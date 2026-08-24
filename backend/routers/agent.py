"""AI Agent endpoints: status, permission mode, chat sessions/messages, streaming chat,
pending-action resolution, and direct action execution."""
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import GEMINI_API_KEY, PERMISSION_MODES
from ..database import (
    engine_lock, db_create_session, db_get_session, db_get_sessions, db_delete_session,
    db_get_messages, db_get_message, db_update_message_pending_action, MAX_MESSAGES_PER_SESSION,
)
from .. import state
from ..notifications import configured_channel
from ..actions import apply_permission_mode
from ..agent import (
    ACTION_TOOLS, ACTION_RISK, run_agent_chat_session, run_agent_chat_session_final,
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
    """Records what happened to a proposed action directly on the chat message, so
    reloading the session shows the real outcome instead of "Awaiting" forever."""
    with engine_lock:
        msg = db_get_message(message_id)
        if not msg:
            return {"status": "error", "message": "Pesan tidak ditemukan."}
        pending = msg.get("pending_action")
        if not pending:
            return {"status": "error", "message": "Pesan ini tidak punya aksi tertunda."}
        if pending.get("state") and pending["state"] != "awaiting":
            return {"status": "error", "message": "Aksi ini sudah diproses sebelumnya.", "pending_action": pending}

        if not req.approve:
            pending["state"] = "cancelled"
            db_update_message_pending_action(message_id, pending)
            return {"status": "success", "pending_action": pending}

        tool = pending.get("tool")
        args = pending.get("args") or {}
        if tool not in ACTION_TOOLS:
            pending["state"] = "failed"
            pending["result"] = "Aksi tidak dikenal atau tidak diizinkan."
            db_update_message_pending_action(message_id, pending)
            return {"status": "error", "message": pending["result"], "pending_action": pending}

        try:
            result = ACTION_TOOLS[tool](**args)
            ok = result.get("status") != "error"
        except TypeError as e:
            ok = False
            result = {"message": f"Argumen tidak valid: {e}"}

        pending["state"] = "done" if ok else "failed"
        pending["result"] = result.get("message") or ("Aksi berhasil dijalankan." if ok else "Aksi gagal.")
        db_update_message_pending_action(message_id, pending)
        return {"status": "success" if ok else "error", "pending_action": pending}


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
    """Non-streaming variant. Kept for simple callers (curl/tests); the dashboard UI uses
    /api/agent/chat/stream instead."""
    session_id = _ensure_dashboard_session(req.session_id)
    return run_agent_chat_session_final(session_id, req.text)


@router.post("/api/agent/chat/stream")
def agent_chat_stream(req: AgentChatRequest):
    """Streaming variant (newline-delimited JSON) — the UI renders each step live as the
    agent works: which tool it's calling, what it found, then the final reply/action.
    First line is always a 'session' step so the client learns the session_id when a new
    one was just created."""
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
