import os
import sys
import threading

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
MODEL_DIR = os.path.join(PROJECT_ROOT, "model dan dataset")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "smart_factory.db")


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

MODEL_ID = "yolo26m"
MODEL_LABEL = "YOLO26m"
MODEL_PATH = os.path.join(MODEL_DIR, "yolo v26.pt")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DISCORD_WEBHOOK_URL_ACTIONS = os.environ.get("DISCORD_WEBHOOK_URL_ACTIONS", "")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_CHAT_CHANNEL_ID = os.environ.get("DISCORD_CHAT_CHANNEL_ID", "")

PPE_TO_VIOLATION = {
    "Hardhat": "NO-Hardhat",
    "Mask": "NO-Mask",
    "Safety Vest": "NO-Safety Vest",
}
EMERGENCY_CLASSES = {"Fire", "Smoke"}

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


DEFAULT_CLASS_RULES = default_class_config({
    "NO-Hardhat": "warning", "NO-Mask": "warning", "NO-Safety Vest": "warning",
    "Fire": "critical", "Smoke": "critical",
})

RESULT_LABEL = "Hasil Deteksi"
