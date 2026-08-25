import os

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import MODEL_REGISTRY, DB_PATH
from ..database import db_conn, engine_lock, db_feedback_summary
from .. import state
from ..actions import (
    apply_model, apply_confidence, apply_zone_classes, apply_zone_responsible,
    apply_autonomous_mode, zones_payload,
)

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


class ZoneClassesUpdate(BaseModel):
    # {class_name: {display?: bool, monitor?: bool, urgency?: "info"|"warning"|"critical"}}
    classes: dict


@router.post("/api/zones/{stream_id}")
def update_zone(stream_id: str, req: ZoneClassesUpdate):
    return apply_zone_classes(stream_id, req.classes)


class ZoneResponsibleSet(BaseModel):
    name: str = ""
    mention: str = ""


@router.post("/api/zones/{stream_id}/responsible")
def update_zone_responsible(stream_id: str, req: ZoneResponsibleSet):
    return apply_zone_responsible(stream_id, req.name, req.mention)


@router.get("/api/system/autonomous")
def get_autonomous():
    return {"autonomous_mode": state.autonomous_mode}


class AutonomousSet(BaseModel):
    enabled: bool


@router.post("/api/system/autonomous")
def set_autonomous(req: AutonomousSet):
    return apply_autonomous_mode(req.enabled)


@router.get("/api/system/agent-feedback")
def agent_feedback():
    with engine_lock:
        return db_feedback_summary()
