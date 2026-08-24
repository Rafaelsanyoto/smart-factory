"""Health, DB info, model/confidence, zone rules, and context-class display endpoints."""
import os

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import MODEL_REGISTRY, DB_PATH, CONTEXT_CLASSES
from ..database import db_conn, engine_lock
from .. import state
from ..actions import apply_model, apply_confidence, apply_zone_rules, apply_context_visibility, zones_payload

router = APIRouter()


@router.get("/api/health")
def health():
    return {"status": "ok"}


@router.get("/api/system/db-info")
def db_info():
    with engine_lock:
        event_count = db_conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
        notif_count = db_conn.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"]
    size_bytes = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    return {
        "path": DB_PATH,
        "size_kb": round(size_bytes / 1024, 1),
        "event_count": event_count,
        "notification_count": notif_count,
    }


@router.get("/api/models")
def get_models():
    return {
        "active": state.active_model_id,
        "confidence": state.active_confidence,
        "models": [{"id": k, "label": v["label"]} for k, v in MODEL_REGISTRY.items()],
    }


class ModelSelect(BaseModel):
    id: str


@router.post("/api/model/select")
def select_model(req: ModelSelect):
    return apply_model(req.id)


class ConfidenceSet(BaseModel):
    confidence: float


@router.post("/api/config/confidence")
def set_confidence(req: ConfidenceSet):
    return apply_confidence(req.confidence)


@router.get("/api/zones")
def get_zones():
    return zones_payload()


class ZoneUpdate(BaseModel):
    required: list[str] | None = None
    emergency: list[str] | None = None


@router.post("/api/zones/{stream_id}")
def update_zone(stream_id: str, req: ZoneUpdate):
    return apply_zone_rules(stream_id, req.required, req.emergency)


@router.get("/api/context-classes")
def get_context_classes():
    return {"classes": CONTEXT_CLASSES, "visible": dict(state.context_visibility)}


class ContextVisibilitySet(BaseModel):
    visible: bool


@router.post("/api/context-classes/{class_name}")
def set_context_visibility(class_name: str, req: ContextVisibilitySet):
    return apply_context_visibility(class_name, req.visible)
