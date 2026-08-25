import os
import sys
import threading

# fix Windows cp1252 crash on emoji print()
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
VIDEO_DIR = os.path.join(PROJECT_ROOT, "VIdeo Testing")
MODEL_DIR = os.path.join(PROJECT_ROOT, "model dan dataset")
DB_PATH = os.path.join(PROJECT_ROOT, "smart_factory.db")


def _load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, val)


_load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

MODEL_REGISTRY = {
    "yolov11m": {"label": "YOLOv11m", "path": os.path.join(MODEL_DIR, "yolo v11.pt")},
    "yolo26m": {"label": "YOLO26m", "path": os.path.join(MODEL_DIR, "yolo v26.pt")},
}
DEFAULT_MODEL = "yolo26m"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
# vision model for autonomous crop verification
GEMINI_VISION_MODEL = os.environ.get("GEMINI_VISION_MODEL", "gemini-flash-latest")
# fallback if primary is overloaded (503) / rate-limited (429)
GEMINI_VISION_MODEL_FALLBACK = os.environ.get("GEMINI_VISION_MODEL_FALLBACK", "gemini-flash-lite-latest")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DISCORD_WEBHOOK_URL_ACTIONS = os.environ.get("DISCORD_WEBHOOK_URL_ACTIONS", "")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_CHAT_CHANNEL_ID = os.environ.get("DISCORD_CHAT_CHANNEL_ID", "")

DEFAULT_VIDEOS = ["WIN_20260821_01_16_00_Pro.mp4", "WIN_20260821_01_16_15_Pro.mp4"]

STREAM_SOURCES = {
    "stream_01": os.path.join(VIDEO_DIR, DEFAULT_VIDEOS[0]),
    "stream_02": os.path.join(VIDEO_DIR, DEFAULT_VIDEOS[1]),
}

# mutated in place by actions.apply_source
stream_source_tokens = {
    "stream_01": DEFAULT_VIDEOS[0],
    "stream_02": DEFAULT_VIDEOS[1],
}


def list_video_files():
    if not os.path.isdir(VIDEO_DIR):
        return []
    return sorted(
        f for f in os.listdir(VIDEO_DIR)
        if f.lower().endswith((".mp4", ".avi", ".mov", ".mkv"))
    )


def resolve_source(token):
    if token is None:
        return None, "source required"
    if str(token).lower() == "webcam":
        return 0, None
    if token in list_video_files():
        return os.path.join(VIDEO_DIR, token), None
    return None, "unknown source"


PPE_TO_VIOLATION = {
    "Hardhat": "NO-Hardhat",
    "Mask": "NO-Mask",
    "Safety Vest": "NO-Safety Vest",
}
ALL_PPE = list(PPE_TO_VIOLATION.keys())
EMERGENCY_CLASSES = {"Fire", "Smoke"}
ALL_EMERGENCY = sorted(EMERGENCY_CLASSES)

CONTEXT_CLASSES = ["Person", "Safety Cone", "machinery", "vehicle"]

ALL_CLASSES = [
    "NO-Hardhat", "NO-Mask", "NO-Safety Vest",
    "Fire", "Smoke",
    "Person",
    "Hardhat", "Mask", "Safety Vest",
    "Safety Cone", "machinery", "vehicle",
]

URGENCY_LEVELS = ("info", "warning", "critical")
DEFAULT_URGENCY = "warning"

context_lock = threading.Lock()


def default_class_config(monitored):
    return {
        cls: {
            "display": True,
            "monitor": cls in monitored,
            "urgency": monitored.get(cls, "info"),
        }
        for cls in ALL_CLASSES
    }


DEFAULT_ZONE_RULES = {
    "stream_01": {
        "label": "Assembly Line A (Cam 01)",
        "classes": default_class_config({
            "NO-Hardhat": "warning", "NO-Safety Vest": "warning",
            "Fire": "critical", "Smoke": "critical",
        }),
    },
    "stream_02": {
        "label": "Welding Bay B (Cam 02)",
        "classes": default_class_config({
            "NO-Hardhat": "warning", "NO-Mask": "warning", "NO-Safety Vest": "warning",
            "Fire": "critical", "Smoke": "critical",
        }),
    },
}

PERMISSION_MODES = ("standard", "accept_low_risk", "auto")
