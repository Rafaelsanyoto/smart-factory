"""Action helpers — the single source of truth for every state change, shared by the REST
routes AND the AI Agent's confirmed actions, so both paths behave identically and validate
the same way. Each apply_* updates the in-memory mirror in state.py AND persists to the DB
(where relevant) so the change survives a restart.

Also holds the read-payload builders (zones_payload / sources_payload) that both the REST
endpoints and the agent's read tools return, so their shape stays identical."""
import json

from .config import (
    MODEL_REGISTRY, PPE_TO_VIOLATION, EMERGENCY_CLASSES, CONTEXT_CLASSES, context_lock,
    ALL_PPE, ALL_EMERGENCY, PERMISSION_MODES, stream_source_tokens, list_video_files, resolve_source,
)
from .database import engine_lock, db_save_config, db_save_zone_rules
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


def apply_zone_rules(stream_id, required=None, emergency=None):
    if stream_id not in state.ZONE_RULES:
        return {"status": "error", "message": "unknown zone"}
    if required is not None:
        state.ZONE_RULES[stream_id]["required"] = [p for p in required if p in PPE_TO_VIOLATION]
    if emergency is not None:
        state.ZONE_RULES[stream_id]["emergency"] = [c for c in emergency if c in EMERGENCY_CLASSES]
    with engine_lock:
        db_save_zone_rules(
            stream_id, state.ZONE_RULES[stream_id]["label"],
            state.ZONE_RULES[stream_id]["required"], state.ZONE_RULES[stream_id].get("emergency", []),
        )
    return {
        "status": "success",
        "stream_id": stream_id,
        "required": state.ZONE_RULES[stream_id]["required"],
        "emergency": state.ZONE_RULES[stream_id].get("emergency", []),
    }


def apply_context_visibility(class_name, visible):
    if class_name not in CONTEXT_CLASSES:
        return {"status": "error", "message": "unknown class"}
    with context_lock, engine_lock:
        state.context_visibility[class_name] = bool(visible)
        db_save_config("context_visibility", json.dumps(state.context_visibility))
    return {"status": "success", "class": class_name, "visible": bool(visible)}


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


# --- read-payload builders (shared by REST routes + agent read tools) ---------------
def zones_payload():
    return {
        "all_ppe": ALL_PPE,
        "all_emergency": ALL_EMERGENCY,
        "zones": [
            {
                "stream_id": sid,
                "label": rule["label"],
                "required": rule["required"],
                "emergency": rule.get("emergency", []),
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
