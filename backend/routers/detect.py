from fastapi import APIRouter, UploadFile, File

from ..detect import run_detection

router = APIRouter()


@router.post("/api/detect")
async def detect(file: UploadFile = File(...)):
    data = await file.read()
    return run_detection(data, file.filename)
