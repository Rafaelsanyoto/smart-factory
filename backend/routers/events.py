"""Incident lifecycle endpoints: list events, verify (confirm/dismiss), record remediation
action, delete-as-duplicate, and the notification log. One violation, one final outcome."""
import time

from fastapi import APIRouter
from pydantic import BaseModel

from ..database import engine_lock, db_get_events, db_get_event, db_update_event, db_get_notifications
from ..notifications import notify_action_taken, notify_deleted

router = APIRouter()


@router.get("/api/events")
def get_events():
    with engine_lock:
        return {"status": "success", "events": db_get_events()}


class EventVerify(BaseModel):
    status: str  # "CONFIRMED" | "DISMISSED"


@router.post("/api/events/{event_id}/verify")
def verify_event(event_id: str, req: EventVerify):
    """Admin marks a PENDING incident as a real violation (CONFIRMED) or a false
    detection (DISMISSED). This is the step that makes the incident queryable by the AI
    Agent and eligible to have a remediation action recorded against it."""
    status = req.status.upper()
    if status not in ("CONFIRMED", "DISMISSED"):
        return {"status": "error", "message": "status harus CONFIRMED atau DISMISSED"}
    with engine_lock:
        event = db_get_event(event_id)
        if not event:
            return {"status": "error", "message": "event tidak ditemukan"}
        result = db_update_event(event_id, status=status, verified_at=time.strftime("%H:%M:%S"))
    return {"status": "success", "event": result}


class EventAction(BaseModel):
    action_note: str


@router.post("/api/events/{event_id}/action")
def record_action(event_id: str, req: EventAction):
    """Admin records what remediation was taken on a CONFIRMED incident. Completes the
    tracking cycle: PENDING -> CONFIRMED -> action taken/note — all queryable by the
    AI Agent, and dispatches a notification to the 'action' channel."""
    note_text = req.action_note.strip()
    if not note_text:
        return {"status": "error", "message": "catatan tindakan tidak boleh kosong"}
    with engine_lock:
        event = db_get_event(event_id)
        if not event:
            return {"status": "error", "message": "event tidak ditemukan"}
        if event["status"] != "CONFIRMED":
            return {"status": "error", "message": "hanya insiden berstatus CONFIRMED yang bisa dicatat tindakannya"}
        result = db_update_event(
            event_id, action_taken=True, action_note=note_text, action_at=time.strftime("%H:%M:%S"),
        )

    notify_action_taken(result)
    return {"status": "success", "event": result}


class EventDelete(BaseModel):
    reason: str = "Duplikat"


@router.post("/api/events/{event_id}/delete")
def delete_event(event_id: str, req: EventDelete):
    """Admin deletes an incident — typically a duplicate (e.g. the same physical event
    got split into two episodes). Not a silent removal: it's still logged as that
    incident's final outcome (status DELETED + reason), so every violation ends up with
    exactly one documented resolution — either a real action taken, or a deletion here.
    Works from any status except an already-deleted incident."""
    reason = (req.reason or "Duplikat").strip() or "Duplikat"
    with engine_lock:
        event = db_get_event(event_id)
        if not event:
            return {"status": "error", "message": "event tidak ditemukan"}
        if event["status"] == "DELETED":
            return {"status": "error", "message": "insiden ini sudah dihapus sebelumnya"}
        result = db_update_event(
            event_id, status="DELETED", deleted=True, delete_reason=reason,
            deleted_at=time.strftime("%H:%M:%S"),
        )

    notify_deleted(result)
    return {"status": "success", "event": result}


@router.get("/api/notifications")
def get_notifications():
    with engine_lock:
        return {"status": "success", "notifications": db_get_notifications()}
