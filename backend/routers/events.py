import time

from fastapi import APIRouter
from pydantic import BaseModel

from ..database import engine_lock, db_get_events, db_get_event, db_update_event, db_get_notifications
from ..notifications import notify_deleted
from .. import followup

router = APIRouter()


@router.get("/api/events")
def get_events():
    with engine_lock:
        return {"status": "success", "events": db_get_events()}


class EventVerify(BaseModel):
    status: str


@router.post("/api/events/{event_id}/verify")
def verify_event(event_id: str, req: EventVerify):
    status = req.status.upper()
    if status not in ("CONFIRMED", "DISMISSED"):
        return {"status": "error", "message": "status harus CONFIRMED atau DISMISSED"}
    with engine_lock:
        event = db_get_event(event_id)
        if not event:
            return {"status": "error", "message": "event tidak ditemukan"}
    if status == "DISMISSED":
        result = followup.dismiss_event(event_id)
    else:
        with engine_lock:
            result = db_update_event(event_id, status="CONFIRMED", verified_at=time.strftime("%H:%M:%S"))
    return {"status": "success", "event": result}


class EventAction(BaseModel):
    action_note: str


@router.post("/api/events/{event_id}/action")
def record_action(event_id: str, req: EventAction):
    note_text = req.action_note.strip()
    if not note_text:
        return {"status": "error", "message": "catatan tindakan tidak boleh kosong"}
    with engine_lock:
        event = db_get_event(event_id)
        if not event:
            return {"status": "error", "message": "event tidak ditemukan"}
        if event["status"] != "CONFIRMED":
            return {"status": "error", "message": "hanya insiden berstatus CONFIRMED yang bisa dicatat tindakannya"}
    result = followup.mark_acted(event_id, note_text)
    return {"status": "success", "event": result}


class EventDelete(BaseModel):
    reason: str = "Duplikat"


@router.post("/api/events/{event_id}/delete")
def delete_event(event_id: str, req: EventDelete):
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


@router.post("/api/events/{event_id}/acknowledge")
def acknowledge_event(event_id: str):
    with engine_lock:
        event = db_get_event(event_id)
        if not event:
            return {"status": "error", "message": "event tidak ditemukan"}
        result = db_update_event(event_id, alarm_ack_at=time.strftime("%H:%M:%S"))
    return {"status": "success", "event": result}
