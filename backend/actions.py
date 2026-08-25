from .config import ALL_CLASSES, URGENCY_LEVELS
from .database import engine_lock, db_save_config, db_save_class_rules
from . import state


def apply_confidence(value):
    state.active_confidence = max(0.1, min(0.95, float(value)))
    with engine_lock:
        db_save_config("active_confidence", state.active_confidence)
    return {"status": "success", "confidence": state.active_confidence}


def apply_class_rules(classes):
    current = state.CLASS_RULES
    for cls, cfg in (classes or {}).items():
        if cls not in ALL_CLASSES or not isinstance(cfg, dict):
            continue
        entry = current.get(cls, {"display": True, "monitor": False, "urgency": "info"})
        if "display" in cfg:
            entry["display"] = bool(cfg["display"])
        if "monitor" in cfg:
            entry["monitor"] = bool(cfg["monitor"])
        if cfg.get("urgency") in URGENCY_LEVELS:
            entry["urgency"] = cfg["urgency"]
        current[cls] = entry
    state.CLASS_RULES = current
    with engine_lock:
        db_save_class_rules(current)
    return {"status": "success", "classes": current}


def class_rules_payload():
    return {
        "all_classes": ALL_CLASSES,
        "urgency_levels": list(URGENCY_LEVELS),
        "classes": state.CLASS_RULES,
    }
