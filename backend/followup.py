import time

from .database import engine_lock, db_get_event, db_update_event
from .notifications import notify_action_taken


def mark_acted(event_id, note):
    with engine_lock:
        ev = db_get_event(event_id)
        if not ev or ev["status"] != "CONFIRMED" or ev["action_taken"]:
            return ev
        updated = db_update_event(
            event_id, action_taken=True, action_note=note, action_at=time.strftime("%H:%M:%S"),
        )
    notify_action_taken(updated)
    return updated


def dismiss_event(event_id):
    with engine_lock:
        ev = db_get_event(event_id)
        if not ev or ev["status"] == "DELETED":
            return ev
        updated = db_update_event(event_id, status="DISMISSED", verified_at=time.strftime("%H:%M:%S"))
    return updated
