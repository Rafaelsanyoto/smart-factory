"""Entry point — backend lives in the `backend/` package (see backend/app.py)."""
from backend.app import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
