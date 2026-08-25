import json
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
        f"• **Jenis:** {event['class']}",
        f"• **Waktu:** {event['timestamp']}",
        f"• **Confidence:** {_pct(event.get('confidence'))}",
        f"• **Status:** {action}",
    ]
    return "\n".join(lines), urgency


def format_action_notification(event):
    lines = [
        "✅ **TINDAKAN DICATAT**",
        f"• **Insiden:** #{event.get('seq', '?')}",
        f"• **Jenis Pelanggaran:** {event['class']}",
        f"• **Waktu Kejadian:** {event['timestamp']}",
        f"• **Tindakan:** {event['action_note']}",
        f"• **Dicatat Pukul:** {event['action_at']}",
    ]
    return "\n".join(lines)


def format_delete_notification(event):
    lines = [
        "🗑️ **INSIDEN DIHAPUS**",
        f"• **Insiden:** #{event.get('seq', '?')}",
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


def notify_safety(event):
    msg, severity = format_notification(event)

    note = {
        "id": event["id"],
        "event_id": event["id"],
        "timestamp": event["timestamp"],
        "message": msg,
        "severity": severity,
        "dispatched": False,
        "channel": None,
    }
    print(f"[AI AGENT] {msg}")
    with engine_lock:
        db_insert_notification(note)

    if event.get("urgency", "warning") == "info":
        return

    images = [state.event_crops[event["id"]]] if event["id"] in state.event_crops else None
    sent, channel = dispatch_message(msg, images=images)
    with engine_lock:
        db_update_notification(note["id"], message=msg, dispatched=sent, channel=channel)
    if sent:
        print(f"[AI AGENT] {channel} dispatched")


def _log_and_dispatch_outcome(note_id, event_id, timestamp, text, severity, log_label):
    note = {
        "id": note_id,
        "event_id": event_id,
        "timestamp": timestamp,
        "message": text,
        "severity": severity,
        "dispatched": False,
        "channel": None,
    }
    print(f"[AI AGENT] {text}")
    with engine_lock:
        db_insert_notification(note)

    sent, channel = dispatch_message(text, purpose="action")
    with engine_lock:
        db_update_notification(note_id, dispatched=sent, channel=channel)
    if sent:
        print(f"[AI AGENT] {channel} dispatched ({log_label}): {text}")


def notify_action_taken(event):
    _log_and_dispatch_outcome(
        f"{event['id']}-action", event["id"], event["action_at"], format_action_notification(event),
        "resolved", "action taken",
    )


def notify_deleted(event):
    _log_and_dispatch_outcome(
        f"{event['id']}-deleted", event["id"], event["deleted_at"], format_delete_notification(event),
        "deleted", "incident deleted",
    )
