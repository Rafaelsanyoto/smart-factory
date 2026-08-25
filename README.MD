# SafeSight AI — Smart Factory HSE Command Dashboard (MVP)

AI Innovation Challenge (AIC) COMPFEST 18, Smart Manufacturing track. MVP submission scope:
upload one image/video, run one YOLO detection pass, review the result — every incident
always waits for a human to confirm it.

---

## Tech Stack

**Backend** — `backend/` package (run via `api.py`)
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) — HTTP API
- [Ultralytics YOLO](https://docs.ultralytics.com/) (YOLO26m, single model) + [OpenCV](https://opencv.org/) — object detection
- [google-genai](https://pypi.org/project/google-genai/) (Gemini) — AI Agent chat with function calling
- [discord.py](https://pypi.org/project/discord.py/) — two-way Discord chat bot (optional)
- Plain `urllib` — Discord webhook dispatch
- [SQLite](https://www.sqlite.org/) (`data/smart_factory.db`) — incidents, notifications, class rules, chat history

**Frontend** — `frontend/` (Vite + React)
- [React](https://react.dev/) + [React Router](https://reactrouter.com/)
- [Tailwind CSS](https://tailwindcss.com/)
- [lucide-react](https://lucide.dev/) — the only icon set used

---

## Folder Structure

```
smart-factory/
├── api.py                      # Entry point — `from backend.app import app` + uvicorn
├── backend/
│   ├── app.py                  # Assembles FastAPI: CORS, routers, Discord startup hook
│   ├── config.py                # Paths, .env, single model path, class taxonomy
│   ├── database.py              # SQLite layer
│   ├── state.py                 # Runtime-mutable state (confidence, class rules)
│   ├── detect.py                 # Single-shot inference: one upload -> one result
│   ├── rule_engine.py            # Monitored-class check -> PENDING incident
│   ├── notifications.py          # Notification templates + Discord dispatch
│   ├── followup.py               # mark_acted / dismiss_event
│   ├── actions.py                # apply_* helpers shared by REST routes AND the AI Agent
│   ├── agent.py                   # AI Agent: tools, Gemini function-calling loop, chat sessions
│   ├── reports.py                 # PDF/XLSX/CSV report generation
│   ├── discord_bot.py             # Two-way Discord chat bot (optional)
│   └── routers/
│       ├── detect.py               # POST /api/detect
│       ├── settings.py             # health, db-info, model info, confidence, class rules
│       ├── events.py               # incident lifecycle (verify/action/delete/acknowledge)
│       ├── agent.py                # /api/agent/* endpoints
│       └── reports.py              # report file endpoints
│
├── data/                        # SQLite DB + generated reports (gitignored, created on first run)
├── .env / .env.example          # Secrets: Gemini key, Discord webhook/bot
│
├── model dan dataset/            # YOLO26m weights (gitignored — only folder tracked)
│   └── yolo v26.pt
│
├── Dockerfile.backend
├── docker-compose.yml
│
└── frontend/
    ├── Dockerfile / nginx.conf
    └── src/
        ├── App.jsx                # Shell: nav, header status, lifted incident polling
        ├── pages/
        │   ├── Login.jsx            # admin/admin gate
        │   ├── Detect.jsx           # upload -> Mulai Proses -> result + incident review
        │   ├── Settings.jsx         # confidence, class rules, db info
        │   └── AgentChat.jsx        # AI Agent chat page
        └── components/
```

---

## Features

### Detection — single synchronous flow
Upload one image or video, click **Mulai Proses**. The backend runs YOLO26m once (for a
video, on frames sampled evenly across it), draws the results, and returns one annotated
image plus the detection list — all within that one request. There is no background
capture loop and no continuous camera stream.

### Rule check -> incident
Every detected object belonging to a monitored class (configurable in Settings) creates
one `PENDING` incident, recorded synchronously in that same request.

### Incident lifecycle — always human-reviewed
`PENDING` (detected) → `CONFIRMED` / `DISMISSED` (human review) → **action recorded**.
Nothing auto-confirms: there is no autonomous vision verification and no reminder
scheduler — review happens whenever an operator looks at the queue.

### AI Agent (Gemini function calling)
- Chat page with a live step trail — see which tool it calls and what it found
- **Read tools** (auto-executed): query recorded incidents/notifications, class rules,
  system config, aggregate report stats
- **Action tools** (always proposed, never auto-run): send an alert, change class rules,
  change confidence, verify/dismiss an incident, record an action — every action shows a
  confirm/cancel card first, with no auto-run mode
- Ask it things like *"Berapa insiden Fire yang belum ditindak?"* or *"Kirim ringkasan ke Discord"*

### Notifications
Deterministic, consistently-formatted messages sent to Discord via webhook as soon as an
incident is recorded, plus updates when action is taken or an incident is deleted.

### Discord bot (two-way chat, optional)
Chat with the AI Agent from a Discord channel — same tools as the dashboard, action
requests show a confirm/cancel button.

---

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** & npm
- YOLO26m weights at `model dan dataset/yolo v26.pt` (not included in this repo)
- Docker + Docker Compose (only if running via `docker compose up`)

---

## Setup — native

### 1. Environment variables

```bash
cp .env.example .env
```

All variables are optional — the app runs without any of them, just without AI Agent
chat / Discord notifications.

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Powers the AI Agent chat (https://aistudio.google.com/apikey) |
| `GEMINI_MODEL` | Defaults to `gemini-flash-lite-latest` |
| `DISCORD_WEBHOOK_URL` | Notification channel for new incidents |
| `DISCORD_WEBHOOK_URL_ACTIONS` | Optional 2nd channel for action/deletion updates |
| `DISCORD_BOT_TOKEN` / `DISCORD_CHAT_CHANNEL_ID` | Optional two-way Discord chat |

### 2. Backend

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
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

---

## Setup — Docker

```bash
cp .env.example .env
docker compose up --build
```

- Backend: `http://localhost:8000`
- Frontend: `http://localhost:5173`

The YOLO weights (`model dan dataset/yolo v26.pt`) and `.env` are read from the host —
make sure the weights file exists locally before starting. SQLite data and generated
reports persist in `./data` on the host.
