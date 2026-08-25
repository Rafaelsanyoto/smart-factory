import threading
import time

from .config import GEMINI_API_KEY, GEMINI_MODEL, MODEL_LABEL
from .database import (
    engine_lock, db_conn, _event_row_to_dict, db_get_notifications, db_update_event,
    db_insert_message, db_get_session, db_touch_session, db_get_messages,
    db_get_message, db_update_message_pending_action,
)
from . import state
from . import actions
from . import followup
from . import reports
from .notifications import dispatch_message

REPORT_URL_BASE = "http://127.0.0.1:8000/api/reports/file"

_turn = threading.local()


def _turn_report_files():
    if not hasattr(_turn, "files"):
        _turn.files = []
    return _turn.files


def _agent_get_events(violation_class="", event_type="", status=""):
    query = "SELECT * FROM events WHERE 1=1"
    params = []
    if violation_class:
        query += " AND LOWER(class) LIKE ?"
        params.append(f"%{str(violation_class).lower()}%")
    if event_type:
        query += " AND type = ?"
        params.append(str(event_type).upper())
    if status:
        query += " AND status = ?"
        params.append(str(status).upper())
    query += " ORDER BY ts_ms DESC LIMIT 50"

    with engine_lock:
        rows = db_conn.execute(query, params).fetchall()
    result = [_event_row_to_dict(r) for r in rows]
    return {"count": len(result), "events": result}


def _agent_get_notifications():
    with engine_lock:
        result = db_get_notifications(limit=50)
    return {"count": len(result), "notifications": result}


def _agent_get_class_rules():
    return actions.class_rules_payload()


def _agent_get_system_config():
    return {"active_model": MODEL_LABEL, "confidence": state.active_confidence}


def _find_event_by_seq(seq):
    try:
        seq = int(seq)
    except (TypeError, ValueError):
        return None
    with engine_lock:
        row = db_conn.execute("SELECT * FROM events WHERE seq = ?", (seq,)).fetchone()
    return _event_row_to_dict(row) if row else None


def _agent_verify_incident(seq, status):
    status = str(status).upper()
    if status not in ("CONFIRMED", "DISMISSED"):
        return {"status": "error", "message": "status harus CONFIRMED atau DISMISSED"}
    ev = _find_event_by_seq(seq)
    if not ev:
        return {"status": "error", "message": f"insiden #{seq} tidak ditemukan"}
    if status == "DISMISSED":
        updated = followup.dismiss_event(ev["id"])
    else:
        with engine_lock:
            updated = db_update_event(ev["id"], status="CONFIRMED", verified_at=time.strftime("%H:%M:%S"))
    return {"status": "success", "message": f"Insiden #{seq} ditandai {status}.", "event": updated}


def _agent_record_action(seq, note):
    note = str(note).strip()
    if not note:
        return {"status": "error", "message": "catatan tindakan tidak boleh kosong"}
    ev = _find_event_by_seq(seq)
    if not ev:
        return {"status": "error", "message": f"insiden #{seq} tidak ditemukan"}
    if ev["status"] != "CONFIRMED":
        return {"status": "error", "message": f"hanya insiden CONFIRMED yang bisa dicatat tindakannya (#{seq} berstatus {ev['status']})"}
    updated = followup.mark_acted(ev["id"], note)
    return {"status": "success", "message": f"Tindakan untuk insiden #{seq} dicatat.", "event": updated}


def _agent_export_report(file_format="pdf"):
    res = reports.generate_report_file(file_format)
    if res.get("status") == "success":
        url = f"{REPORT_URL_BASE}/{res['filename']}"
        res["download_url"] = url
        _turn_report_files().append({
            "filename": res["filename"], "path": res["path"],
            "download_url": url, "format": res["format"],
        })
        res["message"] = f"Laporan {res['format'].upper()} siap ({res['total']} insiden). Unduh: {url}"
    return res


def _apply_class_rules_from_updates(updates):
    classes = {}
    for u in (updates or []):
        name = u.get("class_name")
        if not name:
            continue
        classes[name] = {k: v for k, v in u.items() if k != "class_name"}
    return actions.apply_class_rules(classes)


def _agent_generate_report():
    with engine_lock:
        rows = db_conn.execute("SELECT * FROM events ORDER BY ts_ms ASC").fetchall()
    events_all = [_event_row_to_dict(r) for r in rows]

    by_status, by_class = {}, {}
    unresolved = []
    emergency_count = 0
    for e in events_all:
        by_status[e["status"]] = by_status.get(e["status"], 0) + 1
        by_class[e["class"]] = by_class.get(e["class"], 0) + 1
        if e["type"] == "EMERGENCY":
            emergency_count += 1
        if e["status"] == "CONFIRMED" and not e["action_taken"]:
            unresolved.append({"seq": e["seq"], "class": e["class"], "timestamp": e["timestamp"]})

    return {
        "total_events": len(events_all),
        "by_status": by_status,
        "by_class": by_class,
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
    "get_events": lambda violation_class="", event_type="", status="": _agent_get_events(violation_class, event_type, status),
    "get_notifications": lambda: _agent_get_notifications(),
    "get_class_rules": lambda: _agent_get_class_rules(),
    "get_system_config": lambda: _agent_get_system_config(),
    "generate_report": lambda: _agent_generate_report(),
    "export_report": lambda file_format="pdf": _agent_export_report(file_format),
}

ACTION_TOOLS = {
    "send_alert_message": lambda text: _agent_send_alert(text),
    "set_class_rules": lambda updates: _apply_class_rules_from_updates(updates),
    "set_confidence": lambda confidence: actions.apply_confidence(confidence),
    "verify_incident": lambda seq, status: _agent_verify_incident(seq, status),
    "record_action": lambda seq, note: _agent_record_action(seq, note),
}


AGENT_FUNCTION_DECLARATIONS = [
    {
        "name": "get_events",
        "description": (
            "Ambil hasil deteksi (insiden) yang tercatat dari proses deteksi yang sudah dijalankan. "
            "Tiap insiden punya 'seq' (nomor referensi, mis. #7) dan status siklus penuh "
            "(PENDING/CONFIRMED/DISMISSED/DELETED)."
        ),
        "parameters": {"type": "OBJECT", "properties": {
            "violation_class": {"type": "STRING", "description": "Filter kelas, mis. 'NO-Mask', 'Fire'. Kosongkan untuk semua."},
            "event_type": {"type": "STRING", "description": "'VIOLATION' atau 'EMERGENCY'. Kosongkan untuk semua."},
            "status": {"type": "STRING", "description": "'PENDING', 'CONFIRMED', 'DISMISSED', atau 'DELETED'. Kosongkan untuk semua."},
        }},
    },
    {"name": "get_notifications", "description": "Ambil log notifikasi yang sudah dikirim untuk hasil deteksi.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "get_class_rules", "description": "Ambil kelas apa saja yang dimonitor (memicu insiden) dan urgensinya.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "get_system_config", "description": "Ambil konfigurasi sistem: model deteksi aktif dan confidence threshold.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {
        "name": "generate_report",
        "description": (
            "Ambil statistik teragregasi dari seluruh hasil proses deteksi yang tercatat sejauh ini — "
            "total per status, per kelas pelanggaran, jumlah darurat, dan insiden CONFIRMED yang belum "
            "ditindak. Pakai ini (bukan get_events) untuk membuat ringkasan/laporan naratif."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "export_report",
        "description": "Buat FILE laporan (PDF/Excel/CSV) berisi seluruh hasil deteksi yang tercatat, siap diunduh.",
        "parameters": {"type": "OBJECT", "properties": {
            "file_format": {"type": "STRING", "description": "'pdf', 'xlsx' (Excel), atau 'csv'. Default 'pdf'."},
        }},
    },
    {
        "name": "send_alert_message",
        "description": "Kirim pesan ke channel safety Discord. Susun teksnya sendiri berdasarkan data.",
        "parameters": {"type": "OBJECT", "properties": {
            "text": {"type": "STRING", "description": "Isi pesan yang akan dikirim."},
        }, "required": ["text"]},
    },
    {
        "name": "set_class_rules",
        "description": "Atur kelas mana yang dimonitor (memicu insiden), urgensinya, dan apakah ditampilkan di gambar hasil.",
        "parameters": {"type": "OBJECT", "properties": {
            "updates": {"type": "ARRAY", "description": "Daftar perubahan per kelas.", "items": {"type": "OBJECT", "properties": {
                "class_name": {"type": "STRING", "description": "Salah satu: NO-Hardhat, NO-Mask, NO-Safety Vest, Fire, Smoke, Person, Hardhat, Mask, Safety Vest, Safety Cone, machinery, vehicle."},
                "monitor": {"type": "BOOLEAN", "description": "true = jadikan pemicu insiden, false = tidak."},
                "urgency": {"type": "STRING", "description": "'info', 'warning', atau 'critical'."},
                "display": {"type": "BOOLEAN", "description": "true = tampilkan box di gambar hasil, false = sembunyikan."},
            }, "required": ["class_name"]}},
        }, "required": ["updates"]},
    },
    {
        "name": "set_confidence",
        "description": "Ubah confidence threshold deteksi (0.1 - 0.95).",
        "parameters": {"type": "OBJECT", "properties": {
            "confidence": {"type": "NUMBER", "description": "Nilai 0.1 sampai 0.95, mis. 0.7 untuk 70%."},
        }, "required": ["confidence"]},
    },
    {
        "name": "verify_incident",
        "description": "Tandai sebuah insiden (berdasar nomor seq) sebagai CONFIRMED (pelanggaran asli) atau DISMISSED (salah deteksi).",
        "parameters": {"type": "OBJECT", "properties": {
            "seq": {"type": "INTEGER", "description": "Nomor insiden, mis. 7 untuk #7."},
            "status": {"type": "STRING", "description": "'CONFIRMED' atau 'DISMISSED'."},
        }, "required": ["seq", "status"]},
    },
    {
        "name": "record_action",
        "description": "Catat tindakan remediasi pada insiden CONFIRMED (berdasar nomor seq). Mengirim update ke channel tindakan.",
        "parameters": {"type": "OBJECT", "properties": {
            "seq": {"type": "INTEGER", "description": "Nomor insiden, mis. 7 untuk #7."},
            "note": {"type": "STRING", "description": "Deskripsi tindakan yang dilakukan."},
        }, "required": ["seq", "note"]},
    },
]

AGENT_SYSTEM_PROMPT = (
    "Kamu adalah AI Agent asisten keselamatan kerja (HSE) untuk dashboard Smart Factory. "
    "Jawab dalam Bahasa Indonesia, ringkas dan profesional. "
    "Sistem ini bekerja satu alur sinkron: pengguna mengunggah satu gambar/video, sistem menjalankan "
    "satu inferensi, lalu insiden PENDING dicatat kalau ada pelanggaran — bukan pemantauan kamera "
    "berkelanjutan. Kalau ditanya soal 'hasil deteksi', maksudnya insiden yang sudah tercatat dari "
    "proses-proses yang sudah dijalankan, gunakan get_events / generate_report untuk data nyata, "
    "jangan mengarang angka. "
    "Untuk permintaan yang mengubah sistem atau mengirim pesan, panggil function aksi yang sesuai satu kali; "
    "sistem SELALU meminta konfirmasi manusia sebelum benar-benar menjalankannya, jadi kamu tidak perlu meminta izin lagi. "
    "Kelas pelanggaran APD: NO-Hardhat, NO-Mask, NO-Safety Vest. Kelas darurat: Fire, Smoke. "
    "Setiap insiden punya nomor referensi 'seq' (mis. #7) yang tetap sama sepanjang siklus hidupnya — "
    "selalu sebutkan nomor ini saat membahas insiden tertentu, jangan pakai UUID panjang. "
    "Siklus status penuh: PENDING (baru terdeteksi, belum ditinjau admin — SELALU perlu review manusia, "
    "sistem tidak pernah meng-konfirmasi sendiri) -> CONFIRMED (admin memastikan ini pelanggaran asli) "
    "atau DISMISSED (admin menandai ini salah deteksi) -> jika CONFIRMED, admin bisa mencatat tindakan "
    "(action_taken=true, action_note berisi tindakan yang diambil, action_at waktunya) ATAU menghapusnya "
    "sebagai duplikat (status jadi DELETED). Kalau ditanya status suatu insiden, gunakan get_events dan "
    "baca field status/action_taken/action_note/action_at — jangan mengarang. "
    "Kamu BOLEH mengubah status insiden atas perintah user: pakai verify_incident untuk "
    "CONFIRMED/DISMISSED, dan record_action untuk mencatat tindakan. "
    "Kalau diminta ringkasan/laporan keselamatan, pakai generate_report (bukan get_events) lalu susun "
    "jadi laporan naratif yang jelas: total insiden, tren per kelas, jumlah darurat, dan soroti insiden "
    "CONFIRMED yang belum ditindak sebagai perhatian utama."
)


def describe_action(name, args):
    if name == "send_alert_message":
        return f'Kirim pesan ke channel safety:\n"{args.get("text", "")}"'
    if name == "set_class_rules":
        parts = []
        for u in (args.get("updates") or []):
            cls = u.get("class_name", "?")
            bits = []
            if "monitor" in u:
                bits.append("monitor ON" if u["monitor"] else "monitor OFF")
            if u.get("urgency"):
                bits.append(f"urgensi {u['urgency']}")
            if "display" in u:
                bits.append("tampil" if u["display"] else "sembunyi")
            parts.append(f"{cls} ({', '.join(bits)})" if bits else cls)
        return "Ubah aturan kelas: " + (", ".join(parts) if parts else "(tidak ada perubahan)")
    if name == "set_confidence":
        try:
            pct = round(float(args.get("confidence", 0)) * 100)
        except (TypeError, ValueError):
            pct = args.get("confidence")
        return f"Ubah confidence threshold ke {pct}%"
    if name == "verify_incident":
        return f"Tandai insiden #{args.get('seq')} sebagai {args.get('status')}"
    if name == "record_action":
        return f"Catat tindakan untuk insiden #{args.get('seq')}: \"{args.get('note', '')}\""
    return name


def _summarize_tool_result(name, result):
    try:
        if name == "get_events":
            return f"{result['count']} insiden ditemukan"
        if name == "get_notifications":
            return f"{result['count']} notifikasi ditemukan"
        if name == "get_class_rules":
            return f"{len(result['classes'])} kelas dimuat"
        if name == "get_system_config":
            return f"model aktif: {result.get('active_model')}, confidence: {result.get('confidence')}"
        if name == "generate_report":
            return f"{result['total_events']} insiden tercatat, {len(result['unresolved_confirmed_incidents'])} belum ditindak"
        if name == "export_report":
            if result.get("status") == "success":
                return f"file {result['format'].upper()} dibuat ({result.get('total')} insiden)"
            return result.get("message", "gagal membuat laporan")
    except Exception:
        pass
    return "selesai"


TOOL_LABELS = {
    "get_events": "Mengambil hasil deteksi",
    "get_notifications": "Mengambil log notifikasi",
    "get_class_rules": "Mengambil aturan kelas",
    "generate_report": "Menyusun statistik laporan",
    "get_system_config": "Mengecek konfigurasi sistem",
    "export_report": "Membuat file laporan",
}


def run_agent_chat_steps(history):
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
        for round_num in range(6):
            yield {"step": "thinking", "round": round_num + 1}
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=contents, config=config)
            calls = list(resp.function_calls or [])

            if not calls:
                yield {"step": "final", "configured": True, "reply": (resp.text or "").strip(), "pending_action": None}
                return

            needs_confirm = next((c for c in calls if c.name in ACTION_TOOLS), None)
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

            contents.append(resp.candidates[0].content)
            parts = []
            for c in calls:
                args = dict(c.args or {})
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
    _turn.files = []
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
        if step["step"] in ("thinking", "tool_call", "tool_result"):
            collected_steps.append(step)
        else:
            final_step = step
        yield step

    turn_reports = list(getattr(_turn, "files", []))
    if final_step:
        with engine_lock:
            agent_message_id = db_insert_message(
                session_id, "agent", final_step.get("reply", ""),
                steps=collected_steps, pending_action=final_step.get("pending_action"),
            )
        yield {
            "step": "saved",
            "agent_message_id": agent_message_id,
            "pending_action": final_step.get("pending_action"),
            "reports": turn_reports,
        }


_TERMINAL_STEPS = ("final", "action_proposed", "error", "not_configured")


def run_agent_chat_session_final(session_id, user_text):
    result = {"configured": False, "reply": "", "pending_action": None}
    agent_message_id = None
    turn_reports = []
    for step in run_agent_chat_session(session_id, user_text):
        if step["step"] == "saved":
            agent_message_id = step.get("agent_message_id")
            turn_reports = step.get("reports") or []
        elif step["step"] in _TERMINAL_STEPS:
            result = step
    result = dict(result)
    result["session_id"] = session_id
    result["agent_message_id"] = agent_message_id
    result["reports"] = turn_reports
    return result


def resolve_pending_action(message_id, approve):
    with engine_lock:
        msg = db_get_message(message_id)
        if not msg:
            return {"ok": False, "message": "Pesan tidak ditemukan.", "pending_action": None}
        pending = msg.get("pending_action")
        if not pending:
            return {"ok": False, "message": "Pesan ini tidak punya aksi tertunda.", "pending_action": None}
        if pending.get("state") and pending["state"] != "awaiting":
            return {"ok": False, "message": "Aksi ini sudah diproses sebelumnya.", "pending_action": pending}

        if not approve:
            pending["state"] = "cancelled"
            db_update_message_pending_action(message_id, pending)
            return {"ok": True, "message": "Aksi dibatalkan.", "pending_action": pending}

        tool = pending.get("tool")
        args = pending.get("args") or {}
        if tool not in ACTION_TOOLS:
            pending["state"] = "failed"
            pending["result"] = "Aksi tidak dikenal atau tidak diizinkan."
            db_update_message_pending_action(message_id, pending)
            return {"ok": False, "message": pending["result"], "pending_action": pending}

        try:
            result = ACTION_TOOLS[tool](**args)
            ok = result.get("status") != "error"
        except TypeError as e:
            ok = False
            result = {"message": f"Argumen tidak valid: {e}"}

        pending["state"] = "done" if ok else "failed"
        pending["result"] = result.get("message") or ("Aksi berhasil dijalankan." if ok else "Aksi gagal.")
        db_update_message_pending_action(message_id, pending)
        return {"ok": ok, "message": pending["result"], "pending_action": pending}
