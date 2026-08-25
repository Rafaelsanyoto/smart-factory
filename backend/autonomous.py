"""Autonomous Incident Handling — a background worker that vision-verifies each new
detection and closes the digital cycle without a human, when state.autonomous_mode is on.

Policy (locked in discussion): the agent may CONFIRM + escalate a real violation, but it
NEVER auto-dismisses. Anything it judges false or is unsure about is left PENDING with the
agent's opinion attached, for a human to review. Emergencies (Fire/Smoke) are confirmed &
escalated immediately without waiting on vision — too costly to delay."""
import json
import queue
import threading
import time

from .config import GEMINI_API_KEY, GEMINI_VISION_MODEL, EMERGENCY_CLASSES
from . import state
from .database import engine_lock, db_get_event, db_update_event

_queue = queue.Queue()


def enqueue(event):
    """Hand a freshly-created event to the autonomous worker (called from camera.ai_loop
    only when autonomous_mode is on)."""
    _queue.put(event["id"])


def _vision_verify(crop_jpeg, event):
    """Ask a multimodal Gemini whether the crop really shows the flagged condition.
    Returns (verdict, reason) where verdict is 'real' | 'false' | 'uncertain'."""
    if not GEMINI_API_KEY or not crop_jpeg:
        return "uncertain", "Verifikasi visual tidak tersedia (API key / gambar kosong) — perlu review manusia."

    from google import genai
    from google.genai import types

    cls = event["class"]
    zone = event["zone"]
    prompt = (
        "Kamu auditor keselamatan kerja (HSE) yang teliti. Gambar ini adalah frame kamera "
        f"dengan KOTAK berwarna menandai hasil deteksi otomatis berlabel '{cls}' di zona "
        f"'{zone}'. Fokuskan penilaian pada objek di dalam kotak. Tentukan apakah deteksi ini "
        "BENAR pelanggaran/kondisi nyata atau salah deteksi. "
        "Untuk kelas 'NO-*' artinya seseorang TIDAK memakai APD tersebut; 'Person' di zona "
        "terlarang berarti ada orang yang seharusnya tidak di sana; 'Fire'/'Smoke' berarti "
        "ada api/asap nyata. Jawab HANYA JSON: "
        '{"verdict": "real|false|uncertain", "reason": "penjelasan singkat 1 kalimat"}. '
        "Pakai 'uncertain' bila gambar tidak jelas."
    )
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=GEMINI_VISION_MODEL,
            contents=[
                types.Part.from_bytes(data=crop_jpeg, mime_type="image/jpeg"),
                types.Part(text=prompt),
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        data = json.loads((resp.text or "").strip())
        verdict = str(data.get("verdict", "uncertain")).lower()
        if verdict not in ("real", "false", "uncertain"):
            verdict = "uncertain"
        reason = str(data.get("reason", "")).strip() or "(tanpa alasan)"
        return verdict, reason
    except Exception as e:
        print(f"[AUTONOMOUS] vision verify error: {e}")
        return "uncertain", f"Verifikasi visual gagal ({e}) — perlu review manusia."


def _handle(event_id):
    # Re-check the toggle at processing time: if an admin turned autonomous mode off after
    # this was queued, leave the event for humans.
    if not state.autonomous_mode:
        return
    with engine_lock:
        event = db_get_event(event_id)
    if not event or event["status"] != "PENDING":
        return  # already handled (e.g. a human got to it first)

    is_emergency = event["class"] in EMERGENCY_CLASSES

    if is_emergency:
        verdict, reason = "real", "Kondisi darurat — dikonfirmasi & dieskalasi otomatis tanpa menunggu verifikasi visual."
    else:
        crop = state.event_crops.get(event_id)
        verdict, reason = _vision_verify(crop, event)

    now = time.strftime("%H:%M:%S")
    if verdict == "real":
        # CONFIRM authenticity only — do NOT mark it handled. A human still has to perform
        # and record the physical remediation; the reminder loop (followup.py) will nag by
        # urgency until they do (✅) or override this confirmation (❌ = feedback).
        with engine_lock:
            db_update_event(
                event_id,
                status="CONFIRMED",
                verified_at=now,
                verified_by="agent",
                agent_verdict="real",
                agent_reasoning=reason,
            )
        print(f"[AUTONOMOUS] #{event.get('seq','?')} CONFIRMED by agent (menunggu tindakan manusia) — {reason}")
    else:
        # Never auto-dismiss: keep PENDING, just attach the agent's opinion for the human.
        with engine_lock:
            db_update_event(
                event_id,
                verified_by="agent",
                agent_verdict=verdict,
                agent_reasoning=reason,
            )
        print(f"[AUTONOMOUS] #{event.get('seq','?')} left for human ({verdict}) — {reason}")


def _worker():
    while True:
        event_id = _queue.get()
        try:
            _handle(event_id)
        except Exception as e:
            print(f"[AUTONOMOUS] worker error: {e}")
        finally:
            _queue.task_done()
        time.sleep(0.2)  # gentle pacing so a burst can't hammer the vision quota


_worker_thread = threading.Thread(target=_worker, daemon=True)
_worker_thread.start()
