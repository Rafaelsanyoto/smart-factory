import json
import threading
import urllib.request
import uuid

from .config import DISCORD_WEBHOOK_URL, DISCORD_WEBHOOK_URL_ACTIONS
from .database import engine_lock, db_insert_notification, db_update_notification
from . import state

URGENCY_ICON = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}


def _pct(confidence):
    return f"{round(confidence * 100)}%" if isinstance(confidence, (int, float)) else "—"


def format_notification(event):
    urgency = event.get("urgency", "warning")
    is_emergency = event["type"] == "EMERGENCY"
    icon = URGENCY_ICON.get(urgency, "⚠️")
    header = "DARURAT TERDETEKSI" if is_emergency else "PELANGGARAN TERDETEKSI"
    action = "Segera evakuasi & hubungi tim darurat" if is_emergency else "Menunggu tindakan tim safety"

    lines = [
        f"{icon} **{header}**",
        f"• **Insiden:** #{event.get('seq', '?')}",
        f"• **Urgensi:** {urgency.upper()}",
        f"• **Zona:** {event['zone']}",
        f"• **Jenis:** {event['class']}",
        f"• **Waktu:** {event['timestamp']}",
        f"• **Confidence:** {_pct(event.get('confidence'))}",
        f"• **Status:** {action}",
    ]
    return "\n".join(lines), urgency


def format_batch_notification(batch_events):
    has_emergency = any(e["type"] == "EMERGENCY" for e in batch_events)
    urgencies = [e.get("urgency", "warning") for e in batch_events]
    top_urgency = "critical" if "critical" in urgencies else ("warning" if "warning" in urgencies else "info")
    icon = URGENCY_ICON.get(top_urgency, "⚠️")
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
    return "\n".join(lines), top_urgency


def format_action_notification(event):
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


def format_ai_confirmed_notification(event, mention=None):
    lines = []
    if mention:
        lines.append(mention)
    lines += [
        "🤖 **DIKONFIRMASI AI — PERLU TINDAKAN**",
        f"• **Insiden:** #{event.get('seq', '?')}",
        f"• **Zona:** {event['zone']}",
        f"• **Jenis:** {event['class']}",
        f"• **Waktu:** {event['timestamp']}",
        f"• **Alasan AI:** {event.get('agent_reasoning') or '-'}",
        "• **Status:** Menunggu tindakan — catat penyelesaiannya di dashboard.",
    ]
    return "\n".join(lines)


def format_delete_notification(event):
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


def _multipart_body(text, images):
    boundary = "----SmartFactoryHSE" + uuid.uuid4().hex
    payload = json.dumps({"content": str(text)[:1900]})
    out = []
    out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
               f'Content-Type: application/json\r\n\r\n{payload}\r\n'.encode())
    for i, img in enumerate(images[:10]):
        out.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="files[{i}]"; '
            f'filename="evidence_{i}.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
        )
        out.append(img)
        out.append(b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), boundary


def send_discord(text, webhook_url, images=None):
    if not webhook_url:
        return False
    # custom User-Agent required, Discord rejects the default urllib one
    headers = {"User-Agent": "SmartFactoryHSE/1.0"}
    if images:
        body, boundary = _multipart_body(text, images)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    else:
        body = json.dumps({"content": str(text)[:1900]}).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(webhook_url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"[AI AGENT] Discord send failed: {e}")
        return False


def configured_channel(purpose="detection"):
    if purpose == "action" and DISCORD_WEBHOOK_URL_ACTIONS:
        return "discord"
    if DISCORD_WEBHOOK_URL:
        return "discord"
    return None


def dispatch_message(text, purpose="detection", images=None):
    if purpose == "action" and DISCORD_WEBHOOK_URL_ACTIONS:
        return send_discord(text, DISCORD_WEBHOOK_URL_ACTIONS, images), "discord"
    if DISCORD_WEBHOOK_URL:
        return send_discord(text, DISCORD_WEBHOOK_URL, images), "discord"
    return False, None


BATCH_WINDOW_SECONDS = 2.0
_batch_lock = threading.Lock()
_batch_pending = []
_batch_timer = None


def _flush_batch():
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

    images = [state.event_crops[e["id"]] for e in batch_events if e["id"] in state.event_crops]
    sent, channel = dispatch_message(text, images=images or None)

    with engine_lock:
        for note_id in note_ids:
            db_update_notification(note_id, message=text, dispatched=sent, channel=channel)

    if sent:
        print(f"[AI AGENT] {channel} dispatched (batch of {len(batch_events)}, {len(images)} img)")


def notify_safety(event):
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

    if event.get("urgency", "warning") == "info":
        return  # info: logged only, not pushed externally

    global _batch_timer
    with _batch_lock:
        _batch_pending.append((event, note))
        if _batch_timer is None:
            _batch_timer = threading.Timer(BATCH_WINDOW_SECONDS, _flush_batch)
            _batch_timer.daemon = True
            _batch_timer.start()


def _log_and_dispatch_outcome(note_id, event_id, timestamp, text, severity, stream_id, log_label):
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
    _log_and_dispatch_outcome(
        f"{event['id']}-action", event["id"], event["action_at"], format_action_notification(event),
        "resolved", event["stream_id"], "action taken",
    )


def notify_deleted(event):
    _log_and_dispatch_outcome(
        f"{event['id']}-deleted", event["id"], event["deleted_at"], format_delete_notification(event),
        "deleted", event["stream_id"], "incident deleted",
    )


def notify_ai_confirmed(event, mention=None):
    _log_and_dispatch_outcome(
        f"{event['id']}-ai-confirmed", event["id"], event["verified_at"],
        format_ai_confirmed_notification(event, mention),
        event.get("urgency", "warning"), event["stream_id"], "AI confirmed",
    )
