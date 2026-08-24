import asyncio
import json
import os
import sys
import time
import threading
import urllib.request
import uuid

# Windows defaults stdout/stderr to the system codepage (cp1252 here), which raises
# UnicodeEncodeError and crashes the process on any print() containing an emoji or other
# non-cp1252 character — e.g. the 🚨/⚠️ notification icons, or unicode text a future Gemini
# response might contain. Force UTF-8 so that class of crash can't happen. Only console
# streams support reconfigure (redirected-to-file streams from `run_in_background` do
# too, but guard anyway in case stdout has been replaced by something that doesn't).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import cv2
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from ultralytics import YOLO

app = FastAPI(title="Smart Factory HSE API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Paths, model registry, runtime config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(BASE_DIR, "VIdeo Testing")
MODEL_DIR = os.path.join(BASE_DIR, "model dan dataset")


def _load_dotenv(path):
    """Minimal .env loader (no external dependency). Real environment variables that
    are already set take precedence over the file — same behavior as python-dotenv."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, val)


_load_dotenv(os.path.join(BASE_DIR, ".env"))

MODEL_REGISTRY = {
    "yolov11m": {"label": "YOLOv11m", "path": os.path.join(MODEL_DIR, "yolo v11.pt")},
    "yolo26m": {"label": "YOLO26m", "path": os.path.join(MODEL_DIR, "yolo v26.pt")},
}
DEFAULT_MODEL = "yolo26m"

# Global runtime state (guarded where written from request threads)
active_model_id = DEFAULT_MODEL
active_confidence = 0.25

# --- AI Agent: message wording via Gemini (free tier), dispatch to a notify channel ----
# All optional. If unset, notify_safety() falls back to fixed template text and skips
# external dispatch — the app runs fine without any of this configured.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
# Notification channel — Discord webhook (simplest: one URL, no bot). Telegram kept as a
# fallback option. dispatch_message() prefers Discord when both are set.
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
# Optional SECOND Discord channel, just for "action taken" updates — lets you split new
# detections from remediation follow-ups into two channels. Falls back to the main
# channel above if left unset.
DISCORD_WEBHOOK_URL_ACTIONS = os.environ.get("DISCORD_WEBHOOK_URL_ACTIONS", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Default video files for the two dummy streams
DEFAULT_VIDEOS = ["WIN_20260821_01_16_00_Pro.mp4", "WIN_20260821_01_16_15_Pro.mp4"]

STREAM_SOURCES = {
    "stream_01": os.path.join(VIDEO_DIR, DEFAULT_VIDEOS[0]),
    "stream_02": os.path.join(VIDEO_DIR, DEFAULT_VIDEOS[1]),
}

# Human-readable source token per stream (for the API / UI)
stream_source_tokens = {
    "stream_01": DEFAULT_VIDEOS[0],
    "stream_02": DEFAULT_VIDEOS[1],
}


def list_video_files():
    """Video files actually present in VIdeo Testing/."""
    if not os.path.isdir(VIDEO_DIR):
        return []
    return sorted(
        f for f in os.listdir(VIDEO_DIR)
        if f.lower().endswith((".mp4", ".avi", ".mov", ".mkv"))
    )


def resolve_source(token):
    """Map a UI source token to an OpenCV source. Rejects arbitrary paths.

    Returns (resolved_source, error_message). resolved_source is an int (webcam)
    or an absolute file path; error_message is None on success.
    """
    if token is None:
        return None, "source required"
    if str(token).lower() == "webcam":
        return 0, None
    # Only allow files that actually live in VIDEO_DIR
    if token in list_video_files():
        return os.path.join(VIDEO_DIR, token), None
    return None, "unknown source"


# ---------------------------------------------------------------------------
# Per-zone PPE rules (runtime-editable)
# ---------------------------------------------------------------------------
PPE_TO_VIOLATION = {
    "Hardhat": "NO-Hardhat",
    "Mask": "NO-Mask",
    "Safety Vest": "NO-Safety Vest",
}
ALL_PPE = list(PPE_TO_VIOLATION.keys())
EMERGENCY_CLASSES = {"Fire", "Smoke"}
ALL_EMERGENCY = sorted(EMERGENCY_CLASSES)

# Context classes: detectable, but never a compliance violation (no NO-* pair). Their
# on/off toggle only controls display (bounding boxes + breakdown panel), not rule logic.
CONTEXT_CLASSES = ["Person", "Safety Cone", "machinery", "vehicle"]
context_visibility = {c: True for c in CONTEXT_CLASSES}
context_lock = threading.Lock()

ZONE_RULES = {
    "stream_01": {
        "label": "Assembly Line A (Cam 01)",
        "required": ["Hardhat", "Safety Vest"],
        "emergency": ["Fire", "Smoke"],
    },
    "stream_02": {
        "label": "Welding Bay B (Cam 02)",
        "required": ["Hardhat", "Mask", "Safety Vest"],
        "emergency": ["Fire", "Smoke"],
    },
}


def violation_classes_for(stream_id):
    """The set of NO-* classes that count as violations in a given zone."""
    rule = ZONE_RULES.get(stream_id, {})
    return {PPE_TO_VIOLATION[p] for p in rule.get("required", []) if p in PPE_TO_VIOLATION}


def emergency_classes_for(stream_id):
    """The set of emergency classes (Fire/Smoke) enabled for a given zone."""
    rule = ZONE_RULES.get(stream_id, {})
    return {c for c in rule.get("emergency", []) if c in EMERGENCY_CLASSES}


def is_context_visible(class_name):
    return context_visibility.get(class_name, True)


# ---------------------------------------------------------------------------
# Server-side rule engine state + stub AI Agent
# ---------------------------------------------------------------------------
events = []            # rolling list of structured events, newest first
notifications = []     # AI Agent activity log, newest first
engine_lock = threading.Lock()

# Episode tracking, keyed by "{stream_id}|{cls}" (zone + violation/emergency class) ->
# a LIST of concurrent episodes, one per distinct physical location. We deliberately
# don't key by track_id, since the YOLO tracker reassigns IDs too often to be a reliable
# person identity — instead, episodes are matched by bounding-box overlap (IoU), so two
# people committing the same violation in different spots (at once, or one after the
# other) are recognized as separate occurrences instead of collapsing into one.
# Each entry: {"first_seen_ms", "last_seen_ms", "notified", "last_box"}.
#
# - CONFIRM_MS: a matched episode must persist this long before it's considered real and
#   a notification fires — absorbs single-frame flicker.
# - EPISODE_GAP_MS: an episode not matched by any box for longer than this is dropped —
#   the next box at/near that spot starts a brand new episode (and must reconfirm).
# - MATCH_IOU_THRESHOLD: how much a new box must overlap an existing episode's last known
#   position to be considered "the same occurrence still there" rather than a new one.
#   Known limitation: if a different person happens to stand in nearly the exact same
#   spot within the gap window, they'll be merged into the same episode — an accepted
#   trade-off given there's no reliable per-person identity available.
episodes = {}
CONFIRM_MS = 5_000
EPISODE_GAP_MS = 30_000
MATCH_IOU_THRESHOLD = 0.2
MAX_EVENTS = 100
MAX_NOTIFICATIONS = 100

# Human-referenceable incident number (#1, #2, ...) — the UUID `id` is still the real key
# used everywhere internally/in the API, this is purely a readable label for the UI and
# for admins/the AI Agent to unambiguously refer to "insiden #N" in conversation.
_event_seq_counter = 0


def _iou(box_a, box_b):
    """Intersection-over-union of two [x1,y1,x2,y2] boxes."""
    xa1, ya1, xa2, ya2 = box_a
    xb1, yb1, xb2, yb2 = box_b
    inter_w = max(0.0, min(xa2, xb2) - max(xa1, xb1))
    inter_h = max(0.0, min(ya2, yb2) - max(ya1, yb1))
    inter_area = inter_w * inter_h
    if inter_area <= 0:
        return 0.0
    area_a = max(0.0, xa2 - xa1) * max(0.0, ya2 - ya1)
    area_b = max(0.0, xb2 - xb1) * max(0.0, yb2 - yb1)
    union = area_a + area_b - inter_area
    return inter_area / union if union > 0 else 0.0

latest_detections = {"stream_01": [], "stream_02": []}


def _pct(confidence):
    return f"{round(confidence * 100)}%" if isinstance(confidence, (int, float)) else "—"


def format_notification(event):
    """Deterministic, consistently-formatted notification for a single event — same
    structure every time (bold labels + bullet points), no LLM involved so wording never
    varies from one violation to the next.
    """
    is_emergency = event["type"] == "EMERGENCY"
    icon = "🚨" if is_emergency else "⚠️"
    header = "DARURAT TERDETEKSI" if is_emergency else "PELANGGARAN APD TERDETEKSI"
    action = "Segera evakuasi & hubungi tim darurat" if is_emergency else "Menunggu tindakan tim safety"
    severity = "critical" if is_emergency else "warning"

    lines = [
        f"{icon} **{header}**",
        f"• **Insiden:** #{event.get('seq', '?')}",
        f"• **Zona:** {event['zone']}",
        f"• **Jenis:** {event['class']}",
        f"• **Waktu:** {event['timestamp']}",
        f"• **Confidence:** {_pct(event.get('confidence'))}",
        f"• **Status:** {action}",
    ]
    return "\n".join(lines), severity


def format_batch_notification(batch_events):
    """Deterministic notification covering multiple events that fired close together in
    time — grouped by zone, same bold+bullet structure as the single-event format. This
    is what keeps a burst of near-simultaneous violations to a single external message
    instead of one each.
    """
    has_emergency = any(e["type"] == "EMERGENCY" for e in batch_events)
    icon = "🚨" if has_emergency else "⚠️"
    header = f"{len(batch_events)} KEJADIAN TERDETEKSI BERSAMAAN"
    action = "Segera evakuasi & hubungi tim darurat" if has_emergency else "Menunggu tindakan tim safety"

    by_zone = {}
    for e in batch_events:
        by_zone.setdefault(e["zone"], []).append(e)

    seq_list = ", ".join(f"#{e.get('seq', '?')}" for e in batch_events)
    lines = [f"{icon} **{header}**", f"• **Insiden:** {seq_list}"]
    for zone, evs in by_zone.items():
        items = ", ".join(f"{e['class']} (#{e.get('seq', '?')}, {_pct(e.get('confidence'))})" for e in evs)
        lines.append(f"• **{zone}:** {items}")
    lines.append(f"• **Waktu:** {batch_events[0]['timestamp']}")
    lines.append(f"• **Status:** {action}")
    return "\n".join(lines), ("critical" if has_emergency else "warning")


def format_action_notification(event):
    """Deterministic notification sent when an admin records the remediation taken on a
    CONFIRMED incident — same bold+bullet structure, routed to the 'action' channel."""
    lines = [
        "✅ **TINDAKAN DICATAT**",
        f"• **Insiden:** #{event.get('seq', '?')}",
        f"• **Zona:** {event['zone']}",
        f"• **Jenis Pelanggaran:** {event['class']}",
        f"• **Waktu Kejadian:** {event['timestamp']}",
        f"• **Tindakan:** {event['action_note']}",
        f"• **Dicatat Pukul:** {event['action_at']}",
    ]
    return "\n".join(lines)


def format_delete_notification(event):
    """Deterministic notification sent when an admin deletes an incident (typically a
    duplicate) — this is still logged as the incident's final outcome, not a silent
    removal, so the audit trail stays one-violation-one-outcome. Routed to the 'action'
    channel alongside remediation updates."""
    lines = [
        "🗑️ **INSIDEN DIHAPUS**",
        f"• **Insiden:** #{event.get('seq', '?')}",
        f"• **Zona:** {event['zone']}",
        f"• **Jenis Pelanggaran:** {event['class']}",
        f"• **Waktu Kejadian:** {event['timestamp']}",
        f"• **Alasan:** {event['delete_reason']}",
        f"• **Dihapus Pukul:** {event['deleted_at']}",
    ]
    return "\n".join(lines)


def send_discord(text, webhook_url):
    """Dispatch a message to a specific Discord webhook. Returns True on confirmed delivery."""
    if not webhook_url:
        return False
    body = json.dumps({"content": str(text)[:1900]}).encode()  # Discord caps at 2000 chars
    # A User-Agent header is required — Discord's Cloudflare front rejects the default
    # urllib agent ("Python-urllib/x.y") with 403 Forbidden.
    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "SmartFactoryHSE/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"[AI AGENT] Discord send failed: {e}")
        return False


def send_telegram(text):
    """Dispatch a message via a Telegram bot. Returns True on confirmed delivery.

    Our templates use Discord/CommonMark-style **bold**. Telegram's legacy Markdown
    parse mode uses single-asterisk *bold* instead, so it's converted here — otherwise
    Telegram would show the literal "**" characters instead of rendering bold text.
    """
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return False
    telegram_text = text.replace("**", "*")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    body = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": telegram_text, "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[AI AGENT] Telegram send failed: {e}")
        return False


def configured_channel(purpose="detection"):
    """Which external notify channel is active for a given purpose, or None.

    purpose: "detection" (new events) or "action" (remediation updates — routed to the
    second Discord channel if configured, otherwise falls back to the main one).
    """
    if purpose == "action" and DISCORD_WEBHOOK_URL_ACTIONS:
        return "discord"
    if DISCORD_WEBHOOK_URL:
        return "discord"
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        return "telegram"
    return None


def dispatch_message(text, purpose="detection"):
    """Send to whichever external channel is configured for this purpose. Returns
    (sent, channel)."""
    if purpose == "action" and DISCORD_WEBHOOK_URL_ACTIONS:
        return send_discord(text, DISCORD_WEBHOOK_URL_ACTIONS), "discord"
    channel = configured_channel(purpose)
    if channel == "discord":
        return send_discord(text, DISCORD_WEBHOOK_URL), "discord"
    if channel == "telegram":
        return send_telegram(text), "telegram"
    return False, None


# Batching: events that fire within this window of the FIRST one in a batch are combined
# into a single external message instead of one each — a burst of 3 near-simultaneous
# violations sends 1 Discord/Telegram message, not 3.
BATCH_WINDOW_SECONDS = 2.0
_batch_lock = threading.Lock()
_batch_pending = []   # list of (event, note) accumulated in the current window
_batch_timer = None


def _flush_batch():
    """Runs once, ~BATCH_WINDOW_SECONDS after the first event of a batch arrived."""
    global _batch_timer
    with _batch_lock:
        batch = _batch_pending[:]
        _batch_pending.clear()
        _batch_timer = None

    if not batch:
        return

    batch_events = [e for e, _ in batch]
    batch_notes = [n for _, n in batch]

    if len(batch_events) == 1:
        text, _ = format_notification(batch_events[0])
    else:
        text, _ = format_batch_notification(batch_events)

    sent, channel = dispatch_message(text)

    with engine_lock:
        for note in batch_notes:
            note["message"] = text
            note["dispatched"] = sent
            note["channel"] = channel

    if sent:
        print(f"[AI AGENT] {channel} dispatched (batch of {len(batch_events)}): {text}")


def notify_safety(event):
    """AI Agent entry point: notifies the safety division when an event is raised.

    Builds a consistently-formatted notification immediately (deterministic — same bold
    + bullet-point structure every time, no LLM involved so wording never varies), then
    queues it for a debounced batch: the first event in a new window starts a
    BATCH_WINDOW_SECONDS timer, and everything else that arrives before it fires is
    combined into ONE external message instead of one each.
    """
    msg, severity = format_notification(event)

    note = {
        "id": event["id"],
        "timestamp": event["timestamp"],
        "message": msg,
        "severity": severity,
        "stream_id": event["stream_id"],
        "dispatched": False,
        "channel": None,
    }
    print(f"[AI AGENT] {msg}")
    notifications.insert(0, note)
    del notifications[MAX_NOTIFICATIONS:]

    global _batch_timer
    with _batch_lock:
        _batch_pending.append((event, note))
        if _batch_timer is None:
            _batch_timer = threading.Timer(BATCH_WINDOW_SECONDS, _flush_batch)
            _batch_timer.daemon = True
            _batch_timer.start()


def _log_and_dispatch_outcome(note_id, timestamp, text, severity, stream_id, log_label):
    """Shared by notify_action_taken / notify_deleted: log immediately, dispatch to the
    'action' channel in the background. Not part of the detection batching window — these
    are deliberate one-off admin actions, not a burst of automatic detections."""
    note = {
        "id": note_id,
        "timestamp": timestamp,
        "message": text,
        "severity": severity,
        "stream_id": stream_id,
        "dispatched": False,
        "channel": None,
    }
    print(f"[AI AGENT] {text}")
    notifications.insert(0, note)
    del notifications[MAX_NOTIFICATIONS:]

    def _send():
        sent, channel = dispatch_message(text, purpose="action")
        with engine_lock:
            note["dispatched"] = sent
            note["channel"] = channel
        if sent:
            print(f"[AI AGENT] {channel} dispatched ({log_label}): {text}")

    threading.Thread(target=_send, daemon=True).start()


def notify_action_taken(event):
    """Notification when an admin records remediation on a CONFIRMED incident."""
    _log_and_dispatch_outcome(
        f"{event['id']}-action", event["action_at"], format_action_notification(event),
        "resolved", event["stream_id"], "action taken",
    )


def notify_deleted(event):
    """Notification when an admin deletes an incident (e.g. a duplicate) — still logged
    as the incident's final outcome, not a silent removal."""
    _log_and_dispatch_outcome(
        f"{event['id']}-deleted", event["deleted_at"], format_delete_notification(event),
        "deleted", event["stream_id"], "incident deleted",
    )


def process_rules(stream_id, boxes):
    """Server-side rule engine. Turns raw detections into structured events.

    Episode model, keyed by zone+class with spatial (IoU) matching across concurrent
    episodes (see `episodes` docstring above) — deliberately ignores track_id since the
    tracker can't reliably re-identify a person; position across consecutive frames is
    a much more stable signal than its assigned ID.
    Called from each camera's ai_loop (multiple threads) -> guarded by engine_lock.
    """
    now_ms = time.time() * 1000
    zone = ZONE_RULES.get(stream_id, {}).get("label", stream_id)
    violation_classes = violation_classes_for(stream_id)
    zone_emergency_classes = emergency_classes_for(stream_id)

    with engine_lock:
        for box in boxes:
            cls = box["class_name"]
            if cls in violation_classes:
                event_type = "VIOLATION"
            elif cls in zone_emergency_classes:
                event_type = "EMERGENCY"
            else:
                continue

            key = f"{stream_id}|{cls}"
            box_xyxy = box.get("xyxy")
            # Drop episodes that haven't been matched in a while — also prevents a stale
            # position from wrongly absorbing an unrelated future occurrence.
            active = [e for e in episodes.get(key, []) if now_ms - e["last_seen_ms"] <= EPISODE_GAP_MS]

            match = None
            if box_xyxy:
                best_iou = MATCH_IOU_THRESHOLD
                for ep in active:
                    iou = _iou(box_xyxy, ep["last_box"])
                    if iou >= best_iou:
                        best_iou = iou
                        match = ep

            if match is not None:
                match["last_seen_ms"] = now_ms
                match["last_box"] = box_xyxy
                state = match
            else:
                # No existing episode overlaps this box's position -> a distinct
                # occurrence (different person / different spot), even if another
                # episode of the same class is still active elsewhere in this zone.
                state = {
                    "first_seen_ms": now_ms,
                    "last_seen_ms": now_ms,
                    "notified": False,
                    "last_box": box_xyxy or [0, 0, 0, 0],
                }
                active.append(state)

            episodes[key] = active

            if not state["notified"] and (now_ms - state["first_seen_ms"]) >= CONFIRM_MS:
                state["notified"] = True
                global _event_seq_counter
                _event_seq_counter += 1
                event = {
                    "id": str(uuid.uuid4()),
                    "seq": _event_seq_counter,  # human-referenceable incident number (#1, #2, ...)
                    "timestamp": time.strftime("%H:%M:%S"),
                    "ts_ms": now_ms,  # epoch ms, for the agent's "last N minutes" filtering
                    "stream_id": stream_id,
                    "zone": zone,
                    "type": event_type,
                    "class": cls,
                    "track_id": box.get("track_id"),
                    "confidence": box.get("confidence"),
                    "status": "PENDING",       # PENDING -> CONFIRMED | DISMISSED -> (or DELETED)
                    "verified_at": None,
                    "action_taken": False,     # remediation recorded on a CONFIRMED event
                    "action_note": None,
                    "action_at": None,
                    "deleted": False,          # one violation, one final outcome: either a real
                    "delete_reason": None,     # action above, OR deleted here as a duplicate —
                    "deleted_at": None,        # these two are mutually exclusive.
                }
                events.insert(0, event)
                del events[MAX_EVENTS:]
                notify_safety(event)

            # Surface the rule engine's decision back on the box itself, so the UI can
            # show which detections are suppressed (already notified this episode) vs
            # still pending confirmation.
            box["episode_status"] = "notified" if state["notified"] else "pending"


# ---------------------------------------------------------------------------
# Camera manager — single shared capture feeding AI + rendering
# ---------------------------------------------------------------------------
class SmoothCameraManager:
    def __init__(self, source, stream_id):
        self.stream_id = stream_id
        self.source = source
        self.source_version = 0
        self.source_lock = threading.Lock()

        self.model = YOLO(MODEL_REGISTRY[DEFAULT_MODEL]["path"])
        self.model_lock = threading.Lock()

        self.latest_frame = None          # raw frame from the single capture
        self.frame_lock = threading.Lock()
        self.current_frame_bytes = None   # rendered JPEG for streaming
        self.latest_boxes = []
        self.running = True
        self.paused = True  # start paused — nothing captured/detected until an admin resumes it

        self.capture_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.capture_thread.start()

        self.ai_thread = threading.Thread(target=self.ai_loop, daemon=True)
        self.ai_thread.start()

        self.render_thread = threading.Thread(target=self.render_loop, daemon=True)
        self.render_thread.start()

    # -- source control ------------------------------------------------------
    def switch_source(self, resolved):
        with self.source_lock:
            self.source = resolved
            self.source_version += 1

    def switch_model(self, path):
        new_model = YOLO(path)  # heavy load done outside the lock
        with self.model_lock:
            self.model = new_model
            self.latest_boxes = []

    def set_paused(self, value):
        self.paused = bool(value)

    # -- threads -------------------------------------------------------------
    def capture_loop(self):
        cap = cv2.VideoCapture(self.source)
        local_version = self.source_version
        is_file = isinstance(self.source, str)

        while self.running:
            # Reopen if the source changed
            if self.source_version != local_version:
                cap.release()
                with self.source_lock:
                    local_version = self.source_version
                    new_source = self.source
                cap = cv2.VideoCapture(new_source)
                is_file = isinstance(new_source, str)

            if self.paused:
                time.sleep(0.15)  # freeze feed, stop reading — lighter during testing
                continue

            success, frame = cap.read()
            if not success:
                if is_file:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop the dummy video
                else:
                    time.sleep(0.1)  # webcam hiccup, retry
                continue

            frame = cv2.resize(frame, (640, 480))
            with self.frame_lock:
                self.latest_frame = frame

            time.sleep(0.01)

        cap.release()

    def ai_loop(self):
        while self.running:
            if self.paused:
                time.sleep(0.15)  # skip inference — the expensive part — while paused
                continue

            with self.frame_lock:
                frame = None if self.latest_frame is None else self.latest_frame.copy()

            if frame is None:
                time.sleep(0.02)
                continue

            with self.model_lock:
                results = self.model.track(
                    frame, persist=True, conf=active_confidence, verbose=False
                )

            boxes_data = []
            for box in results[0].boxes:
                track_id = int(box.id[0]) if box.id is not None else None
                boxes_data.append({
                    "class_name": self.model.names[int(box.cls)],
                    "confidence": round(float(box.conf), 2),
                    "track_id": track_id,
                    "xyxy": box.xyxy[0].tolist(),
                })

            self.latest_boxes = boxes_data
            process_rules(self.stream_id, boxes_data)  # tags violation/emergency boxes with episode_status

            latest_detections[self.stream_id] = [
                {
                    "class_name": d["class_name"],
                    "confidence": d["confidence"],
                    "track_id": d["track_id"],
                    "episode_status": d.get("episode_status"),
                }
                for d in boxes_data
            ]

            time.sleep(0.02)

    def render_loop(self):
        while self.running:
            with self.frame_lock:
                frame = None if self.latest_frame is None else self.latest_frame.copy()

            if frame is None:
                time.sleep(0.03)
                continue

            for box in self.latest_boxes:
                if box["class_name"] in CONTEXT_CLASSES and not is_context_visible(box["class_name"]):
                    continue

                coords = box["xyxy"]
                x1, y1, x2, y2 = int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3])

                cls_upper = box["class_name"].upper()
                if "NO-" in cls_upper:
                    color = (0, 0, 255)        # red — violation
                elif box["class_name"] in EMERGENCY_CLASSES:
                    color = (0, 128, 255)      # orange — emergency
                else:
                    color = (0, 255, 0)        # green — compliant/neutral

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

                label = f"{box['class_name']} {box['confidence']}"
                (text_width, text_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)

                if y1 - 20 < 0:
                    text_y = y1 + text_height + 10
                    plate_y1 = y1
                    plate_y2 = y1 + text_height + 15
                else:
                    text_y = y1 - 10
                    plate_y1 = y1 - text_height - 15
                    plate_y2 = y1

                cv2.rectangle(frame, (x1, plate_y1), (x1 + text_width, plate_y2), color, -1)
                cv2.putText(frame, label, (x1, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            self.current_frame_bytes = buffer.tobytes()

            time.sleep(0.033)

    def get_frame(self):
        return self.current_frame_bytes


cameras = {stream_id: SmoothCameraManager(src, stream_id) for stream_id, src in STREAM_SOURCES.items()}


# ---------------------------------------------------------------------------
# Action helpers — single source of truth shared by REST routes AND the AI Agent's
# confirmed actions, so both paths behave identically and validate the same way.
# ---------------------------------------------------------------------------
def apply_model(model_id):
    global active_model_id
    if model_id not in MODEL_REGISTRY:
        return {"status": "error", "message": "unknown model"}
    path = MODEL_REGISTRY[model_id]["path"]
    for cam in cameras.values():
        cam.switch_model(path)
    active_model_id = model_id
    return {"status": "success", "active": active_model_id}


def apply_confidence(value):
    global active_confidence
    active_confidence = max(0.1, min(0.95, float(value)))
    return {"status": "success", "confidence": active_confidence}


def apply_zone_rules(stream_id, required=None, emergency=None):
    if stream_id not in ZONE_RULES:
        return {"status": "error", "message": "unknown zone"}
    if required is not None:
        ZONE_RULES[stream_id]["required"] = [p for p in required if p in PPE_TO_VIOLATION]
    if emergency is not None:
        ZONE_RULES[stream_id]["emergency"] = [c for c in emergency if c in EMERGENCY_CLASSES]
    return {
        "status": "success",
        "stream_id": stream_id,
        "required": ZONE_RULES[stream_id]["required"],
        "emergency": ZONE_RULES[stream_id].get("emergency", []),
    }


def apply_context_visibility(class_name, visible):
    if class_name not in CONTEXT_CLASSES:
        return {"status": "error", "message": "unknown class"}
    with context_lock:
        context_visibility[class_name] = bool(visible)
    return {"status": "success", "class": class_name, "visible": bool(visible)}


def apply_pause(stream_id, paused):
    cam = cameras.get(stream_id)
    if not cam:
        return {"status": "error", "message": "unknown stream"}
    cam.set_paused(bool(paused))
    return {"status": "success", "stream_id": stream_id, "paused": cam.paused}


def apply_source(stream_id, token):
    cam = cameras.get(stream_id)
    if not cam:
        return {"status": "error", "message": "unknown stream"}
    resolved, err = resolve_source(token)
    if err:
        return {"status": "error", "message": err}
    cam.switch_source(resolved)
    stream_source_tokens[stream_id] = "Webcam" if resolved == 0 else token
    return {"status": "success", "stream_id": stream_id, "source": stream_source_tokens[stream_id]}


# ---------------------------------------------------------------------------
# Video streaming endpoints
# ---------------------------------------------------------------------------
async def generate_video_stream(request: Request, stream_id: str):
    camera = cameras.get(stream_id)
    if not camera:
        return

    while True:
        if await request.is_disconnected():
            break

        frame = camera.get_frame()
        if frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

        await asyncio.sleep(0.033)


@app.get("/api/video/{stream_id}")
async def video_feed(request: Request, stream_id: str):
    return StreamingResponse(
        generate_video_stream(request, stream_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/data/{stream_id}")
async def stream_data(stream_id: str):
    cam = cameras.get(stream_id)
    visible = [
        d for d in latest_detections.get(stream_id, [])
        if d["class_name"] not in CONTEXT_CLASSES or is_context_visible(d["class_name"])
    ]
    return {
        "status": "success",
        "detections": visible,
        "paused": bool(cam.paused) if cam else False,
    }


# ---------------------------------------------------------------------------
# Health / model / config endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/models")
def get_models():
    return {
        "active": active_model_id,
        "confidence": active_confidence,
        "models": [{"id": k, "label": v["label"]} for k, v in MODEL_REGISTRY.items()],
    }


class ModelSelect(BaseModel):
    id: str


@app.post("/api/model/select")
def select_model(req: ModelSelect):
    return apply_model(req.id)


class ConfidenceSet(BaseModel):
    confidence: float


@app.post("/api/config/confidence")
def set_confidence(req: ConfidenceSet):
    return apply_confidence(req.confidence)


# ---------------------------------------------------------------------------
# Zone rule endpoints
# ---------------------------------------------------------------------------
@app.get("/api/zones")
def get_zones():
    return {
        "all_ppe": ALL_PPE,
        "all_emergency": ALL_EMERGENCY,
        "zones": [
            {
                "stream_id": sid,
                "label": rule["label"],
                "required": rule["required"],
                "emergency": rule.get("emergency", []),
            }
            for sid, rule in ZONE_RULES.items()
        ],
    }


class ZoneUpdate(BaseModel):
    required: list[str] | None = None
    emergency: list[str] | None = None


@app.post("/api/zones/{stream_id}")
def update_zone(stream_id: str, req: ZoneUpdate):
    return apply_zone_rules(stream_id, req.required, req.emergency)


# ---------------------------------------------------------------------------
# Context class display filter (Person / Safety Cone / machinery / vehicle)
# ---------------------------------------------------------------------------
@app.get("/api/context-classes")
def get_context_classes():
    return {"classes": CONTEXT_CLASSES, "visible": dict(context_visibility)}


class ContextVisibilitySet(BaseModel):
    visible: bool


@app.post("/api/context-classes/{class_name}")
def set_context_visibility(class_name: str, req: ContextVisibilitySet):
    return apply_context_visibility(class_name, req.visible)


# ---------------------------------------------------------------------------
# Events + AI Agent notification endpoints
# ---------------------------------------------------------------------------
@app.get("/api/events")
def get_events():
    with engine_lock:
        return {"status": "success", "events": list(events)}


class EventVerify(BaseModel):
    status: str  # "CONFIRMED" | "DISMISSED"


@app.post("/api/events/{event_id}/verify")
def verify_event(event_id: str, req: EventVerify):
    """Admin marks a PENDING incident as a real violation (CONFIRMED) or a false
    detection (DISMISSED). This is the step that makes the incident queryable by the AI
    Agent and eligible to have a remediation action recorded against it."""
    status = req.status.upper()
    if status not in ("CONFIRMED", "DISMISSED"):
        return {"status": "error", "message": "status harus CONFIRMED atau DISMISSED"}
    with engine_lock:
        event = next((e for e in events if e["id"] == event_id), None)
        if not event:
            return {"status": "error", "message": "event tidak ditemukan"}
        event["status"] = status
        event["verified_at"] = time.strftime("%H:%M:%S")
        result = dict(event)
    return {"status": "success", "event": result}


class EventAction(BaseModel):
    action_note: str


@app.post("/api/events/{event_id}/action")
def record_action(event_id: str, req: EventAction):
    """Admin records what remediation was taken on a CONFIRMED incident. Completes the
    tracking cycle: PENDING -> CONFIRMED -> action taken/note — all queryable by the
    AI Agent, and dispatches a notification to the 'action' channel."""
    note_text = req.action_note.strip()
    if not note_text:
        return {"status": "error", "message": "catatan tindakan tidak boleh kosong"}
    with engine_lock:
        event = next((e for e in events if e["id"] == event_id), None)
        if not event:
            return {"status": "error", "message": "event tidak ditemukan"}
        if event["status"] != "CONFIRMED":
            return {"status": "error", "message": "hanya insiden berstatus CONFIRMED yang bisa dicatat tindakannya"}
        event["action_taken"] = True
        event["action_note"] = note_text
        event["action_at"] = time.strftime("%H:%M:%S")
        result = dict(event)

    notify_action_taken(result)
    return {"status": "success", "event": result}


class EventDelete(BaseModel):
    reason: str = "Duplikat"


@app.post("/api/events/{event_id}/delete")
def delete_event(event_id: str, req: EventDelete):
    """Admin deletes an incident — typically a duplicate (e.g. the same physical event
    got split into two episodes). Not a silent removal: it's still logged as that
    incident's final outcome (status DELETED + reason), so every violation ends up with
    exactly one documented resolution — either a real action taken, or a deletion here.
    Works from any status except an already-deleted incident."""
    reason = (req.reason or "Duplikat").strip() or "Duplikat"
    with engine_lock:
        event = next((e for e in events if e["id"] == event_id), None)
        if not event:
            return {"status": "error", "message": "event tidak ditemukan"}
        if event["status"] == "DELETED":
            return {"status": "error", "message": "insiden ini sudah dihapus sebelumnya"}
        event["status"] = "DELETED"
        event["deleted"] = True
        event["delete_reason"] = reason
        event["deleted_at"] = time.strftime("%H:%M:%S")
        result = dict(event)

    notify_deleted(result)
    return {"status": "success", "event": result}


@app.get("/api/notifications")
def get_notifications():
    with engine_lock:
        return {"status": "success", "notifications": list(notifications)}


# ---------------------------------------------------------------------------
# Source selection endpoints
# ---------------------------------------------------------------------------
@app.get("/api/sources")
def get_sources():
    return {
        "options": ["Webcam"] + list_video_files(),
        "current": dict(stream_source_tokens),
        "paused": {sid: bool(cam.paused) for sid, cam in cameras.items()},
    }


class SourceSet(BaseModel):
    source: str


@app.post("/api/stream/{stream_id}/source")
def set_source(stream_id: str, req: SourceSet):
    return apply_source(stream_id, req.source)


class PauseSet(BaseModel):
    paused: bool


@app.post("/api/stream/{stream_id}/pause")
def set_pause(stream_id: str, req: PauseSet):
    return apply_pause(stream_id, req.paused)


# ---------------------------------------------------------------------------
# AI Agent — conversational assistant with tool calling (Gemini function calling).
# READ tools run inline (safe). ACTION tools are NOT run here — they're returned to
# the UI as a pending action that a human confirms, then executed via /api/agent/execute.
# ---------------------------------------------------------------------------
def _agent_get_events(zone="", violation_class="", event_type="", since_minutes=0, status=""):
    with engine_lock:
        result = list(events)
    if zone:
        z = str(zone).lower()
        result = [e for e in result if z in e["zone"].lower() or z in e["stream_id"].lower()]
    if violation_class:
        vc = str(violation_class).lower()
        result = [e for e in result if vc in e["class"].lower()]
    if event_type:
        et = str(event_type).upper()
        result = [e for e in result if e["type"] == et]
    if status:
        st = str(status).upper()
        result = [e for e in result if e["status"] == st]
    try:
        since_minutes = int(since_minutes or 0)
    except (TypeError, ValueError):
        since_minutes = 0
    if since_minutes > 0:
        cutoff = time.time() * 1000 - since_minutes * 60_000
        result = [e for e in result if e.get("ts_ms", 0) >= cutoff]
    return {"count": len(result), "events": result[:50]}


def _agent_get_notifications():
    with engine_lock:
        return {"count": len(notifications), "notifications": list(notifications)[:50]}


def _agent_get_zone_config():
    return get_zones()


def _agent_get_stream_status():
    return get_sources()


def _agent_get_system_config():
    return {
        "active_model": active_model_id,
        "confidence": active_confidence,
        "context_visible": dict(context_visibility),
    }


def _agent_send_alert(text):
    sent, channel = dispatch_message(str(text))
    if sent:
        return {"status": "success", "sent": True, "channel": channel, "message": f"Terkirim ke {channel}."}
    return {
        "status": "error",
        "sent": False,
        "message": "Gagal kirim — belum ada channel notifikasi yang aktif (isi DISCORD_WEBHOOK_URL di .env).",
    }


READ_TOOLS = {
    "get_events": _agent_get_events,
    "get_notifications": _agent_get_notifications,
    "get_zone_config": _agent_get_zone_config,
    "get_stream_status": _agent_get_stream_status,
    "get_system_config": _agent_get_system_config,
}

ACTION_TOOLS = {
    "send_alert_message": lambda text: _agent_send_alert(text),
    "set_zone_rules": lambda stream_id, required=None, emergency=None: apply_zone_rules(stream_id, required, emergency),
    "set_confidence": lambda confidence: apply_confidence(confidence),
    "set_stream_paused": lambda stream_id, paused: apply_pause(stream_id, paused),
    "select_model": lambda model_id: apply_model(model_id),
    "set_context_visibility": lambda class_name, visible: apply_context_visibility(class_name, visible),
}

AGENT_FUNCTION_DECLARATIONS = [
    {
        "name": "get_events",
        "description": (
            "Ambil daftar event pelanggaran APD / darurat yang tercatat sistem. Tiap event punya "
            "'seq' (nomor insiden referensi, mis. #7), status siklus penuh (PENDING/CONFIRMED/"
            "DISMISSED/DELETED), dan detail tindakan/penghapusan jika ada (action_taken, "
            "action_note, action_at, deleted, delete_reason, deleted_at). Bisa difilter."
        ),
        "parameters": {"type": "OBJECT", "properties": {
            "zone": {"type": "STRING", "description": "Filter nama zona atau stream_id, mis. 'Welding' atau 'stream_02'. Kosongkan untuk semua."},
            "violation_class": {"type": "STRING", "description": "Filter kelas, mis. 'NO-Mask', 'Fire'. Kosongkan untuk semua."},
            "event_type": {"type": "STRING", "description": "'VIOLATION' atau 'EMERGENCY'. Kosongkan untuk semua."},
            "since_minutes": {"type": "INTEGER", "description": "Hanya event dalam N menit terakhir. 0 = semua."},
            "status": {"type": "STRING", "description": "'PENDING' (belum ditinjau admin), 'CONFIRMED' (sudah dikonfirmasi asli), 'DISMISSED' (dianggap salah deteksi saat review), atau 'DELETED' (dihapus admin, biasanya duplikat). Kosongkan untuk semua."},
        }},
    },
    {"name": "get_notifications", "description": "Ambil log aktivitas notifikasi yang sudah dikirim AI Agent.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "get_zone_config", "description": "Ambil konfigurasi aturan tiap zona: PPE wajib dan kelas darurat yang aktif.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "get_stream_status", "description": "Ambil status tiap stream/kamera: sumber (video/webcam) dan apakah sedang di-pause.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "get_system_config", "description": "Ambil konfigurasi sistem: model deteksi aktif, confidence threshold, visibilitas kelas konteks.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {
        "name": "send_alert_message",
        "description": "Kirim pesan/laporan ke channel safety (Discord/Telegram). Susun teksnya sendiri berdasarkan data.",
        "parameters": {"type": "OBJECT", "properties": {
            "text": {"type": "STRING", "description": "Isi pesan yang akan dikirim."},
        }, "required": ["text"]},
    },
    {
        "name": "set_zone_rules",
        "description": "Ubah aturan sebuah zona. stream_01=Assembly Line A, stream_02=Welding Bay B.",
        "parameters": {"type": "OBJECT", "properties": {
            "stream_id": {"type": "STRING", "description": "'stream_01' atau 'stream_02'."},
            "required": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Daftar PPE wajib: Hardhat, Mask, Safety Vest. Hilangkan bila tak diubah."},
            "emergency": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Daftar kelas darurat aktif: Fire, Smoke. Hilangkan bila tak diubah."},
        }, "required": ["stream_id"]},
    },
    {
        "name": "set_confidence",
        "description": "Ubah confidence threshold deteksi (0.1 - 0.95).",
        "parameters": {"type": "OBJECT", "properties": {
            "confidence": {"type": "NUMBER", "description": "Nilai 0.1 sampai 0.95, mis. 0.7 untuk 70%."},
        }, "required": ["confidence"]},
    },
    {
        "name": "set_stream_paused",
        "description": "Pause atau resume sebuah stream/kamera.",
        "parameters": {"type": "OBJECT", "properties": {
            "stream_id": {"type": "STRING", "description": "'stream_01' atau 'stream_02'."},
            "paused": {"type": "BOOLEAN", "description": "true = pause, false = resume."},
        }, "required": ["stream_id", "paused"]},
    },
    {
        "name": "select_model",
        "description": "Ganti model deteksi YOLO.",
        "parameters": {"type": "OBJECT", "properties": {
            "model_id": {"type": "STRING", "description": "'yolov11m' atau 'yolo26m'."},
        }, "required": ["model_id"]},
    },
    {
        "name": "set_context_visibility",
        "description": "Tampilkan/sembunyikan kelas konteks di overlay: Person, Safety Cone, machinery, vehicle.",
        "parameters": {"type": "OBJECT", "properties": {
            "class_name": {"type": "STRING", "description": "Person, Safety Cone, machinery, atau vehicle."},
            "visible": {"type": "BOOLEAN", "description": "true = tampilkan, false = sembunyikan."},
        }, "required": ["class_name", "visible"]},
    },
]

AGENT_SYSTEM_PROMPT = (
    "Kamu adalah AI Agent asisten keselamatan kerja (HSE) untuk dashboard Smart Factory. "
    "Jawab dalam Bahasa Indonesia, ringkas dan profesional. "
    "Selalu gunakan tools untuk mengambil data nyata sebelum menjawab pertanyaan tentang kondisi/insiden — "
    "jangan mengarang angka. "
    "Untuk permintaan yang mengubah sistem atau mengirim pesan, panggil function aksi yang sesuai satu kali; "
    "sistem akan meminta konfirmasi manusia sebelum benar-benar menjalankannya, jadi kamu tidak perlu meminta izin lagi. "
    "Konteks: stream_01 = Assembly Line A, stream_02 = Welding Bay B. "
    "Kelas pelanggaran APD: NO-Hardhat, NO-Mask, NO-Safety Vest. Kelas darurat: Fire, Smoke. "
    "Setiap insiden punya nomor referensi 'seq' (mis. #7) yang tetap sama sepanjang siklus "
    "hidupnya — selalu sebutkan nomor ini saat membahas insiden tertentu, jangan pakai UUID panjang. "
    "Siklus status penuh: PENDING (baru terdeteksi, belum ditinjau admin) -> CONFIRMED (admin "
    "memastikan ini pelanggaran asli) atau DISMISSED (admin menandai ini salah deteksi) -> jika "
    "CONFIRMED, admin bisa mencatat tindakan (action_taken=true, action_note berisi tindakan yang "
    "diambil, action_at waktunya) ATAU menghapusnya sebagai duplikat (status jadi DELETED, "
    "delete_reason berisi alasan, deleted_at waktunya) — satu insiden selalu berakhir dengan tepat "
    "satu hasil akhir: tindakan nyata ATAU dihapus sebagai duplikat, tidak keduanya. Kalau ditanya "
    "status suatu insiden atau tindakan apa yang diambil, gunakan get_events dan baca field "
    "status/action_taken/action_note/action_at/deleted/delete_reason — jangan mengarang."
)


def describe_action(name, args):
    if name == "send_alert_message":
        return f'Kirim pesan ke channel safety:\n"{args.get("text", "")}"'
    if name == "set_zone_rules":
        parts = []
        if args.get("required") is not None:
            parts.append(f"PPE wajib = {args.get('required')}")
        if args.get("emergency") is not None:
            parts.append(f"deteksi darurat = {args.get('emergency')}")
        return f"Ubah aturan zona {args.get('stream_id')}: " + (", ".join(parts) if parts else "(tidak ada perubahan)")
    if name == "set_confidence":
        try:
            pct = round(float(args.get("confidence", 0)) * 100)
        except (TypeError, ValueError):
            pct = args.get("confidence")
        return f"Ubah confidence threshold ke {pct}%"
    if name == "set_stream_paused":
        return f"{'Pause' if args.get('paused') else 'Resume'} stream {args.get('stream_id')}"
    if name == "select_model":
        return f"Ganti model deteksi ke {args.get('model_id')}"
    if name == "set_context_visibility":
        return f"{'Tampilkan' if args.get('visible') else 'Sembunyikan'} kelas '{args.get('class_name')}' di layar"
    return name


def _summarize_tool_result(name, result):
    """Short human-readable summary of a read-tool's result, shown live in the UI —
    not the raw JSON, just enough to say what the agent found."""
    try:
        if name == "get_events":
            return f"{result['count']} event ditemukan"
        if name == "get_notifications":
            return f"{result['count']} notifikasi ditemukan"
        if name == "get_zone_config":
            return f"{len(result['zones'])} zona dimuat"
        if name == "get_stream_status":
            return f"status {len(result.get('current', {}))} stream dimuat"
        if name == "get_system_config":
            return f"model aktif: {result.get('active_model')}, confidence: {result.get('confidence')}"
    except Exception:
        pass
    return "selesai"


TOOL_LABELS = {
    "get_events": "Mengambil data event pelanggaran/darurat",
    "get_notifications": "Mengambil log notifikasi",
    "get_zone_config": "Mengambil konfigurasi zona",
    "get_stream_status": "Mengecek status stream/kamera",
    "get_system_config": "Mengecek konfigurasi sistem",
}


def run_agent_chat_steps(history):
    """Generator: yields step dicts live as the agent reasons/calls tools, ending with
    a 'final' (or 'action_proposed'/'error'/'not_configured') step. Shared by both the
    streaming endpoint (yields each step to the UI) and the plain endpoint (drains this
    generator and returns only the last step, for simple non-streaming callers)."""
    if not GEMINI_API_KEY:
        yield {
            "step": "not_configured",
            "configured": False,
            "reply": "AI Agent belum aktif. Isi GEMINI_API_KEY di file .env untuk mengaktifkan chat.",
            "pending_action": None,
        }
        return

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    tool = types.Tool(function_declarations=AGENT_FUNCTION_DECLARATIONS)
    config = types.GenerateContentConfig(
        system_instruction=AGENT_SYSTEM_PROMPT,
        tools=[tool],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    contents = []
    for m in history:
        role = "user" if m.get("role") == "user" else "model"
        text = m.get("text", "")
        if text:
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))

    try:
        for round_num in range(6):  # bounded tool-calling loop
            yield {"step": "thinking", "round": round_num + 1}
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=contents, config=config)
            calls = list(resp.function_calls or [])

            action_call = next((c for c in calls if c.name in ACTION_TOOLS), None)
            if action_call is not None:
                args = dict(action_call.args or {})
                yield {
                    "step": "action_proposed",
                    "configured": True,
                    "reply": (resp.text or "").strip(),
                    "pending_action": {
                        "tool": action_call.name,
                        "args": args,
                        "description": describe_action(action_call.name, args),
                    },
                }
                return

            if calls:  # all read tools -> execute (with live step per tool), feed back, continue
                contents.append(resp.candidates[0].content)
                parts = []
                for c in calls:
                    args = dict(c.args or {})
                    yield {
                        "step": "tool_call",
                        "name": c.name,
                        "label": TOOL_LABELS.get(c.name, c.name),
                        "args": args,
                    }
                    fn = READ_TOOLS.get(c.name)
                    result = fn(**args) if fn else {"error": "unknown tool"}
                    yield {"step": "tool_result", "name": c.name, "summary": _summarize_tool_result(c.name, result)}
                    parts.append(types.Part.from_function_response(name=c.name, response={"result": result}))
                contents.append(types.Content(role="user", parts=parts))
                continue

            yield {"step": "final", "configured": True, "reply": (resp.text or "").strip(), "pending_action": None}
            return

        yield {
            "step": "final",
            "configured": True,
            "reply": "Maaf, langkahnya terlalu panjang. Coba pertanyaan yang lebih spesifik.",
            "pending_action": None,
        }
    except Exception as e:
        print(f"[AI AGENT] chat error: {e}")
        yield {
            "step": "error",
            "configured": True,
            "reply": f"Terjadi kendala saat memproses permintaan: {e}",
            "pending_action": None,
            "error": True,
        }


@app.get("/api/agent/status")
def agent_status():
    return {"configured": bool(GEMINI_API_KEY), "channel": configured_channel()}


class AgentMessage(BaseModel):
    role: str
    text: str


class AgentChatRequest(BaseModel):
    messages: list[AgentMessage]


@app.post("/api/agent/chat")
def agent_chat(req: AgentChatRequest):
    """Non-streaming variant — drains the step generator, returns only the final step.
    Kept for simple callers (curl/tests); the UI uses /api/agent/chat/stream instead."""
    history = [{"role": m.role, "text": m.text} for m in req.messages]
    last = None
    for step in run_agent_chat_steps(history):
        last = step
    return last or {"configured": False, "reply": "", "pending_action": None}


@app.post("/api/agent/chat/stream")
def agent_chat_stream(req: AgentChatRequest):
    """Streaming variant (newline-delimited JSON) — the UI renders each step live as the
    agent works: which tool it's calling, what it found, then the final reply/action."""
    history = [{"role": m.role, "text": m.text} for m in req.messages]

    def generate():
        for step in run_agent_chat_steps(history):
            yield json.dumps(step, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


class AgentExecuteRequest(BaseModel):
    tool: str
    args: dict = {}


@app.post("/api/agent/execute")
def agent_execute(req: AgentExecuteRequest):
    if req.tool not in ACTION_TOOLS:
        return {"status": "error", "message": "Aksi tidak dikenal atau tidak diizinkan."}
    try:
        result = ACTION_TOOLS[req.tool](**req.args)
    except TypeError as e:
        return {"status": "error", "message": f"Argumen tidak valid: {e}"}
    return {"status": "success", "tool": req.tool, "result": result}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
