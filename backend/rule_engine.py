"""Server-side rule engine: turns raw per-frame detections into structured, deduplicated
incidents. Uses an episode model keyed by zone+class with spatial (IoU) matching across
concurrent episodes — deliberately NOT track_id, since the YOLO tracker reassigns IDs too
often to be a reliable person identity. Two people committing the same violation in
different spots (at once, or one after the other) are recognized as separate occurrences
instead of collapsing into one."""
import time
import uuid

from .config import EMERGENCY_CLASSES
from . import state
from .database import engine_lock, db_insert_event, db_next_seq

# Episode tracking, keyed by "{stream_id}|{cls}" (zone + violation/emergency class) ->
# a LIST of concurrent episodes, one per distinct physical location.
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


def process_rules(stream_id, boxes):
    """Turns raw detections into structured events (episode model with IoU matching, see
    module docstring). Called from each camera's ai_loop (multiple threads) -> guarded by
    engine_lock.

    Returns a list of (event, box) for events newly created this call, so the caller (which
    holds the video frame) can crop the detection for evidence/vision and then notify. This
    function no longer notifies directly — the crop has to be captured first."""
    now_ms = time.time() * 1000
    zone = state.ZONE_RULES.get(stream_id, {}).get("label", stream_id)
    monitored = state.monitored_classes_for(stream_id)  # {class_name: urgency}
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
                stat = match
            else:
                # No existing episode overlaps this box's position -> a distinct
                # occurrence (different person / different spot), even if another
                # episode of the same class is still active elsewhere in this zone.
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
                    "seq": db_next_seq(),  # human-referenceable incident number (#1, #2, ...)
                    "timestamp": time.strftime("%H:%M:%S"),
                    "ts_ms": now_ms,  # epoch ms, for the agent's "last N minutes" filtering
                    "stream_id": stream_id,
                    "zone": zone,
                    "type": event_type,
                    "urgency": urgency,        # info | warning | critical (per-zone per-class)
                    "class": cls,
                    "track_id": box.get("track_id"),
                    "confidence": box.get("confidence"),
                    "status": "PENDING",       # PENDING -> CONFIRMED | DISMISSED -> (or DELETED)
                    "verified_at": None,
                    "verified_by": None,       # "agent" when confirmed by autonomous handling
                    "agent_verdict": None,     # real | false | uncertain (autonomous opinion)
                    "agent_reasoning": None,
                    "action_taken": False,     # remediation recorded on a CONFIRMED event
                    "action_note": None,
                    "action_at": None,
                    "deleted": False,          # one violation, one final outcome: either a real
                    "delete_reason": None,     # action above, OR deleted here as a duplicate —
                    "deleted_at": None,        # these two are mutually exclusive.
                }
                db_insert_event(event)
                new_events.append((event, box))

            # Surface the rule engine's decision back on the box itself, so the UI can
            # show which detections are suppressed (already notified this episode) vs
            # still pending confirmation.
            box["episode_status"] = "notified" if stat["notified"] else "pending"

    return new_events
