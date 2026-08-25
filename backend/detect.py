import base64
import os
import tempfile
import threading

import cv2
import numpy as np
from ultralytics import YOLO

from .config import MODEL_PATH, EMERGENCY_CLASSES
from . import state
from .rule_engine import process_rules
from .notifications import notify_safety

_model = YOLO(MODEL_PATH)
_model_lock = threading.Lock()

MAX_VIDEO_FRAMES = 24
VIDEO_EXTENSIONS = (".mp4", ".avi", ".mov", ".mkv", ".webm")


def _infer(frame):
    with _model_lock:
        results = _model(frame, conf=state.active_confidence, verbose=False)
    boxes = []
    for box in results[0].boxes:
        boxes.append({
            "class_name": _model.names[int(box.cls)],
            "confidence": round(float(box.conf), 2),
            "xyxy": box.xyxy[0].tolist(),
        })
    return boxes


def _draw(frame, boxes):
    out = frame.copy()
    for box in boxes:
        if not state.is_class_visible(box["class_name"]):
            continue
        x1, y1, x2, y2 = (int(v) for v in box["xyxy"])
        cls_upper = box["class_name"].upper()
        if "NO-" in cls_upper:
            color = (0, 0, 255)
        elif box["class_name"] in EMERGENCY_CLASSES:
            color = (0, 128, 255)
        else:
            color = (0, 255, 0)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        label = f"{box['class_name']} {box['confidence']}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        if y1 - 20 < 0:
            ty, py1, py2 = y1 + th + 10, y1, y1 + th + 15
        else:
            ty, py1, py2 = y1 - 10, y1 - th - 15, y1
        cv2.rectangle(out, (x1, py1), (x1 + tw, py2), color, -1)
        cv2.putText(out, label, (x1, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    return out


def _evidence_jpeg(frame, box):
    return _draw(frame, [box])


def _sample_video_frames(path):
    cap = cv2.VideoCapture(path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    frames = []
    if total > 0:
        sample_count = min(MAX_VIDEO_FRAMES, total)
        indices = sorted({int(i * total / sample_count) for i in range(sample_count)})
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if ok:
                frames.append(frame)
    else:
        while len(frames) < MAX_VIDEO_FRAMES:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
    cap.release()
    return frames


def run_detection(file_bytes, filename):
    """Synchronous single-shot pipeline: one upload -> one inference -> one result. No background loop."""
    ext = os.path.splitext(filename or "")[1].lower()
    is_video = ext in VIDEO_EXTENSIONS

    if is_video:
        fd, tmp_path = tempfile.mkstemp(suffix=ext)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(file_bytes)
            frames = _sample_video_frames(tmp_path)
        finally:
            os.remove(tmp_path)
    else:
        arr = np.frombuffer(file_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        frames = [frame] if frame is not None else []

    if not frames:
        return {"status": "error", "message": "Gagal membaca file — pastikan format gambar/video didukung."}

    best_frame, best_boxes = frames[0], []
    for frame in frames:
        boxes = _infer(frame)
        if len(boxes) > len(best_boxes):
            best_frame, best_boxes = frame, boxes

    annotated = _draw(best_frame, best_boxes)
    ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
    annotated_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None

    new_events = process_rules(best_boxes)
    incidents = []
    for event, box in new_events:
        _, crop_buf = cv2.imencode(".jpg", _evidence_jpeg(best_frame, box), [cv2.IMWRITE_JPEG_QUALITY, 85])
        state.store_event_crop(event["id"], crop_buf.tobytes())
        notify_safety(event)
        incidents.append(event)

    return {
        "status": "success",
        "is_video": is_video,
        "frames_processed": len(frames),
        "detections": best_boxes,
        "annotated_image": annotated_b64,
        "incidents": incidents,
    }
