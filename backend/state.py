# Runtime-mutable state, mirrored from DB for fast reads. Scalars are reassigned by
# actions.apply_*() — always access as state.X, never `from state import X`.
from . import database as db

CLASS_RULES = db.db_load_class_rules()
active_confidence = float(db.db_load_config("active_confidence", "0.25"))

# crop JPEG per event id: notification/evidence attachment
event_crops = {}
MAX_EVENT_CROPS = 200


def store_event_crop(event_id, jpeg_bytes):
    if len(event_crops) >= MAX_EVENT_CROPS:
        for k in list(event_crops)[: len(event_crops) - MAX_EVENT_CROPS + 1]:
            event_crops.pop(k, None)
    event_crops[event_id] = jpeg_bytes


def monitored_classes():
    return {cls: cfg.get("urgency", "info") for cls, cfg in CLASS_RULES.items() if cfg.get("monitor")}


def is_class_visible(class_name):
    cfg = CLASS_RULES.get(class_name)
    return cfg.get("display", True) if cfg else True
