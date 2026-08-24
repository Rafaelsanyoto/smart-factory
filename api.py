"""Entry point. The backend now lives in the `backend/` package (see backend/app.py for
how the app is assembled). This thin launcher keeps the familiar `python api.py` command
working — importing backend.app builds the app and starts the camera threads."""
from backend.app import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
