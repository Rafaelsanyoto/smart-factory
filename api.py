import asyncio
import json
import os
import time
import threading
import urllib.request
import uuid

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

MODEL_REGISTRY = {
    "yolov11m": {"label": "YOLOv11m", "path": os.path.join(MODEL_DIR, "yolo v11.pt")},
    "yolo26m": {"label": "YOLO26m", "path": os.path.join(MODEL_DIR, "yolo v26.pt")},
}
DEFAULT_MODEL = "yolov11m"

# Global runtime state (guarded where written from request threads)
active_model_id = DEFAULT_MODEL
active_confidence = 0.25

# --- AI Agent: message wording via Gemini (free tier), dispatch via Telegram ---------
# Both are optional. If unset, notify_safety() falls back to a fixed template and skips
# external dispatch — the app runs fine without any of this configured.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
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
active_keys = {}       # track-level dedup key -> last_seen_ms
class_cooldown = {}    # "{stream_id}|{cls}" -> last event timestamp_ms
notifications = []     # AI Agent activity log, newest first
engine_lock = threading.Lock()

EVENT_EXPIRY_MS = 3000
# Suppresses a fresh event for the same violation/emergency class in the same zone for
# this long after the last one fired — absorbs YOLO tracker ID churn (a person losing and
# regaining a track_id would otherwise look like a "new" person and spam duplicate events).
CLASS_COOLDOWN_MS = 30_000
MAX_EVENTS = 100
MAX_NOTIFICATIONS = 100

latest_detections = {"stream_01": [], "stream_02": []}


def build_fallback_message(event):
    """Fixed-template message — used immediately, and whenever Gemini is unavailable."""
    if event["type"] == "EMERGENCY":
        msg = (
            f"EMERGENCY — {event['class']} detected at {event['zone']}. "
            f"Escalating to safety division immediately."
        )
        return msg, "critical"
    msg = (
        f"PPE violation ({event['class']}) at {event['zone']}. "
        f"Notifying safety division for review."
    )
    return msg, "warning"


def generate_notification_text(event):
    """Ask Gemini to phrase the notification. Returns None on missing key/any failure."""
    if not GEMINI_API_KEY:
        return None
    prompt = (
        "Kamu adalah AI Agent keselamatan kerja (HSE) di sebuah pabrik. Tulis SATU "
        "notifikasi singkat (maksimal 2 kalimat, Bahasa Indonesia, nada profesional dan "
        "tegas) untuk tim safety berdasarkan kejadian berikut:\n"
        f"- Jenis kejadian: {event['type']} ({event['class']})\n"
        f"- Zona: {event['zone']}\n"
        f"- Waktu: {event['timestamp']}\n"
        f"- Confidence deteksi: {event.get('confidence')}\n"
        "Langsung tulis isi notifikasinya saja, tanpa basa-basi atau label tambahan."
    )
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:"
        f"generateContent?key={GEMINI_API_KEY}"
    )
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"[AI AGENT] Gemini generation failed: {e}")
        return None


def send_telegram(text):
    """Dispatch a message via a Telegram bot. Returns True on confirmed delivery."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    body = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[AI AGENT] Telegram send failed: {e}")
        return False


def _dispatch_notification(event, note):
    """Background work: refine wording via Gemini, then send via Telegram.

    Runs off the hot path (ai_loop) so a slow/unavailable network never affects
    detection throughput. Mutates `note` in place — safe even if it has since been
    trimmed out of the `notifications` list.
    """
    generated = generate_notification_text(event)
    text = generated or note["message"]
    sent = send_telegram(text)
    with engine_lock:
        note["message"] = text
        note["source"] = "gemini" if generated else "template"
        note["dispatched"] = sent
    if sent:
        print(f"[AI AGENT] Telegram dispatched: {text}")


def notify_safety(event):
    """AI Agent entry point: notifies the safety division when an event is raised.

    Logs an immediate template-based notification synchronously (always available,
    zero latency — critical for EMERGENCY events), then asynchronously upgrades the
    wording via Gemini and attempts real delivery via Telegram if configured.
    """
    msg, severity = build_fallback_message(event)

    note = {
        "id": event["id"],
        "timestamp": event["timestamp"],
        "message": msg,
        "severity": severity,
        "stream_id": event["stream_id"],
        "source": "template",
        "dispatched": False,
    }
    print(f"[AI AGENT] {msg}")
    notifications.insert(0, note)
    del notifications[MAX_NOTIFICATIONS:]

    threading.Thread(target=_dispatch_notification, args=(event, note), daemon=True).start()


def process_rules(stream_id, boxes):
    """Server-side rule engine. Turns raw detections into structured events.

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

            track_id = box.get("track_id")
            key = f"{stream_id}|{track_id}|{cls}"
            is_new = key not in active_keys
            active_keys[key] = now_ms

            if is_new:
                cooldown_key = f"{stream_id}|{cls}"
                last_fired = class_cooldown.get(cooldown_key, 0)
                if now_ms - last_fired < CLASS_COOLDOWN_MS:
                    continue  # same violation type still cooling down in this zone — skip
                class_cooldown[cooldown_key] = now_ms

                event = {
                    "id": str(uuid.uuid4()),
                    "timestamp": time.strftime("%H:%M:%S"),
                    "stream_id": stream_id,
                    "zone": zone,
                    "type": event_type,
                    "class": cls,
                    "track_id": track_id,
                    "confidence": box.get("confidence"),
                    "status": "PENDING",
                }
                events.insert(0, event)
                del events[MAX_EVENTS:]
                notify_safety(event)

        # Expire keys not seen recently so the same person re-alerts after leaving
        for k in list(active_keys.keys()):
            if now_ms - active_keys[k] > EVENT_EXPIRY_MS:
                del active_keys[k]


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
        self.paused = False

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
            latest_detections[self.stream_id] = [
                {"class_name": d["class_name"], "confidence": d["confidence"], "track_id": d["track_id"]}
                for d in boxes_data
            ]

            process_rules(self.stream_id, boxes_data)
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
    global active_model_id
    if req.id not in MODEL_REGISTRY:
        return {"status": "error", "message": "unknown model"}
    path = MODEL_REGISTRY[req.id]["path"]
    for cam in cameras.values():
        cam.switch_model(path)
    active_model_id = req.id
    return {"status": "success", "active": active_model_id}


class ConfidenceSet(BaseModel):
    confidence: float


@app.post("/api/config/confidence")
def set_confidence(req: ConfidenceSet):
    global active_confidence
    active_confidence = max(0.1, min(0.95, req.confidence))
    return {"status": "success", "confidence": active_confidence}


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
    if stream_id not in ZONE_RULES:
        return {"status": "error", "message": "unknown zone"}
    if req.required is not None:
        ZONE_RULES[stream_id]["required"] = [p for p in req.required if p in PPE_TO_VIOLATION]
    if req.emergency is not None:
        ZONE_RULES[stream_id]["emergency"] = [c for c in req.emergency if c in EMERGENCY_CLASSES]
    return {
        "status": "success",
        "stream_id": stream_id,
        "required": ZONE_RULES[stream_id]["required"],
        "emergency": ZONE_RULES[stream_id].get("emergency", []),
    }


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
    if class_name not in CONTEXT_CLASSES:
        return {"status": "error", "message": "unknown class"}
    with context_lock:
        context_visibility[class_name] = req.visible
    return {"status": "success", "class": class_name, "visible": req.visible}


# ---------------------------------------------------------------------------
# Events + AI Agent notification endpoints
# ---------------------------------------------------------------------------
@app.get("/api/events")
def get_events():
    with engine_lock:
        return {"status": "success", "events": list(events)}


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
    cam = cameras.get(stream_id)
    if not cam:
        return {"status": "error", "message": "unknown stream"}
    resolved, err = resolve_source(req.source)
    if err:
        return {"status": "error", "message": err}
    cam.switch_source(resolved)
    stream_source_tokens[stream_id] = "Webcam" if resolved == 0 else req.source
    return {"status": "success", "stream_id": stream_id, "source": stream_source_tokens[stream_id]}


class PauseSet(BaseModel):
    paused: bool


@app.post("/api/stream/{stream_id}/pause")
def set_pause(stream_id: str, req: PauseSet):
    cam = cameras.get(stream_id)
    if not cam:
        return {"status": "error", "message": "unknown stream"}
    cam.set_paused(req.paused)
    return {"status": "success", "stream_id": stream_id, "paused": cam.paused}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
