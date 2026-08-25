import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import GEMINI_API_KEY, PERMISSION_MODES
from ..database import (
    engine_lock, db_create_session, db_get_session, db_get_sessions, db_delete_session,
    db_get_messages, MAX_MESSAGES_PER_SESSION,
)
from .. import state
from ..notifications import configured_channel
from ..actions import apply_permission_mode
from ..agent import (
    ACTION_TOOLS, ACTION_RISK, run_agent_chat_session, run_agent_chat_session_final,
    resolve_pending_action,
)

router = APIRouter()


@router.get("/api/agent/status")
def agent_status():
    return {
        "configured": bool(GEMINI_API_KEY),
        "channel": configured_channel(),
        "permission_mode": state.agent_permission_mode,
    }


@router.get("/api/agent/permission-mode")
def get_permission_mode():
    return {
        "mode": state.agent_permission_mode,
        "options": list(PERMISSION_MODES),
        "action_risk": ACTION_RISK,
    }


class PermissionModeSet(BaseModel):
    mode: str


@router.post("/api/agent/permission-mode")
def set_permission_mode(req: PermissionModeSet):
    return apply_permission_mode(req.mode)


@router.get("/api/agent/sessions")
def list_sessions(limit: int = 50):
    with engine_lock:
        return {"status": "success", "sessions": db_get_sessions(source="dashboard", limit=limit)}


@router.post("/api/agent/sessions")
def create_session():
    with engine_lock:
        session_id = db_create_session(source="dashboard")
        session = db_get_session(session_id)
    return {"status": "success", "session": session}


@router.get("/api/agent/sessions/{session_id}/messages")
def get_session_messages(session_id: str, limit: int = MAX_MESSAGES_PER_SESSION):
    with engine_lock:
        session = db_get_session(session_id)
        if not session:
            return {"status": "error", "message": "session tidak ditemukan"}
        messages = db_get_messages(session_id, limit=limit)
    return {"status": "success", "messages": messages}


class ResolveActionRequest(BaseModel):
    approve: bool


@router.post("/api/agent/messages/{message_id}/resolve-action")
def resolve_message_action(message_id: str, req: ResolveActionRequest):
    res = resolve_pending_action(message_id, req.approve)
    return {
        "status": "success" if res["ok"] else "error",
        "message": res["message"],
        "pending_action": res["pending_action"],
    }


@router.delete("/api/agent/sessions/{session_id}")
def delete_session(session_id: str):
    with engine_lock:
        if not db_get_session(session_id):
            return {"status": "error", "message": "session tidak ditemukan"}
        db_delete_session(session_id)
    return {"status": "success"}


class AgentChatRequest(BaseModel):
    session_id: str | None = None
    text: str


def _ensure_dashboard_session(session_id):
    with engine_lock:
        if session_id and db_get_session(session_id):
            return session_id
        return db_create_session(source="dashboard")


@router.post("/api/agent/chat")
def agent_chat(req: AgentChatRequest):
    session_id = _ensure_dashboard_session(req.session_id)
    return run_agent_chat_session_final(session_id, req.text)


@router.post("/api/agent/chat/stream")
def agent_chat_stream(req: AgentChatRequest):
    session_id = _ensure_dashboard_session(req.session_id)

    def generate():
        yield json.dumps({"step": "session", "session_id": session_id}, ensure_ascii=False) + "\n"
        for step in run_agent_chat_session(session_id, req.text):
            yield json.dumps(step, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


class AgentExecuteRequest(BaseModel):
    tool: str
    args: dict = {}


@router.post("/api/agent/execute")
def agent_execute(req: AgentExecuteRequest):
    if req.tool not in ACTION_TOOLS:
        return {"status": "error", "message": "Aksi tidak dikenal atau tidak diizinkan."}
    try:
        result = ACTION_TOOLS[req.tool](**req.args)
    except TypeError as e:
        return {"status": "error", "message": f"Argumen tidak valid: {e}"}
    return {"status": "success", "tool": req.tool, "result": result}
