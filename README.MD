# Smart Factory HSE Command Dashboard

Autonomous Safety Surveillance & Incident Workflow system for AI Innovation Challenge (AIC) COMPFEST 18, Smart Manufacturing track — real-time YOLO-based PPE compliance & fire/smoke detection, a server-side rule engine with full incident lifecycle tracking, an AI Agent (Gemini function calling), and a FastAPI + React dashboard.

---

## Tech Stack

**Backend** — `api.py` (single file)
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) — HTTP API & MJPEG video streaming
- [Ultralytics YOLO](https://docs.ultralytics.com/) (YOLOv11m / YOLO26m) + [OpenCV](https://opencv.org/) — object detection & video capture
- [google-genai](https://pypi.org/project/google-genai/) (Gemini) — AI Agent chat with function calling (tool use)
- Plain `urllib` — Discord webhook / Telegram bot dispatch (no extra HTTP client dependency)
- In-memory state only — no database. Everything (events, notifications, zone rules) lives in process memory and resets on restart.

**Frontend** — `frontend/` (Vite + React)
- [React](https://react.dev/) + [React Router](https://reactrouter.com/) — SPA with client-side routing
- [Tailwind CSS](https://tailwindcss.com/) — styling
- [Recharts](https://recharts.org/) — Analytics charts
- [lucide-react](https://lucide.dev/) — icons (the only icon set used, by design)

---

## Folder Structure

```
smart-factory/
├── api.py                      # FastAPI backend — camera pipeline, rule engine, AI Agent, all endpoints
├── .env                        # Your local secrets (gitignored) — copy from .env.example
├── .env.example                # Template: Gemini key, Discord/Telegram channel setup instructions
│
├── model dan dataset/          # YOLO weights + training dataset (gitignored — only folder tracked)
│   ├── yolo v11.pt
│   ├── yolo v26.pt
│   └── master_dataset/         # train/valid/test images + labels, data.yaml
│
├── VIdeo Testing/               # Dummy CCTV footage for the two demo streams (gitignored)
├── Gambar testing/               # Test images (gitignored)
│
└── frontend/
    ├── src/
    │   ├── App.jsx              # Shell: nav, header status, lifted incident polling
    │   ├── pages/
    │   │   ├── Login.jsx         # admin/admin gate
    │   │   ├── LiveMonitor.jsx   # Video feed, live breakdown, incident queue, action tracking
    │   │   ├── Analytics.jsx     # Charts over confirmed incidents
    │   │   ├── Settings.jsx      # Model/confidence/zone rules/source/pause/display filters
    │   │   └── AgentChat.jsx     # AI Agent chat page (streaming tool-call trail)
    │   ├── main.jsx / index.css
    │   └── assets/
    ├── package.json
    └── vite.config.js
```

---

## Features

### Detection pipeline
- Two simulated CCTV streams (dummy video, or switch either to your **webcam** live from Settings)
- 12-class YOLO model: PPE compliance (Hardhat, Mask, Safety Vest + their `NO-*` violation counterparts), Fire, Smoke, and context objects (Person, Safety Cone, machinery, vehicle)
- Runtime **model switching** (YOLOv11m ↔ YOLO26m) and **confidence threshold** tuning, no restart needed
- Per-stream **pause/resume** — streams start **paused by default**; nothing is captured or detected until resumed
- Configurable per-zone rules: which PPE is required, which emergency classes (Fire/Smoke) are monitored

### Server-side rule engine
- Detections don't create incidents immediately — an episode must be seen continuously for **5 seconds** (filters single-frame flicker) before it's confirmed real
- Episodes are matched by **spatial position (IoU)**, not tracker ID (YOLO's tracker reassigns IDs too often to be a reliable person identity) — so two people violating at once, in different spots, are correctly tracked as separate incidents
- A **30-second continuity window**: the same ongoing violation doesn't re-fire repeatedly; a genuinely new occurrence (after the class has been absent from that zone for 30s+) starts a fresh episode

### Full incident lifecycle tracking
`PENDING` (detected) → `CONFIRMED` / `DISMISSED` (admin review in Live Monitor) → **action recorded** (admin logs what remediation was taken). Every stage is backend-persisted and queryable — nothing lives only in the browser.

### AI Agent (Gemini function calling)
- Chat page with a **live step trail** (streamed NDJSON) — see exactly which tool it's calling and what it found, not just a spinner
- **Read tools** (safe, auto-executed): query events (with status/zone/class/time filters), notifications, zone config, stream status, system config
- **Action tools** (proposed, never auto-run): send an alert, change zone rules, change confidence, pause/resume a stream, switch model, toggle display filters — every action surfaces a confirm/cancel card first
- Ask it things like *"Ada pelanggaran apa 10 menit terakhir?"*, *"Zona mana paling sering melanggar?"*, or *"Pause kamera Welding Bay"*

### Notifications
- Deterministic, consistently-formatted messages (bold + bullet points) — no LLM involved, so wording never varies
- Auto-**batches** events that fire within a 2-second window into a single outbound message instead of spamming one per detection
- Dispatched to **Discord** (webhook) or **Telegram** (bot) — optionally to **two separate channels**: one for new detections, another for "action taken" updates

---

## Prerequisites

- **Python 3.10+** with a CUDA-capable environment recommended (YOLO inference is much faster on GPU; CPU works but slower)
- **Node.js 18+** & npm

---

## Setup

### 1. Environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in what you need (all optional — the app runs fine with everything blank, just without AI Agent chat / external notifications):

| Variable | Purpose | How to get it |
|---|---|---|
| `GEMINI_API_KEY` | Powers the AI Agent chat | https://aistudio.google.com/apikey (free tier) |
| `GEMINI_MODEL` | Defaults to `gemini-flash-lite-latest` — has a much higher free daily quota than full "flash" models | — |
| `DISCORD_WEBHOOK_URL` | Notification channel for new detections | Discord → Server Settings → Integrations → Webhooks → New Webhook |
| `DISCORD_WEBHOOK_URL_ACTIONS` | Optional 2nd channel, just for "action taken" updates | Same as above, different channel |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Fallback channel if Discord isn't set | Chat `@BotFather` → `/newbot`, then `https://api.telegram.org/bot<TOKEN>/getUpdates` |

### 2. Backend

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install fastapi uvicorn ultralytics opencv-python numpy google-genai
python api.py
```

Backend runs at `http://127.0.0.1:8000`.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the printed dev URL (usually `http://localhost:5173`).

**Login:** `admin` / `admin`

> Streams start **paused** — click **Resume Feed** on Live Monitor (or from Settings) to start detection.
