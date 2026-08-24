"""AI Agent — conversational assistant with Gemini function calling. READ tools always run
inline (safe). ACTION tools are gated by the permission mode: in 'standard' they're returned
to the UI as a pending action a human confirms; in 'accept_low_risk' the low-risk ones run
inline; in 'auto' everything runs inline. Chat history is persisted per session so it
survives restarts and gives the Discord bot real multi-turn memory."""
import time

from .config import GEMINI_API_KEY, GEMINI_MODEL
from .database import (
    engine_lock, db_conn, _event_row_to_dict, db_get_notifications,
    db_insert_message, db_get_session, db_touch_session, db_get_messages,
)
from . import state
from . import actions
from .notifications import dispatch_message


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def _agent_get_events(zone="", violation_class="", event_type="", since_minutes=0, status=""):
    query = "SELECT * FROM events WHERE 1=1"
    params = []
    if zone:
        z = f"%{str(zone).lower()}%"
        query += " AND (LOWER(zone) LIKE ? OR LOWER(stream_id) LIKE ?)"
        params += [z, z]
    if violation_class:
        query += " AND LOWER(class) LIKE ?"
        params.append(f"%{str(violation_class).lower()}%")
    if event_type:
        query += " AND type = ?"
        params.append(str(event_type).upper())
    if status:
        query += " AND status = ?"
        params.append(str(status).upper())
    try:
        since_minutes = int(since_minutes or 0)
    except (TypeError, ValueError):
        since_minutes = 0
    if since_minutes > 0:
        query += " AND ts_ms >= ?"
        params.append(time.time() * 1000 - since_minutes * 60_000)
    query += " ORDER BY ts_ms DESC LIMIT 50"

    with engine_lock:
        rows = db_conn.execute(query, params).fetchall()
    result = [_event_row_to_dict(r) for r in rows]
    return {"count": len(result), "events": result}


def _agent_get_notifications():
    with engine_lock:
        result = db_get_notifications(limit=50)
    return {"count": len(result), "notifications": result}


def _agent_get_zone_config():
    return actions.zones_payload()


def _agent_get_stream_status():
    return actions.sources_payload()


def _agent_get_system_config():
    return {
        "active_model": state.active_model_id,
        "confidence": state.active_confidence,
        "context_visible": dict(state.context_visibility),
    }


def _agent_generate_report(since_hours=24, zone=""):
    """Aggregated stats over a time window — richer material for the agent to write a
    coherent narrative report from, instead of just a flat list of raw events."""
    try:
        since_hours = float(since_hours or 24)
    except (TypeError, ValueError):
        since_hours = 24
    cutoff = time.time() * 1000 - since_hours * 3_600_000

    query = "SELECT * FROM events WHERE ts_ms >= ?"
    params = [cutoff]
    if zone:
        z = f"%{str(zone).lower()}%"
        query += " AND (LOWER(zone) LIKE ? OR LOWER(stream_id) LIKE ?)"
        params += [z, z]
    query += " ORDER BY ts_ms ASC"

    with engine_lock:
        rows = db_conn.execute(query, params).fetchall()
    events_in_range = [_event_row_to_dict(r) for r in rows]

    by_status, by_class, by_zone = {}, {}, {}
    unresolved = []
    emergency_count = 0

    for e in events_in_range:
        by_status[e["status"]] = by_status.get(e["status"], 0) + 1
        by_class[e["class"]] = by_class.get(e["class"], 0) + 1
        by_zone[e["zone"]] = by_zone.get(e["zone"], 0) + 1
        if e["type"] == "EMERGENCY":
            emergency_count += 1
        if e["status"] == "CONFIRMED" and not e["action_taken"]:
            unresolved.append({"seq": e["seq"], "class": e["class"], "zone": e["zone"], "timestamp": e["timestamp"]})

    return {
        "period_hours": since_hours,
        "total_events": len(events_in_range),
        "by_status": by_status,
        "by_class": by_class,
        "by_zone": by_zone,
        "emergency_count": emergency_count,
        "unresolved_confirmed_incidents": unresolved,
    }


def _agent_send_alert(text):
    sent, channel = dispatch_message(str(text))
    if sent:
        return {"status": "success", "sent": True, "channel": channel, "message": f"Terkirim ke {channel}."}
    return {
        "status": "error",
        "sent": False,
        "message": "Gagal kirim — belum ada channel notifikasi yang aktif (isi DISCORD_WEBHOOK_URL di .env).",
    }


READ_TOOLS = {
    "get_events": _agent_get_events,
    "get_notifications": _agent_get_notifications,
    "get_zone_config": _agent_get_zone_config,
    "get_stream_status": _agent_get_stream_status,
    "get_system_config": _agent_get_system_config,
    "generate_report": lambda since_hours=24, zone="": _agent_generate_report(since_hours, zone),
}

ACTION_TOOLS = {
    "send_alert_message": lambda text: _agent_send_alert(text),
    "set_zone_rules": lambda stream_id, required=None, emergency=None: actions.apply_zone_rules(stream_id, required, emergency),
    "set_confidence": lambda confidence: actions.apply_confidence(confidence),
    "set_stream_paused": lambda stream_id, paused: actions.apply_pause(stream_id, paused),
    "select_model": lambda model_id: actions.apply_model(model_id),
    "set_context_visibility": lambda class_name, visible: actions.apply_context_visibility(class_name, visible),
    "set_agent_permission_mode": lambda mode: actions.apply_permission_mode(mode),
}

# Risk tier per action tool, used by the permission-mode auto-run decision below.
# "low": can't affect what gets detected as a violation/emergency — safe to auto-run.
# "high": changes actual detection behavior (what's required, how sensitive, whether a
# camera is even running) — a misinterpreted command here could mean a real violation or
# emergency goes undetected, so it stays gated behind confirmation unless the operator
# has explicitly opted into Full Auto.
ACTION_RISK = {
    "send_alert_message": "low",
    "set_context_visibility": "low",
    "set_zone_rules": "high",
    "set_confidence": "high",
    "set_stream_paused": "high",
    "select_model": "high",
    # High even though it's "just" a settings toggle — changing this decides how
    # autonomous FUTURE actions become, so it defaults to needing confirmation too.
    # Only auto-runs itself once already in "auto" mode.
    "set_agent_permission_mode": "high",
}


def _action_auto_runs(tool_name):
    """Whether the current permission mode allows this action tool to execute without
    a human confirm click."""
    if state.agent_permission_mode == "auto":
        return True
    if state.agent_permission_mode == "accept_low_risk":
        return ACTION_RISK.get(tool_name, "high") == "low"
    return False


AGENT_FUNCTION_DECLARATIONS = [
    {
        "name": "get_events",
        "description": (
            "Ambil daftar event pelanggaran APD / darurat yang tercatat sistem. Tiap event punya "
            "'seq' (nomor insiden referensi, mis. #7), status siklus penuh (PENDING/CONFIRMED/"
            "DISMISSED/DELETED), dan detail tindakan/penghapusan jika ada (action_taken, "
            "action_note, action_at, deleted, delete_reason, deleted_at). Bisa difilter."
        ),
        "parameters": {"type": "OBJECT", "properties": {
            "zone": {"type": "STRING", "description": "Filter nama zona atau stream_id, mis. 'Welding' atau 'stream_02'. Kosongkan untuk semua."},
            "violation_class": {"type": "STRING", "description": "Filter kelas, mis. 'NO-Mask', 'Fire'. Kosongkan untuk semua."},
            "event_type": {"type": "STRING", "description": "'VIOLATION' atau 'EMERGENCY'. Kosongkan untuk semua."},
            "since_minutes": {"type": "INTEGER", "description": "Hanya event dalam N menit terakhir. 0 = semua."},
            "status": {"type": "STRING", "description": "'PENDING' (belum ditinjau admin), 'CONFIRMED' (sudah dikonfirmasi asli), 'DISMISSED' (dianggap salah deteksi saat review), atau 'DELETED' (dihapus admin, biasanya duplikat). Kosongkan untuk semua."},
        }},
    },
    {"name": "get_notifications", "description": "Ambil log aktivitas notifikasi yang sudah dikirim AI Agent.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "get_zone_config", "description": "Ambil konfigurasi aturan tiap zona: PPE wajib dan kelas darurat yang aktif.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "get_stream_status", "description": "Ambil status tiap stream/kamera: sumber (video/webcam) dan apakah sedang di-pause.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "get_system_config", "description": "Ambil konfigurasi sistem: model deteksi aktif, confidence threshold, visibilitas kelas konteks.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {
        "name": "generate_report",
        "description": (
            "Ambil statistik teragregasi insiden dalam rentang waktu tertentu — total per status, "
            "per kelas pelanggaran, per zona, jumlah darurat, dan daftar insiden CONFIRMED yang "
            "BELUM ditindak. Pakai ini (bukan get_events) kalau diminta membuat laporan/ringkasan, "
            "lalu susun jadi narasi yang jelas berdasarkan angka-angka ini — jangan mengarang."
        ),
        "parameters": {"type": "OBJECT", "properties": {
            "since_hours": {"type": "NUMBER", "description": "Rentang waktu dalam jam, mis. 24 untuk 'hari ini', 168 untuk 'minggu ini'. Default 24."},
            "zone": {"type": "STRING", "description": "Filter ke satu zona/stream tertentu. Kosongkan untuk semua zona."},
        }},
    },
    {
        "name": "send_alert_message",
        "description": "Kirim pesan/laporan ke channel safety Discord. Susun teksnya sendiri berdasarkan data.",
        "parameters": {"type": "OBJECT", "properties": {
            "text": {"type": "STRING", "description": "Isi pesan yang akan dikirim."},
        }, "required": ["text"]},
    },
    {
        "name": "set_zone_rules",
        "description": "Ubah aturan sebuah zona. stream_01=Assembly Line A, stream_02=Welding Bay B.",
        "parameters": {"type": "OBJECT", "properties": {
            "stream_id": {"type": "STRING", "description": "'stream_01' atau 'stream_02'."},
            "required": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Daftar PPE wajib: Hardhat, Mask, Safety Vest. Hilangkan bila tak diubah."},
            "emergency": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Daftar kelas darurat aktif: Fire, Smoke. Hilangkan bila tak diubah."},
        }, "required": ["stream_id"]},
    },
    {
        "name": "set_confidence",
        "description": "Ubah confidence threshold deteksi (0.1 - 0.95).",
        "parameters": {"type": "OBJECT", "properties": {
            "confidence": {"type": "NUMBER", "description": "Nilai 0.1 sampai 0.95, mis. 0.7 untuk 70%."},
        }, "required": ["confidence"]},
    },
    {
        "name": "set_stream_paused",
        "description": "Pause atau resume sebuah stream/kamera.",
        "parameters": {"type": "OBJECT", "properties": {
            "stream_id": {"type": "STRING", "description": "'stream_01' atau 'stream_02'."},
            "paused": {"type": "BOOLEAN", "description": "true = pause, false = resume."},
        }, "required": ["stream_id", "paused"]},
    },
    {
        "name": "select_model",
        "description": "Ganti model deteksi YOLO.",
        "parameters": {"type": "OBJECT", "properties": {
            "model_id": {"type": "STRING", "description": "'yolov11m' atau 'yolo26m'."},
        }, "required": ["model_id"]},
    },
    {
        "name": "set_context_visibility",
        "description": "Tampilkan/sembunyikan kelas konteks di overlay: Person, Safety Cone, machinery, vehicle.",
        "parameters": {"type": "OBJECT", "properties": {
            "class_name": {"type": "STRING", "description": "Person, Safety Cone, machinery, atau vehicle."},
            "visible": {"type": "BOOLEAN", "description": "true = tampilkan, false = sembunyikan."},
        }, "required": ["class_name", "visible"]},
    },
    {
        "name": "set_agent_permission_mode",
        "description": (
            "Ubah mode izin agent ini sendiri: seberapa otonom aksi-aksi (bukan tools baca) boleh "
            "berjalan tanpa klik konfirmasi manusia."
        ),
        "parameters": {"type": "OBJECT", "properties": {
            "mode": {"type": "STRING", "description": (
                "'standard' = semua aksi selalu minta konfirmasi (default paling aman). "
                "'accept_low_risk' = aksi aman (kirim pesan, toggle tampilan) langsung jalan, "
                "aksi yang mempengaruhi deteksi (aturan zona, confidence, pause, ganti model) "
                "tetap minta konfirmasi. 'auto' = semua aksi langsung jalan tanpa konfirmasi."
            )},
        }, "required": ["mode"]},
    },
]

AGENT_SYSTEM_PROMPT = (
    "Kamu adalah AI Agent asisten keselamatan kerja (HSE) untuk dashboard Smart Factory. "
    "Jawab dalam Bahasa Indonesia, ringkas dan profesional. "
    "Selalu gunakan tools untuk mengambil data nyata sebelum menjawab pertanyaan tentang kondisi/insiden — "
    "jangan mengarang angka. "
    "Untuk permintaan yang mengubah sistem atau mengirim pesan, panggil function aksi yang sesuai satu kali; "
    "sistem akan meminta konfirmasi manusia sebelum benar-benar menjalankannya, jadi kamu tidak perlu meminta izin lagi. "
    "Konteks: stream_01 = Assembly Line A, stream_02 = Welding Bay B. "
    "Kelas pelanggaran APD: NO-Hardhat, NO-Mask, NO-Safety Vest. Kelas darurat: Fire, Smoke. "
    "Setiap insiden punya nomor referensi 'seq' (mis. #7) yang tetap sama sepanjang siklus "
    "hidupnya — selalu sebutkan nomor ini saat membahas insiden tertentu, jangan pakai UUID panjang. "
    "Siklus status penuh: PENDING (baru terdeteksi, belum ditinjau admin) -> CONFIRMED (admin "
    "memastikan ini pelanggaran asli) atau DISMISSED (admin menandai ini salah deteksi) -> jika "
    "CONFIRMED, admin bisa mencatat tindakan (action_taken=true, action_note berisi tindakan yang "
    "diambil, action_at waktunya) ATAU menghapusnya sebagai duplikat (status jadi DELETED, "
    "delete_reason berisi alasan, deleted_at waktunya) — satu insiden selalu berakhir dengan tepat "
    "satu hasil akhir: tindakan nyata ATAU dihapus sebagai duplikat, tidak keduanya. Kalau ditanya "
    "status suatu insiden atau tindakan apa yang diambil, gunakan get_events dan baca field "
    "status/action_taken/action_note/action_at/deleted/delete_reason — jangan mengarang. "
    "Kalau diminta membuat laporan/ringkasan/rekap keselamatan untuk suatu periode (hari ini, "
    "minggu ini, dst), pakai generate_report (bukan get_events) lalu susun jadi laporan naratif "
    "yang jelas: total insiden, tren per kelas/zona, jumlah darurat, dan soroti insiden CONFIRMED "
    "yang belum ditindak sebagai perhatian utama."
)


def describe_action(name, args):
    if name == "send_alert_message":
        return f'Kirim pesan ke channel safety:\n"{args.get("text", "")}"'
    if name == "set_zone_rules":
        parts = []
        if args.get("required") is not None:
            parts.append(f"PPE wajib = {args.get('required')}")
        if args.get("emergency") is not None:
            parts.append(f"deteksi darurat = {args.get('emergency')}")
        return f"Ubah aturan zona {args.get('stream_id')}: " + (", ".join(parts) if parts else "(tidak ada perubahan)")
    if name == "set_confidence":
        try:
            pct = round(float(args.get("confidence", 0)) * 100)
        except (TypeError, ValueError):
            pct = args.get("confidence")
        return f"Ubah confidence threshold ke {pct}%"
    if name == "set_stream_paused":
        return f"{'Pause' if args.get('paused') else 'Resume'} stream {args.get('stream_id')}"
    if name == "select_model":
        return f"Ganti model deteksi ke {args.get('model_id')}"
    if name == "set_context_visibility":
        return f"{'Tampilkan' if args.get('visible') else 'Sembunyikan'} kelas '{args.get('class_name')}' di layar"
    if name == "set_agent_permission_mode":
        labels = {"standard": "Standard (selalu konfirmasi)", "accept_low_risk": "Accept Low-Risk (aksi aman otomatis)", "auto": "Full Auto (semua otomatis)"}
        return f"Ubah mode izin AI Agent ke: {labels.get(args.get('mode'), args.get('mode'))}"
    return name


def _summarize_tool_result(name, result):
    """Short human-readable summary of a read-tool's result, shown live in the UI —
    not the raw JSON, just enough to say what the agent found."""
    try:
        if name == "get_events":
            return f"{result['count']} event ditemukan"
        if name == "get_notifications":
            return f"{result['count']} notifikasi ditemukan"
        if name == "get_zone_config":
            return f"{len(result['zones'])} zona dimuat"
        if name == "get_stream_status":
            return f"status {len(result.get('current', {}))} stream dimuat"
        if name == "get_system_config":
            return f"model aktif: {result.get('active_model')}, confidence: {result.get('confidence')}"
        if name == "generate_report":
            return f"{result['total_events']} insiden dalam {result['period_hours']} jam terakhir, {len(result['unresolved_confirmed_incidents'])} belum ditindak"
    except Exception:
        pass
    return "selesai"


TOOL_LABELS = {
    "get_events": "Mengambil data event pelanggaran/darurat",
    "get_notifications": "Mengambil log notifikasi",
    "get_zone_config": "Mengambil konfigurasi zona",
    "generate_report": "Menyusun statistik laporan",
    "get_stream_status": "Mengecek status stream/kamera",
    "get_system_config": "Mengecek konfigurasi sistem",
}


def run_agent_chat_steps(history):
    """Generator: yields step dicts live as the agent reasons/calls tools, ending with
    a 'final' (or 'action_proposed'/'error'/'not_configured') step. Shared by both the
    streaming endpoint (yields each step to the UI) and the plain endpoint (drains this
    generator and returns only the last step, for simple non-streaming callers)."""
    if not GEMINI_API_KEY:
        yield {
            "step": "not_configured",
            "configured": False,
            "reply": "AI Agent belum aktif. Isi GEMINI_API_KEY di file .env untuk mengaktifkan chat.",
            "pending_action": None,
        }
        return

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    tool = types.Tool(function_declarations=AGENT_FUNCTION_DECLARATIONS)
    config = types.GenerateContentConfig(
        system_instruction=AGENT_SYSTEM_PROMPT,
        tools=[tool],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    contents = []
    for m in history:
        role = "user" if m.get("role") == "user" else "model"
        text = m.get("text", "")
        if text:
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))

    try:
        for round_num in range(6):  # bounded tool-calling loop
            yield {"step": "thinking", "round": round_num + 1}
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=contents, config=config)
            calls = list(resp.function_calls or [])

            if not calls:
                yield {"step": "final", "configured": True, "reply": (resp.text or "").strip(), "pending_action": None}
                return

            # If any action call in this round still needs a human click under the
            # current permission mode, stop and propose it — don't partially execute
            # some calls while asking about another in the same round.
            needs_confirm = next(
                (c for c in calls if c.name in ACTION_TOOLS and not _action_auto_runs(c.name)), None,
            )
            if needs_confirm is not None:
                args = dict(needs_confirm.args or {})
                yield {
                    "step": "action_proposed",
                    "configured": True,
                    "reply": (resp.text or "").strip(),
                    "pending_action": {
                        "tool": needs_confirm.name,
                        "args": args,
                        "description": describe_action(needs_confirm.name, args),
                        "state": "awaiting",
                    },
                }
                return

            # Every call this round is either a read tool, or an action tool the current
            # permission mode allows to run without confirmation — execute inline and
            # feed the results back so Gemini can produce a final reply referencing them.
            contents.append(resp.candidates[0].content)
            parts = []
            for c in calls:
                args = dict(c.args or {})
                if c.name in ACTION_TOOLS:
                    yield {"step": "action_call", "name": c.name, "label": describe_action(c.name, args), "args": args}
                    result = ACTION_TOOLS[c.name](**args)
                    yield {"step": "action_result", "name": c.name, "summary": result.get("message") or "Aksi dijalankan otomatis."}
                else:
                    yield {"step": "tool_call", "name": c.name, "label": TOOL_LABELS.get(c.name, c.name), "args": args}
                    fn = READ_TOOLS.get(c.name)
                    result = fn(**args) if fn else {"error": "unknown tool"}
                    yield {"step": "tool_result", "name": c.name, "summary": _summarize_tool_result(c.name, result)}
                parts.append(types.Part.from_function_response(name=c.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=parts))
            continue

        yield {
            "step": "final",
            "configured": True,
            "reply": "Maaf, langkahnya terlalu panjang. Coba pertanyaan yang lebih spesifik.",
            "pending_action": None,
        }
    except Exception as e:
        print(f"[AI AGENT] chat error: {e}")
        yield {
            "step": "error",
            "configured": True,
            "reply": f"Terjadi kendala saat memproses permintaan: {e}",
            "pending_action": None,
            "error": True,
        }


def run_agent_chat_session(session_id, user_text):
    """Wraps run_agent_chat_steps with DB persistence: saves the incoming user message,
    loads the FULL session history from the DB (source of truth, not client-supplied) to
    build Gemini's context, runs the normal tool-calling loop, then saves the agent's
    final reply — together with its full step trail — back to the session. Yields the
    same step stream as run_agent_chat_steps, so both streaming and non-streaming callers
    (dashboard UI, plain HTTP, Discord bot) work exactly as before at the call site."""
    with engine_lock:
        db_insert_message(session_id, "user", user_text)
        session = db_get_session(session_id)
        if session and session["title"] == "Percakapan baru":
            db_touch_session(session_id, title=user_text[:48])
        else:
            db_touch_session(session_id)
        messages = db_get_messages(session_id)

    history = [{"role": m["role"], "text": m["text"]} for m in messages if m["text"]]

    collected_steps = []
    final_step = None
    for step in run_agent_chat_steps(history):
        if step["step"] in ("thinking", "tool_call", "tool_result", "action_call", "action_result"):
            collected_steps.append(step)
        else:
            final_step = step
        yield step

    if final_step:
        with engine_lock:
            db_insert_message(
                session_id, "agent", final_step.get("reply", ""),
                steps=collected_steps, pending_action=final_step.get("pending_action"),
            )


def run_agent_chat_session_final(session_id, user_text):
    """Drains the step generator, returns only the final step (+ session_id). Used by
    the plain HTTP endpoint and the Discord bot — both just want a one-shot answer."""
    last = None
    for step in run_agent_chat_session(session_id, user_text):
        last = step
    result = last or {"configured": False, "reply": "", "pending_action": None}
    result["session_id"] = session_id
    return result
