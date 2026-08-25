import json
import queue
import re
import threading
import time

from .config import GEMINI_API_KEY, GEMINI_VISION_MODEL, GEMINI_VISION_MODEL_FALLBACK, EMERGENCY_CLASSES
from . import state
from .database import engine_lock, db_get_event, db_update_event
from .notifications import notify_ai_confirmed

_queue = queue.Queue()

# 429/503/504 are transient -> retry, then fall back to a second model
RETRYABLE_CODES = (429, 503, 504)
TIMEOUT_MS = 15_000
MAX_ATTEMPTS_PER_MODEL = 2
BASE_BACKOFF_SECONDS = 4


def enqueue(event):
    _queue.put(event["id"])


def _retry_delay_hint(exc):
    # honor Google's suggested retryDelay if present, else use our own backoff
    match = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(exc))
    return float(match.group(1)) if match else None


def _call_gemini(model, crop_jpeg, prompt):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    resp = client.models.generate_content(
        model=model,
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


def _vision_verify(crop_jpeg, event):
    if not GEMINI_API_KEY or not crop_jpeg:
        return "uncertain", "Verifikasi visual tidak tersedia (API key / gambar kosong) — perlu review manusia."

    from google.genai import errors as genai_errors

    cls = event["class"]
    prompt = (
        "Kamu pemeriksa visual otomatis untuk sistem keselamatan kerja. Gambar ini adalah "
        f"frame kamera dengan KOTAK berwarna menandai hasil deteksi otomatis berlabel '{cls}'. "
        "Tugasmu HANYA satu: pastikan objek DI DALAM KOTAK itu secara visual benar-benar "
        f"menunjukkan '{cls}'. JANGAN menilai lokasi, konteks, apakah orang itu seharusnya ada "
        "di situ, atau apa pun di luar kotak — zona ini sudah dikonfigurasi untuk memantau "
        "kelas ini, jadi konteks/lokasinya sudah pasti benar, abaikan sepenuhnya.\n"
        "Panduan per kelas: 'NO-Hardhat'/'NO-Mask'/'NO-Safety Vest' = pastikan orang di kotak "
        "BENAR TIDAK memakai APD tersebut. 'Person' = pastikan memang ada orang di kotak. "
        "'Fire'/'Smoke' = pastikan memang ada api/asap di kotak.\n"
        'Jawab HANYA JSON: {"verdict": "real|false|uncertain", "reason": "1 kalimat singkat"}. '
        "'real' = visual jelas cocok label. 'false' = visual jelas TIDAK cocok (salah deteksi, "
        "atau orang justru memakai APD-nya). 'uncertain' HANYA jika gambar buram/kotak kosong/ "
        "objek tak terlihat jelas — bukan karena ragu soal lokasi atau konteks."
    )

    models = [m for m in (GEMINI_VISION_MODEL, GEMINI_VISION_MODEL_FALLBACK) if m]
    last_transient_error = None

    for model_idx, model in enumerate(models):
        for attempt in range(1, MAX_ATTEMPTS_PER_MODEL + 1):
            try:
                return _call_gemini(model, crop_jpeg, prompt)
            except (genai_errors.ClientError, genai_errors.ServerError) as e:
                code = getattr(e, "code", None)
                if code not in RETRYABLE_CODES:
                    print(f"[AUTONOMOUS] vision verify error ({model}, non-retryable {code}): {e.message if hasattr(e, 'message') else e}")
                    return "uncertain", f"Verifikasi visual gagal ({code or 'error'}) — perlu review manusia."
                last_transient_error = e
                delay = _retry_delay_hint(e) or (BASE_BACKOFF_SECONDS * attempt)
                print(f"[AUTONOMOUS] {model} busy (HTTP {code}), retry {attempt}/{MAX_ATTEMPTS_PER_MODEL} in {delay:.0f}s")
                time.sleep(delay)
            except Exception as e:
                # local timeout, not a genai ServerError -- still transient
                if "timed out" in str(e).lower() or "timeout" in type(e).__name__.lower():
                    last_transient_error = e
                    print(f"[AUTONOMOUS] {model} timed out locally, retry {attempt}/{MAX_ATTEMPTS_PER_MODEL}")
                    continue
                print(f"[AUTONOMOUS] vision verify error ({model}): {e}")
                return "uncertain", f"Verifikasi visual gagal ({e}) — perlu review manusia."
        if model_idx < len(models) - 1:
            print(f"[AUTONOMOUS] {model} still busy after {MAX_ATTEMPTS_PER_MODEL} tries — falling back to {models[model_idx + 1]}")

    code = getattr(last_transient_error, "code", "error")
    return "uncertain", f"Server AI sedang sibuk (HTTP {code}) setelah beberapa kali dicoba — perlu review manusia."


def _handle(event_id):
    if not state.autonomous_mode:
        return
    with engine_lock:
        event = db_get_event(event_id)
    if not event or event["status"] != "PENDING":
        return

    is_emergency = event["class"] in EMERGENCY_CLASSES

    if is_emergency:
        verdict, reason = "real", "Kondisi darurat — dikonfirmasi & dieskalasi otomatis tanpa menunggu verifikasi visual."
    else:
        crop = state.event_crops.get(event_id)
        verdict, reason = _vision_verify(crop, event)

    now = time.strftime("%H:%M:%S")
    if verdict == "real":
        # confirm authenticity only, human still records the actual remediation
        with engine_lock:
            updated = db_update_event(
                event_id,
                status="CONFIRMED",
                verified_at=now,
                verified_by="agent",
                agent_verdict="real",
                agent_reasoning=reason,
            )
        mention = state.responsible_mention_for(event["stream_id"])
        notify_ai_confirmed(updated, mention)
        print(f"[AUTONOMOUS] #{event.get('seq','?')} CONFIRMED by agent (menunggu tindakan manusia) — {reason}")
    else:
        # never auto-dismiss, just attach opinion for a human to review
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
        time.sleep(0.2)


_worker_thread = threading.Thread(target=_worker, daemon=True)
_worker_thread.start()
