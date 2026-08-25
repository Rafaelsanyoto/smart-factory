import time
import uuid

from .config import EMERGENCY_CLASSES
from . import state
from .database import engine_lock, db_insert_event, db_next_seq

# episodes: "{stream_id}|{class}" -> list of concurrent {first_seen_ms, last_seen_ms,
# notified, last_box}. IoU-matched instead of track_id (tracker reassigns IDs too often).
episodes = {}
CONFIRM_MS = 5_000       # episode must persist this long before it's considered real
EPISODE_GAP_MS = 30_000  # episode dropped if unmatched for this long
MATCH_IOU_THRESHOLD = 0.2


def _iou(box_a, box_b):
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


def process_rules(stream_id, boxes):
    """Returns [(event, box), ...] for events newly created this call — caller crops the
    frame for evidence/vision and notifies; this function doesn't notify directly."""
    now_ms = time.time() * 1000
    zone = state.ZONE_RULES.get(stream_id, {}).get("label", stream_id)
    monitored = state.monitored_classes_for(stream_id)
    new_events = []

    with engine_lock:
        for box in boxes:
            cls = box["class_name"]
            if cls not in monitored:
                continue
            urgency = monitored[cls]
            event_type = "EMERGENCY" if cls in EMERGENCY_CLASSES else "VIOLATION"

            key = f"{stream_id}|{cls}"
            box_xyxy = box.get("xyxy")
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
                stat = match
            else:
                stat = {
                    "first_seen_ms": now_ms,
                    "last_seen_ms": now_ms,
                    "notified": False,
                    "last_box": box_xyxy or [0, 0, 0, 0],
                }
                active.append(stat)

            episodes[key] = active

            if not stat["notified"] and (now_ms - stat["first_seen_ms"]) >= CONFIRM_MS:
                stat["notified"] = True
                event = {
                    "id": str(uuid.uuid4()),
                    "seq": db_next_seq(),
                    "timestamp": time.strftime("%H:%M:%S"),
                    "ts_ms": now_ms,
                    "stream_id": stream_id,
                    "zone": zone,
                    "type": event_type,
                    "urgency": urgency,
                    "class": cls,
                    "track_id": box.get("track_id"),
                    "confidence": box.get("confidence"),
                    "status": "PENDING",
                    "verified_at": None,
                    "verified_by": None,
                    "agent_verdict": None,
                    "agent_reasoning": None,
                    "action_taken": False,
                    "action_note": None,
                    "action_at": None,
                    "deleted": False,
                    "delete_reason": None,
                    "deleted_at": None,
                }
                db_insert_event(event)
                new_events.append((event, box))

            box["episode_status"] = "notified" if stat["notified"] else "pending"

    return new_events
