import time
import uuid

from .config import EMERGENCY_CLASSES, RESULT_LABEL
from . import state
from .database import engine_lock, db_insert_event, db_next_seq


def process_rules(boxes):
    """One detect run -> one PENDING incident per monitored class found (best-confidence box)."""
    now_ms = time.time() * 1000
    monitored = state.monitored_classes()

    best_per_class = {}
    for box in boxes:
        cls = box["class_name"]
        if cls not in monitored:
            continue
        current = best_per_class.get(cls)
        if current is None or box["confidence"] > current["confidence"]:
            best_per_class[cls] = box

    new_events = []
    with engine_lock:
        for cls, box in best_per_class.items():
            event = {
                "id": str(uuid.uuid4()),
                "seq": db_next_seq(),
                "timestamp": time.strftime("%H:%M:%S"),
                "ts_ms": now_ms,
                "zone": RESULT_LABEL,
                "type": "EMERGENCY" if cls in EMERGENCY_CLASSES else "VIOLATION",
                "urgency": monitored[cls],
                "class": cls,
                "confidence": box.get("confidence"),
                "status": "PENDING",
                "verified_at": None,
                "action_taken": False,
                "action_note": None,
                "action_at": None,
                "deleted": False,
                "delete_reason": None,
                "deleted_at": None,
            }
            db_insert_event(event)
            new_events.append((event, box))

    return new_events
