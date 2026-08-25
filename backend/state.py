# Runtime-mutable config, mirrored from DB for fast reads on the hot path. Scalars are
# reassigned by actions.apply_*() — always access as state.X, never `from state import X`.
from .config import DEFAULT_MODEL, PERMISSION_MODES
from . import database as db

ZONE_RULES = db.db_load_zone_rules()
active_model_id = db.db_load_config("active_model_id", DEFAULT_MODEL)
active_confidence = float(db.db_load_config("active_confidence", "0.25"))

agent_permission_mode = db.db_load_config("agent_permission_mode", "standard")
if agent_permission_mode not in PERMISSION_MODES:
    agent_permission_mode = "standard"

autonomous_mode = db.db_load_config("autonomous_mode", "off") == "on"

latest_detections = {"stream_01": [], "stream_02": []}

# crop JPEG per event id: notification evidence + autonomous vision input
event_crops = {}
MAX_EVENT_CROPS = 200


def store_event_crop(event_id, jpeg_bytes):
    if len(event_crops) >= MAX_EVENT_CROPS:
        for k in list(event_crops)[: len(event_crops) - MAX_EVENT_CROPS + 1]:
            event_crops.pop(k, None)
    event_crops[event_id] = jpeg_bytes


def monitored_classes_for(stream_id):
    classes = ZONE_RULES.get(stream_id, {}).get("classes", {})
    return {cls: cfg.get("urgency", "info") for cls, cfg in classes.items() if cfg.get("monitor")}


def is_class_visible(stream_id, class_name):
    cfg = ZONE_RULES.get(stream_id, {}).get("classes", {}).get(class_name)
    return cfg.get("display", True) if cfg else True


def responsible_mention_for(stream_id):
    raw_id = ZONE_RULES.get(stream_id, {}).get("responsible_mention")
    return f"<@{raw_id}>" if raw_id else None
