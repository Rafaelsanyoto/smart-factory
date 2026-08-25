"""Runtime-mutable state — the values that change while the app runs, loaded from the DB
at startup and mirrored here for fast reads on the hot path (every detected frame reads
ZONE_RULES / active_confidence).

IMPORTANT: the scalars below (active_model_id, active_confidence, agent_permission_mode,
autonomous_mode) get REASSIGNED at runtime by actions.apply_*(). Always read them as
`state.active_...` (module-attribute access), never `from state import active_confidence`
— the latter copies the value at import time and would never see later updates. The dicts
(ZONE_RULES, latest_detections, event_crops) are mutated in place, so for consistency
everything here is accessed as `state.X`."""
from .config import DEFAULT_MODEL, PERMISSION_MODES
from . import database as db

# Fast in-memory mirrors of DB-persisted config. Writes go through actions.apply_*(),
# which update both this mirror AND the DB (so the next restart picks up the latest).
# ZONE_RULES: {stream_id: {"label": str, "classes": {class: {display, monitor, urgency}}}}
ZONE_RULES = db.db_load_zone_rules()
active_model_id = db.db_load_config("active_model_id", DEFAULT_MODEL)
active_confidence = float(db.db_load_config("active_confidence", "0.25"))

agent_permission_mode = db.db_load_config("agent_permission_mode", "standard")
if agent_permission_mode not in PERMISSION_MODES:
    agent_permission_mode = "standard"

# Autonomous Incident Handling — when on, the AI Agent vision-verifies + confirms/escalates
# new detections without a human. Separate axis from agent_permission_mode (which governs
# user-initiated chat actions). Stored as "on"/"off" in the DB, mirrored as a bool here.
autonomous_mode = db.db_load_config("autonomous_mode", "off") == "on"

# Most recent per-stream detection breakdown, written by each camera's ai_loop and read by
# the /api/data/{stream_id} endpoint. Mutated in place (keyed by stream_id).
latest_detections = {"stream_01": [], "stream_02": []}

# Cropped JPEG of the detection that raised each event, keyed by event id. Captured in
# camera.ai_loop at event-creation time and consumed by (a) the notification dispatch as
# photo evidence and (b) the autonomous worker as the image to vision-verify. Bounded so
# it can't grow without limit.
event_crops = {}
MAX_EVENT_CROPS = 200


def store_event_crop(event_id, jpeg_bytes):
    if len(event_crops) >= MAX_EVENT_CROPS:
        # drop oldest (dicts preserve insertion order)
        for k in list(event_crops)[: len(event_crops) - MAX_EVENT_CROPS + 1]:
            event_crops.pop(k, None)
    event_crops[event_id] = jpeg_bytes


def monitored_classes_for(stream_id):
    """{class_name: urgency} for every class marked monitor=true in this zone — i.e. the
    classes whose detection should raise an incident."""
    classes = ZONE_RULES.get(stream_id, {}).get("classes", {})
    return {cls: cfg.get("urgency", "info") for cls, cfg in classes.items() if cfg.get("monitor")}


def is_class_visible(stream_id, class_name):
    """Whether this class's bounding box should be drawn / listed for this zone."""
    cfg = ZONE_RULES.get(stream_id, {}).get("classes", {}).get(class_name)
    return cfg.get("display", True) if cfg else True
