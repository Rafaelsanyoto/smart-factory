"""Camera manager — one shared OpenCV capture per stream feeding three threads: capture
(reads raw frames), ai (runs YOLO + the rule engine), and render (draws overlays into a
JPEG for the MJPEG stream). A single capture avoids double-opening the same webcam/file."""
import asyncio
import threading
import time

import cv2
from fastapi import Request
from ultralytics import YOLO

from .config import MODEL_REGISTRY, DEFAULT_MODEL, EMERGENCY_CLASSES, STREAM_SOURCES
from . import state
from .rule_engine import process_rules
from .notifications import notify_safety
from . import autonomous


def _evidence_jpeg(frame, box):
    """Full-frame JPEG with the triggering detection boxed + labeled. A full scene with a
    highlight box is clearer evidence than a tight crop (you see where/what in context), and
    gives the autonomous vision model more context while still pointing it at the region.
    Returns bytes, or None on failure."""
    img = frame.copy()
    x1, y1, x2, y2 = (int(v) for v in (box.get("xyxy") or [0, 0, 0, 0]))
    cls = box.get("class_name", "")
    color = (0, 128, 255) if cls in EMERGENCY_CLASSES else (0, 0, 255)  # BGR: orange / red
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
    label = f"{cls} {box.get('confidence', '')}".strip()
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    ly = y1 - 8 if y1 - 8 > th else y1 + th + 8
    cv2.rectangle(img, (x1, ly - th - 6), (x1 + tw + 6, ly + 4), color, -1)
    cv2.putText(img, label, (x1 + 3, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else None


class SmoothCameraManager:
    def __init__(self, source, stream_id):
        self.stream_id = stream_id
        self.source = source
        self.source_version = 0
        self.source_lock = threading.Lock()

        self.model = YOLO(MODEL_REGISTRY[DEFAULT_MODEL]["path"])
        self.model_lock = threading.Lock()

        self.latest_frame = None          # raw frame from the single capture
        self.frame_lock = threading.Lock()
        self.current_frame_bytes = None   # rendered JPEG for streaming
        self.latest_boxes = []
        self.running = True
        self.paused = True  # start paused — nothing captured/detected until an admin resumes it

        self.capture_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.capture_thread.start()

        self.ai_thread = threading.Thread(target=self.ai_loop, daemon=True)
        self.ai_thread.start()

        self.render_thread = threading.Thread(target=self.render_loop, daemon=True)
        self.render_thread.start()

    # -- source control ------------------------------------------------------
    def switch_source(self, resolved):
        with self.source_lock:
            self.source = resolved
            self.source_version += 1

    def switch_model(self, path):
        new_model = YOLO(path)  # heavy load done outside the lock
        with self.model_lock:
            self.model = new_model
            self.latest_boxes = []

    def set_paused(self, value):
        self.paused = bool(value)

    # -- threads -------------------------------------------------------------
    def capture_loop(self):
        cap = cv2.VideoCapture(self.source)
        local_version = self.source_version
        is_file = isinstance(self.source, str)

        while self.running:
            # Reopen if the source changed
            if self.source_version != local_version:
                cap.release()
                with self.source_lock:
                    local_version = self.source_version
                    new_source = self.source
                cap = cv2.VideoCapture(new_source)
                is_file = isinstance(new_source, str)

            if self.paused:
                time.sleep(0.15)  # freeze feed, stop reading — lighter during testing
                continue

            success, frame = cap.read()
            if not success:
                if is_file:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop the dummy video
                else:
                    time.sleep(0.1)  # webcam hiccup, retry
                continue

            frame = cv2.resize(frame, (640, 480))
            with self.frame_lock:
                self.latest_frame = frame

            time.sleep(0.01)

        cap.release()

    def ai_loop(self):
        while self.running:
            if self.paused:
                time.sleep(0.15)  # skip inference — the expensive part — while paused
                continue

            with self.frame_lock:
                frame = None if self.latest_frame is None else self.latest_frame.copy()

            if frame is None:
                time.sleep(0.02)
                continue

            with self.model_lock:
                results = self.model.track(
                    frame, persist=True, conf=state.active_confidence, verbose=False
                )

            boxes_data = []
            for box in results[0].boxes:
                track_id = int(box.id[0]) if box.id is not None else None
                boxes_data.append({
                    "class_name": self.model.names[int(box.cls)],
                    "confidence": round(float(box.conf), 2),
                    "track_id": track_id,
                    "xyxy": box.xyxy[0].tolist(),
                })

            self.latest_boxes = boxes_data
            # process_rules tags boxes with episode_status and returns events created this
            # frame. We hold the frame here, so we crop each new detection for evidence,
            # then notify (with the crop) and hand off to the autonomous worker if enabled.
            new_events = process_rules(self.stream_id, boxes_data)
            for event, box in new_events:
                crop = _evidence_jpeg(frame, box)
                if crop:
                    state.store_event_crop(event["id"], crop)
                notify_safety(event)
                if state.autonomous_mode:
                    autonomous.enqueue(event)

            state.latest_detections[self.stream_id] = [
                {
                    "class_name": d["class_name"],
                    "confidence": d["confidence"],
                    "track_id": d["track_id"],
                    "episode_status": d.get("episode_status"),
                }
                for d in boxes_data
            ]

            time.sleep(0.02)

    def render_loop(self):
        while self.running:
            with self.frame_lock:
                frame = None if self.latest_frame is None else self.latest_frame.copy()

            if frame is None:
                time.sleep(0.03)
                continue

            for box in self.latest_boxes:
                if not state.is_class_visible(self.stream_id, box["class_name"]):
                    continue

                coords = box["xyxy"]
                x1, y1, x2, y2 = int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3])

                cls_upper = box["class_name"].upper()
                if "NO-" in cls_upper:
                    color = (0, 0, 255)        # red — violation
                elif box["class_name"] in EMERGENCY_CLASSES:
                    color = (0, 128, 255)      # orange — emergency
                else:
                    color = (0, 255, 0)        # green — compliant/neutral

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

                label = f"{box['class_name']} {box['confidence']}"
                (text_width, text_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)

                if y1 - 20 < 0:
                    text_y = y1 + text_height + 10
                    plate_y1 = y1
                    plate_y2 = y1 + text_height + 15
                else:
                    text_y = y1 - 10
                    plate_y1 = y1 - text_height - 15
                    plate_y2 = y1

                cv2.rectangle(frame, (x1, plate_y1), (x1 + text_width, plate_y2), color, -1)
                cv2.putText(frame, label, (x1, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            self.current_frame_bytes = buffer.tobytes()

            time.sleep(0.033)

    def get_frame(self):
        return self.current_frame_bytes


# One manager per configured stream. Creating these starts the capture/ai/render threads
# immediately (they idle while paused, which is the default on startup).
cameras = {stream_id: SmoothCameraManager(src, stream_id) for stream_id, src in STREAM_SOURCES.items()}


async def generate_video_stream(request: Request, stream_id: str):
    camera = cameras.get(stream_id)
    if not camera:
        return

    while True:
        if await request.is_disconnected():
            break

        frame = camera.get_frame()
        if frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

        await asyncio.sleep(0.033)
