"""Follow-up on CONFIRMED incidents that still need a human to physically act.

The autonomous agent only judges authenticity — it never marks an incident "handled". A
real, confirmed incident sits in the awaiting-action set until a human records the actual
remediation (web form, or a Discord ✅ reaction). Until then this module reminds them, with
a cadence that escalates by urgency. A ❌ reaction / web dismissal on an agent-confirmed
incident is captured as feedback: the AI's confirmation was wrong.

This module is dependency-light on purpose (database / state / notifications only, never
discord_bot or agent) so it can't create an import cycle. Discord delivery is injected via
set_sender(); without a bot it falls back to the webhook (no reactions, but the web OVERDUE
badge still covers acknowledgement)."""
import os
import threading
import time

from .config import PROJECT_ROOT
from . import state
from .database import (
    engine_lock, db_get_event, db_update_event, db_get_awaiting_action, db_insert_feedback,
)
from .notifications import notify_action_taken, dispatch_message

EVIDENCE_DIR = os.path.join(PROJECT_ROOT, "feedback_evidence")

# Reminder cadence (seconds) per urgency. 'info' absent -> never reminded.
REMINDER_CADENCE = {"critical": 120, "warning": 600}
REMINDER_TICK = 20

_reminded = {}            # event_id -> last-reminded epoch seconds
_sender = None            # injected Discord sender: fn(event, text) -> bool (True if sent via bot)
incident_messages = {}    # discord message_id -> event_id (for reaction handling)


def set_sender(fn):
    global _sender
    _sender = fn


def register_incident_message(message_id, event_id):
    incident_messages[message_id] = event_id


def event_for_message(message_id):
    return incident_messages.get(message_id)


def _forget(event_id):
    for mid in [m for m, e in list(incident_messages.items()) if e == event_id]:
        incident_messages.pop(mid, None)
    _reminded.pop(event_id, None)


def _save_feedback_image(event):
    """Persist the evidence crop (if still in memory) so a wrong-confirmation feedback row
    references a real labeled image."""
    data = state.event_crops.get(event["id"])
    if not data:
        return None
    try:
        os.makedirs(EVIDENCE_DIR, exist_ok=True)
        path = os.path.join(EVIDENCE_DIR, f"{event.get('seq', 'x')}_{event['id'][:8]}.jpg")
        with open(path, "wb") as f:
            f.write(data)
        return path
    except Exception as e:
        print(f"[FEEDBACK] save image failed: {e}")
        return None


def mark_acted(event_id, note):
    """Record remediation on a CONFIRMED incident — the shared core for the web form, the
    agent's record_action tool, and the Discord ✅ reaction. Returns the updated event."""
    with engine_lock:
        ev = db_get_event(event_id)
        if not ev or ev["status"] != "CONFIRMED" or ev["action_taken"]:
            return ev
        updated = db_update_event(
            event_id, action_taken=True, action_note=note, action_at=time.strftime("%H:%M:%S"),
        )
    _forget(event_id)
    notify_action_taken(updated)
    return updated


def dismiss_with_feedback(event_id, source, note):
    """Dismiss an incident. If it was one the agent had confirmed as real, log it as an AI
    mistake (with evidence) — this is the model-feedback signal. Shared by the web dismiss,
    the agent's verify_incident(DISMISSED), and the Discord ❌ reaction."""
    with engine_lock:
        ev = db_get_event(event_id)
        if not ev or ev["status"] == "DELETED":
            return ev
        was_agent_confirm = ev.get("verified_by") == "agent" and ev.get("agent_verdict") == "real"
        updated = db_update_event(event_id, status="DISMISSED", verified_at=time.strftime("%H:%M:%S"))
        if was_agent_confirm:
            img = _save_feedback_image(ev)
            db_insert_feedback(updated, human_decision="DISMISSED", source=source, image_path=img)
    _forget(event_id)
    if was_agent_confirm:
        print(f"[FEEDBACK] #{ev.get('seq')} — koreksi: AI keliru meng-CONFIRM (via {source}). Note: {note}")
    return updated


def _due(event, now):
    cadence = REMINDER_CADENCE.get(event.get("urgency"))
    if not cadence:
        return False
    last = _reminded.get(event["id"])
    return last is None or (now - last) >= cadence


def _send_reminder(event):
    text = (
        f"🔔 **BELUM DITINDAK — #{event.get('seq', '?')}** ({str(event.get('urgency', '?')).upper()})\n"
        f"• **Zona:** {event['zone']}\n"
        f"• **Jenis:** {event['class']}\n"
        f"• **Terdeteksi:** {event['timestamp']}\n"
        f"React ✅ jika sudah ditindak, ❌ jika salah deteksi."
    )
    sent = False
    if _sender:
        try:
            sent = bool(_sender(event, text))
        except Exception as e:
            print(f"[REMINDER] sender error: {e}")
    if not sent:
        dispatch_message(text, purpose="action")  # webhook fallback (no reactions)
    print(f"[REMINDER] #{event.get('seq', '?')} ({event.get('urgency')}) diingatkan via {'bot' if sent else 'webhook'}")


def _reminder_worker():
    while True:
        time.sleep(REMINDER_TICK)
        try:
            with engine_lock:
                events = db_get_awaiting_action()
            now = time.time()
            for ev in events:
                if _due(ev, now):
                    _send_reminder(ev)
                    _reminded[ev["id"]] = now
        except Exception as e:
            print(f"[REMINDER] worker error: {e}")


_worker_thread = threading.Thread(target=_reminder_worker, daemon=True)
_worker_thread.start()
