import os

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import MODEL_ID, MODEL_LABEL, DB_PATH
from ..database import db_conn, engine_lock
from .. import state
from ..actions import apply_confidence, apply_class_rules, class_rules_payload

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
def get_model():
    return {"active": MODEL_ID, "label": MODEL_LABEL, "confidence": state.active_confidence}


class ConfidenceSet(BaseModel):
    confidence: float


@router.post("/api/config/confidence")
def set_confidence(req: ConfidenceSet):
    return apply_confidence(req.confidence)


@router.get("/api/class-rules")
def get_class_rules():
    return class_rules_payload()


class ClassRulesUpdate(BaseModel):
    classes: dict


@router.post("/api/class-rules")
def update_class_rules(req: ClassRulesUpdate):
    return apply_class_rules(req.classes)
