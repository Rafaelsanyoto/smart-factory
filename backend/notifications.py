"""Notification formatting + dispatch. Notifications are deterministic (fixed bold+bullet
templates, no LLM) so wording never varies from one violation to the next, and every one
carries the incident's #seq for cross-referencing. Detection notifications are debounced
into batches (a burst of near-simultaneous violations becomes one Discord message);
action/delete outcomes are dispatched immediately in a background thread."""
import json
import threading
import urllib.request

from .config import DISCORD_WEBHOOK_URL, DISCORD_WEBHOOK_URL_ACTIONS
from .database import engine_lock, db_insert_notification, db_update_notification


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


def configured_channel(purpose="detection"):
    """Which external notify channel is active for a given purpose, or None.

    purpose: "detection" (new events) or "action" (remediation updates — routed to the
    second Discord channel if configured, otherwise falls back to the main one).
    """
    if purpose == "action" and DISCORD_WEBHOOK_URL_ACTIONS:
        return "discord"
    if DISCORD_WEBHOOK_URL:
        return "discord"
    return None


def dispatch_message(text, purpose="detection"):
    """Send to whichever external channel is configured for this purpose. Returns
    (sent, channel)."""
    if purpose == "action" and DISCORD_WEBHOOK_URL_ACTIONS:
        return send_discord(text, DISCORD_WEBHOOK_URL_ACTIONS), "discord"
    if DISCORD_WEBHOOK_URL:
        return send_discord(text, DISCORD_WEBHOOK_URL), "discord"
    return False, None


# Batching: events that fire within this window of the FIRST one in a batch are combined
# into a single external message instead of one each — a burst of 3 near-simultaneous
# violations sends 1 Discord message, not 3.
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
    note_ids = [n["id"] for _, n in batch]

    if len(batch_events) == 1:
        text, _ = format_notification(batch_events[0])
    else:
        text, _ = format_batch_notification(batch_events)

    sent, channel = dispatch_message(text)

    with engine_lock:
        for note_id in note_ids:
            db_update_notification(note_id, message=text, dispatched=sent, channel=channel)

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
        "event_id": event["id"],
        "timestamp": event["timestamp"],
        "message": msg,
        "severity": severity,
        "stream_id": event["stream_id"],
        "dispatched": False,
        "channel": None,
    }
    print(f"[AI AGENT] {msg}")
    with engine_lock:
        db_insert_notification(note)

    global _batch_timer
    with _batch_lock:
        _batch_pending.append((event, note))
        if _batch_timer is None:
            _batch_timer = threading.Timer(BATCH_WINDOW_SECONDS, _flush_batch)
            _batch_timer.daemon = True
            _batch_timer.start()


def _log_and_dispatch_outcome(note_id, event_id, timestamp, text, severity, stream_id, log_label):
    """Shared by notify_action_taken / notify_deleted: log immediately, dispatch to the
    'action' channel in the background. Not part of the detection batching window — these
    are deliberate one-off admin actions, not a burst of automatic detections."""
    note = {
        "id": note_id,
        "event_id": event_id,
        "timestamp": timestamp,
        "message": text,
        "severity": severity,
        "stream_id": stream_id,
        "dispatched": False,
        "channel": None,
    }
    print(f"[AI AGENT] {text}")
    with engine_lock:
        db_insert_notification(note)

    def _send():
        sent, channel = dispatch_message(text, purpose="action")
        with engine_lock:
            db_update_notification(note_id, dispatched=sent, channel=channel)
        if sent:
            print(f"[AI AGENT] {channel} dispatched ({log_label}): {text}")

    threading.Thread(target=_send, daemon=True).start()


def notify_action_taken(event):
    """Notification when an admin records remediation on a CONFIRMED incident."""
    _log_and_dispatch_outcome(
        f"{event['id']}-action", event["id"], event["action_at"], format_action_notification(event),
        "resolved", event["stream_id"], "action taken",
    )


def notify_deleted(event):
    """Notification when an admin deletes an incident (e.g. a duplicate) — still logged
    as the incident's final outcome, not a silent removal."""
    _log_and_dispatch_outcome(
        f"{event['id']}-deleted", event["id"], event["deleted_at"], format_delete_notification(event),
        "deleted", event["stream_id"], "incident deleted",
    )
