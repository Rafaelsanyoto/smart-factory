"""Static configuration: paths, environment variables, model registry, and the fixed
domain constants (PPE classes, emergency classes, default zone rules). Nothing here is
mutated at runtime — anything that changes while the app runs lives in state.py instead.

This module is imported (directly or transitively) before anything else, so the stdout
UTF-8 fix below runs early enough to protect the very first emoji print()."""
import os
import sys

# Windows defaults stdout/stderr to the system codepage (cp1252 here), which raises
# UnicodeEncodeError and crashes the process on any print() containing an emoji or other
# non-cp1252 character — e.g. the 🚨/⚠️ notification icons, or unicode text a future Gemini
# response might contain. Force UTF-8 so that class of crash can't happen. Only console
# streams support reconfigure (redirected-to-file streams from `run_in_background` do
# too, but guard anyway in case stdout has been replaced by something that doesn't).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Paths — the code now lives in backend/, but the data folders (.env, videos, model
# weights, the SQLite file) stay at the project root, so resolve everything relative to
# the parent of this package instead of the package dir.
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))          # .../smart-factory/backend
PROJECT_ROOT = os.path.dirname(BASE_DIR)                        # .../smart-factory
VIDEO_DIR = os.path.join(PROJECT_ROOT, "VIdeo Testing")
MODEL_DIR = os.path.join(PROJECT_ROOT, "model dan dataset")
DB_PATH = os.path.join(PROJECT_ROOT, "smart_factory.db")


def _load_dotenv(path):
    """Minimal .env loader (no external dependency). Real environment variables that
    are already set take precedence over the file — same behavior as python-dotenv."""
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

# --- AI Agent: message wording via Gemini (free tier), dispatch to a notify channel ----
# All optional. If unset, notify_safety() falls back to fixed template text and skips
# external dispatch — the app runs fine without any of this configured.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
# Notification channel — Discord webhook (one URL, no bot needed for outbound messages).
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
# Optional SECOND Discord channel, just for "action taken" updates — lets you split new
# detections from remediation follow-ups into two channels. Falls back to the main
# channel above if left unset.
DISCORD_WEBHOOK_URL_ACTIONS = os.environ.get("DISCORD_WEBHOOK_URL_ACTIONS", "")

# --- Discord BOT (two-way chat) -----------------------------------------------------
# Separate from the webhooks above — a webhook can only push messages OUT, it can't read
# anything typed in Discord. This needs a real Bot Token (Discord Developer Portal ->
# your app -> Bot -> Reset Token) with "Message Content Intent" enabled, invited to the
# server. Messages sent in DISCORD_CHAT_CHANNEL_ID get forwarded to the same AI Agent
# used by the dashboard chat (read-only — it can answer questions, but can't execute
# actions from Discord since there's no confirm/cancel UI there). See discord_bot.py.
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_CHAT_CHANNEL_ID = os.environ.get("DISCORD_CHAT_CHANNEL_ID", "")

# Default video files for the two dummy streams
DEFAULT_VIDEOS = ["WIN_20260821_01_16_00_Pro.mp4", "WIN_20260821_01_16_15_Pro.mp4"]

STREAM_SOURCES = {
    "stream_01": os.path.join(VIDEO_DIR, DEFAULT_VIDEOS[0]),
    "stream_02": os.path.join(VIDEO_DIR, DEFAULT_VIDEOS[1]),
}

# Human-readable source token per stream (for the API / UI). Mutated in place at runtime
# by actions.apply_source — kept here (not state.py) because it's a dict updated in place,
# so its identity stays stable for every importer.
stream_source_tokens = {
    "stream_01": DEFAULT_VIDEOS[0],
    "stream_02": DEFAULT_VIDEOS[1],
}


def list_video_files():
    """Video files actually present in VIdeo Testing/."""
    if not os.path.isdir(VIDEO_DIR):
        return []
    return sorted(
        f for f in os.listdir(VIDEO_DIR)
        if f.lower().endswith((".mp4", ".avi", ".mov", ".mkv"))
    )


def resolve_source(token):
    """Map a UI source token to an OpenCV source. Rejects arbitrary paths.

    Returns (resolved_source, error_message). resolved_source is an int (webcam)
    or an absolute file path; error_message is None on success.
    """
    if token is None:
        return None, "source required"
    if str(token).lower() == "webcam":
        return 0, None
    # Only allow files that actually live in VIDEO_DIR
    if token in list_video_files():
        return os.path.join(VIDEO_DIR, token), None
    return None, "unknown source"


# ---------------------------------------------------------------------------
# Per-zone PPE rules + domain constants (runtime-editable rules live in state.ZONE_RULES,
# seeded from DEFAULT_ZONE_RULES below on first run).
# ---------------------------------------------------------------------------
PPE_TO_VIOLATION = {
    "Hardhat": "NO-Hardhat",
    "Mask": "NO-Mask",
    "Safety Vest": "NO-Safety Vest",
}
ALL_PPE = list(PPE_TO_VIOLATION.keys())
EMERGENCY_CLASSES = {"Fire", "Smoke"}
ALL_EMERGENCY = sorted(EMERGENCY_CLASSES)

# Context classes: detectable, but never a compliance violation (no NO-* pair). Their
# on/off toggle only controls display (bounding boxes + breakdown panel), not rule logic.
CONTEXT_CLASSES = ["Person", "Safety Cone", "machinery", "vehicle"]

import threading  # noqa: E402 — kept next to the lock it guards for readability
context_lock = threading.Lock()

DEFAULT_ZONE_RULES = {
    "stream_01": {
        "label": "Assembly Line A (Cam 01)",
        "required": ["Hardhat", "Safety Vest"],
        "emergency": ["Fire", "Smoke"],
    },
    "stream_02": {
        "label": "Welding Bay B (Cam 02)",
        "required": ["Hardhat", "Mask", "Safety Vest"],
        "emergency": ["Fire", "Smoke"],
    },
}

# AI Agent permission modes — how autonomously the agent's ACTION tools may run without a
# human confirm click. The active mode is runtime state (state.agent_permission_mode);
# this is just the allowed set.
PERMISSION_MODES = ("standard", "accept_low_risk", "auto")
