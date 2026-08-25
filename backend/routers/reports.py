import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

from ..reports import REPORTS_DIR, generate_report_file

router = APIRouter()

_MEDIA = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
}


@router.get("/api/reports/file/{filename}")
def download_report(filename: str):
    safe = os.path.basename(filename)  # prevent path traversal
    path = os.path.join(REPORTS_DIR, safe)
    if not os.path.exists(path):
        return {"status": "error", "message": "file tidak ditemukan"}
    ext = safe.rsplit(".", 1)[-1].lower()
    return FileResponse(path, filename=safe, media_type=_MEDIA.get(ext, "application/octet-stream"))


@router.get("/api/reports/generate")
def generate(format: str = "pdf", since_hours: float = 24, zone: str = ""):
    res = generate_report_file(format, since_hours, zone)
    if res.get("status") != "success":
        return res
    return FileResponse(
        res["path"], filename=res["filename"],
        media_type=_MEDIA.get(res["format"], "application/octet-stream"),
    )
