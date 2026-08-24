"""Video streaming + source/pause control endpoints."""
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import CONTEXT_CLASSES
from ..camera import cameras, generate_video_stream
from .. import state
from ..actions import apply_source, apply_pause, sources_payload

router = APIRouter()


@router.get("/api/video/{stream_id}")
async def video_feed(request: Request, stream_id: str):
    return StreamingResponse(
        generate_video_stream(request, stream_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/api/data/{stream_id}")
async def stream_data(stream_id: str):
    cam = cameras.get(stream_id)
    visible = [
        d for d in state.latest_detections.get(stream_id, [])
        if d["class_name"] not in CONTEXT_CLASSES or state.is_context_visible(d["class_name"])
    ]
    return {
        "status": "success",
        "detections": visible,
        "paused": bool(cam.paused) if cam else False,
    }


@router.get("/api/sources")
def get_sources():
    return sources_payload()


class SourceSet(BaseModel):
    source: str


@router.post("/api/stream/{stream_id}/source")
def set_source(stream_id: str, req: SourceSet):
    return apply_source(stream_id, req.source)


class PauseSet(BaseModel):
    paused: bool


@router.post("/api/stream/{stream_id}/pause")
def set_pause(stream_id: str, req: PauseSet):
    return apply_pause(stream_id, req.paused)
