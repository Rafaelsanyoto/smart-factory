import re

from .config import (
    MODEL_REGISTRY, ALL_CLASSES, URGENCY_LEVELS, PERMISSION_MODES,
    stream_source_tokens, list_video_files, resolve_source,
)
from .database import engine_lock, db_save_config, db_save_zone_classes, db_save_zone_responsible
from . import state
from .camera import cameras


def apply_model(model_id):
    if model_id not in MODEL_REGISTRY:
        return {"status": "error", "message": "unknown model"}
    path = MODEL_REGISTRY[model_id]["path"]
    for cam in cameras.values():
        cam.switch_model(path)
    state.active_model_id = model_id
    with engine_lock:
        db_save_config("active_model_id", state.active_model_id)
    return {"status": "success", "active": state.active_model_id}


def apply_confidence(value):
    state.active_confidence = max(0.1, min(0.95, float(value)))
    with engine_lock:
        db_save_config("active_confidence", state.active_confidence)
    return {"status": "success", "confidence": state.active_confidence}


def apply_zone_classes(stream_id, classes):
    if stream_id not in state.ZONE_RULES:
        return {"status": "error", "message": "unknown zone"}
    current = state.ZONE_RULES[stream_id].get("classes", {})
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
    state.ZONE_RULES[stream_id]["classes"] = current
    with engine_lock:
        db_save_zone_classes(stream_id, state.ZONE_RULES[stream_id]["label"], current)
    return {"status": "success", "stream_id": stream_id, "classes": current}


def apply_zone_responsible(stream_id, name, mention):
    if stream_id not in state.ZONE_RULES:
        return {"status": "error", "message": "unknown zone"}
    name = (name or "").strip() or None
    mention = re.sub(r"\D", "", mention or "") or None  # keep digits only, e.g. pasted <@id>
    state.ZONE_RULES[stream_id]["responsible_name"] = name
    state.ZONE_RULES[stream_id]["responsible_mention"] = mention
    with engine_lock:
        db_save_zone_responsible(stream_id, name, mention)
    return {"status": "success", "stream_id": stream_id, "responsible_name": name, "responsible_mention": mention}


def apply_autonomous_mode(enabled):
    state.autonomous_mode = bool(enabled)
    with engine_lock:
        db_save_config("autonomous_mode", "on" if state.autonomous_mode else "off")
    return {"status": "success", "autonomous_mode": state.autonomous_mode}


def apply_pause(stream_id, paused):
    cam = cameras.get(stream_id)
    if not cam:
        return {"status": "error", "message": "unknown stream"}
    cam.set_paused(bool(paused))
    return {"status": "success", "stream_id": stream_id, "paused": cam.paused}


def apply_source(stream_id, token):
    cam = cameras.get(stream_id)
    if not cam:
        return {"status": "error", "message": "unknown stream"}
    resolved, err = resolve_source(token)
    if err:
        return {"status": "error", "message": err}
    cam.switch_source(resolved)
    stream_source_tokens[stream_id] = "Webcam" if resolved == 0 else token
    return {"status": "success", "stream_id": stream_id, "source": stream_source_tokens[stream_id]}


def apply_permission_mode(mode):
    if mode not in PERMISSION_MODES:
        return {"status": "error", "message": "mode tidak dikenal"}
    state.agent_permission_mode = mode
    with engine_lock:
        db_save_config("agent_permission_mode", mode)
    return {"status": "success", "mode": mode}


def zones_payload():
    return {
        "all_classes": ALL_CLASSES,
        "urgency_levels": list(URGENCY_LEVELS),
        "zones": [
            {
                "stream_id": sid,
                "label": rule["label"],
                "classes": rule.get("classes", {}),
                "responsible_name": rule.get("responsible_name"),
                "responsible_mention": rule.get("responsible_mention"),
            }
            for sid, rule in state.ZONE_RULES.items()
        ],
    }


def sources_payload():
    return {
        "options": ["Webcam"] + list_video_files(),
        "current": dict(stream_source_tokens),
        "paused": {sid: bool(cam.paused) for sid, cam in cameras.items()},
    }
