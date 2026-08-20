import asyncio
import cv2
import time
import threading
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from ultralytics import YOLO

app = FastAPI(title="Smart Factory HSE API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STREAM_SOURCES = {
    "stream_01": "WIN_20260821_01_16_00_Pro.mp4", 
    "stream_02": "WIN_20260821_01_16_15_Pro.mp4"
}

latest_detections = {"stream_01": [], "stream_02": []}

class SmoothCameraManager:
    def __init__(self, source_url, stream_id):
        self.source = source_url
        self.stream_id = stream_id
        self.model = YOLO("best.pt")
        
        self.current_frame_bytes = None
        self.running = True
        self.latest_boxes = []
        
        self.ai_thread = threading.Thread(target=self.ai_loop, daemon=True)
        self.ai_thread.start()
        
        self.video_thread = threading.Thread(target=self.video_loop, daemon=True)
        self.video_thread.start()

    def ai_loop(self):
        cap_ai = cv2.VideoCapture(self.source)
        while self.running:
            success, frame = cap_ai.read()
            if not success:
                cap_ai.set(cv2.CAP_PROP_POS_FRAMES, 0)
                time.sleep(0.1)
                continue
            
            frame = cv2.resize(frame, (640, 480))
            results = self.model.track(frame, persist=True, verbose=False)
            
            boxes_data = []
            for box in results[0].boxes:
                track_id = int(box.id[0]) if box.id is not None else None
                boxes_data.append({
                    "class_name": self.model.names[int(box.cls)],
                    "confidence": round(float(box.conf), 2),
                    "track_id": track_id,
                    "xyxy": box.xyxy[0].tolist()
                })
            
            self.latest_boxes = boxes_data
            latest_detections[self.stream_id] = [
                {"class_name": d["class_name"], "confidence": d["confidence"], "track_id": d["track_id"]} 
                for d in boxes_data
            ]
            
            time.sleep(0.02)

    def video_loop(self):
        cap_smooth = cv2.VideoCapture(self.source)
        while self.running:
            success, frame = cap_smooth.read()
            if not success:
                cap_smooth.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            
            frame = cv2.resize(frame, (640, 480))
            
            for box in self.latest_boxes:
                coords = box["xyxy"]
                x1, y1, x2, y2 = int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3])
                
                is_violation = "NO-" in box['class_name'].upper()
                color = (0, 0, 255) if is_violation else (0, 255, 0) 
                
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

cameras = {stream_id: SmoothCameraManager(url, stream_id) for stream_id, url in STREAM_SOURCES.items()}

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

@app.get("/api/video/{stream_id}")
async def video_feed(request: Request, stream_id: str):
    return StreamingResponse(generate_video_stream(request, stream_id), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/api/data/{stream_id}")
async def stream_data(stream_id: str):
    return {"status": "success", "detections": latest_detections.get(stream_id, [])}