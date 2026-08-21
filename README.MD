# Smart Factory HSE Command Dashboard

Autonomous Safety Surveillance & Incident Workflow system featuring real-time YOLO-based violation detection, a FastAPI backend, and a React (Vite/Tailwind) frontend.

---

## Prerequisites

Make sure you have the following installed on your local machine:
- **Python** (v3.10 or higher)
- **Node.js** (v18 or higher) & npm

---

# --- TERMINAL 1: Backend ---
git clone https://github.com/Rafaelsanyoto/smart-factory.git
cd smart-factory
python -m venv venv
venv\Scripts\activate
pip install fastapi uvicorn ultralytics opencv-python numpy
python api.py

# --- TERMINAL 2: Frontend ---
cd frontend
npm install
npm run dev

Username: admin
Password: admin
