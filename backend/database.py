import json
import os
import sqlite3
import threading
import time
import uuid

from .config import DATA_DIR, DB_PATH, DEFAULT_CLASS_RULES, RESULT_LABEL

os.makedirs(DATA_DIR, exist_ok=True)
db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
db_conn.row_factory = sqlite3.Row

engine_lock = threading.RLock()

MAX_MESSAGES_PER_SESSION = 200
MAX_SESSIONS_PER_SOURCE = 200

CLASS_RULES_ID = "default"


def init_db():
    db_conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            seq INTEGER UNIQUE NOT NULL,
            timestamp TEXT NOT NULL,
            ts_ms REAL NOT NULL,
            zone TEXT NOT NULL,
            type TEXT NOT NULL,
            class TEXT NOT NULL,
            confidence REAL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            verified_at TEXT,
            action_taken INTEGER NOT NULL DEFAULT 0,
            action_note TEXT,
            action_at TEXT,
            deleted INTEGER NOT NULL DEFAULT 0,
            delete_reason TEXT,
            deleted_at TEXT,
            urgency TEXT,
            alarm_ack_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
        CREATE INDEX IF NOT EXISTS idx_events_ts_ms ON events(ts_ms);

        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL REFERENCES events(id),
            timestamp TEXT NOT NULL,
            message TEXT NOT NULL,
            severity TEXT NOT NULL,
            dispatched INTEGER NOT NULL DEFAULT 0,
            channel TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_notif_event ON notifications(event_id);

        CREATE TABLE IF NOT EXISTS class_rules (
            id TEXT PRIMARY KEY,
            monitored_classes TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT 'Percakapan baru',
            source TEXT NOT NULL DEFAULT 'dashboard',
            discord_channel_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_source ON chat_sessions(source);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_discord_channel
            ON chat_sessions(discord_channel_id) WHERE discord_channel_id IS NOT NULL;

        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES chat_sessions(id),
            role TEXT NOT NULL,
            text TEXT,
            steps TEXT,
            pending_action TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id);
    """)
    db_conn.commit()


def _seed_defaults():
    if db_conn.execute("SELECT COUNT(*) c FROM class_rules").fetchone()["c"] == 0:
        db_conn.execute(
            "INSERT INTO class_rules (id, monitored_classes) VALUES (?, ?)",
            (CLASS_RULES_ID, json.dumps(DEFAULT_CLASS_RULES)),
        )
    if db_conn.execute("SELECT COUNT(*) c FROM system_config").fetchone()["c"] == 0:
        db_conn.executemany(
            "INSERT INTO system_config (key, value) VALUES (?, ?)",
            [
                ("active_confidence", "0.25"),
                ("event_seq_counter", "0"),
            ],
        )
    db_conn.commit()


def db_save_config(key, value):
    db_conn.execute(
        "INSERT INTO system_config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    db_conn.commit()


def db_load_config(key, default=None):
    row = db_conn.execute("SELECT value FROM system_config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def db_save_class_rules(classes):
    db_conn.execute(
        "INSERT INTO class_rules (id, monitored_classes) VALUES (?, ?) "
        "ON CONFLICT(id) DO UPDATE SET monitored_classes = excluded.monitored_classes",
        (CLASS_RULES_ID, json.dumps(classes)),
    )
    db_conn.commit()


def db_load_class_rules():
    row = db_conn.execute(
        "SELECT monitored_classes FROM class_rules WHERE id = ?", (CLASS_RULES_ID,)
    ).fetchone()
    return json.loads(row["monitored_classes"]) if row else dict(DEFAULT_CLASS_RULES)


def _event_row_to_dict(row):
    d = dict(row)
    d["action_taken"] = bool(d["action_taken"])
    d["deleted"] = bool(d["deleted"])
    return d


def _notif_row_to_dict(row):
    d = dict(row)
    d["dispatched"] = bool(d["dispatched"])
    return d


def db_next_seq():
    current = int(db_load_config("event_seq_counter", "0"))
    nxt = current + 1
    db_save_config("event_seq_counter", nxt)
    return nxt


def db_insert_event(event):
    db_conn.execute(
        """INSERT INTO events (id, seq, timestamp, ts_ms, zone, type, class, confidence,
           status, verified_at, action_taken, action_note, action_at, deleted, delete_reason,
           deleted_at, urgency) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            event["id"], event["seq"], event["timestamp"], event["ts_ms"],
            event.get("zone", RESULT_LABEL), event["type"], event["class"], event["confidence"],
            event["status"], event["verified_at"], int(event["action_taken"]), event["action_note"],
            event["action_at"], int(event["deleted"]), event["delete_reason"], event["deleted_at"],
            event.get("urgency"),
        ),
    )
    db_conn.commit()


def db_get_events(limit=200):
    rows = db_conn.execute("SELECT * FROM events ORDER BY ts_ms DESC LIMIT ?", (limit,)).fetchall()
    return [_event_row_to_dict(r) for r in rows]


def db_get_event(event_id):
    row = db_conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return _event_row_to_dict(row) if row else None


def db_update_event(event_id, **fields):
    coerced = {k: (int(v) if isinstance(v, bool) else v) for k, v in fields.items()}
    set_clause = ", ".join(f"{k} = ?" for k in coerced)
    db_conn.execute(f"UPDATE events SET {set_clause} WHERE id = ?", (*coerced.values(), event_id))
    db_conn.commit()
    return db_get_event(event_id)


def db_insert_notification(note):
    db_conn.execute(
        """INSERT INTO notifications (id, event_id, timestamp, message, severity,
           dispatched, channel) VALUES (?,?,?,?,?,?,?)""",
        (
            note["id"], note["event_id"], note["timestamp"], note["message"], note["severity"],
            int(note["dispatched"]), note["channel"],
        ),
    )
    db_conn.commit()


def db_get_notifications(limit=200):
    rows = db_conn.execute("SELECT * FROM notifications ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
    return [_notif_row_to_dict(r) for r in rows]


def db_update_notification(note_id, **fields):
    coerced = {k: (int(v) if isinstance(v, bool) else v) for k, v in fields.items()}
    set_clause = ", ".join(f"{k} = ?" for k in coerced)
    db_conn.execute(f"UPDATE notifications SET {set_clause} WHERE id = ?", (*coerced.values(), note_id))
    db_conn.commit()


def db_create_session(source="dashboard", discord_channel_id=None, title="Percakapan baru"):
    session_id = str(uuid.uuid4())
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    db_conn.execute(
        "INSERT INTO chat_sessions (id, title, source, discord_channel_id, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?)",
        (session_id, title, source, discord_channel_id, now, now),
    )
    db_conn.commit()
    db_prune_sessions(source)
    return session_id


def db_get_sessions(source=None, limit=50):
    if source:
        rows = db_conn.execute(
            "SELECT * FROM chat_sessions WHERE source = ? ORDER BY updated_at DESC LIMIT ?", (source, limit),
        ).fetchall()
    else:
        rows = db_conn.execute("SELECT * FROM chat_sessions ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def db_get_session(session_id):
    row = db_conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def db_touch_session(session_id, title=None):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    if title:
        db_conn.execute("UPDATE chat_sessions SET updated_at = ?, title = ? WHERE id = ?", (now, title, session_id))
    else:
        db_conn.execute("UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (now, session_id))
    db_conn.commit()


def db_delete_session(session_id):
    db_conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    db_conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    db_conn.commit()


def db_get_or_create_discord_session(channel_id):
    channel_id = str(channel_id)
    row = db_conn.execute(
        "SELECT id FROM chat_sessions WHERE source = 'discord' AND discord_channel_id = ?", (channel_id,),
    ).fetchone()
    if row:
        return row["id"]
    return db_create_session(source="discord", discord_channel_id=channel_id, title=f"Discord #{channel_id}")


def db_insert_message(session_id, role, text, steps=None, pending_action=None):
    msg_id = str(uuid.uuid4())
    db_conn.execute(
        "INSERT INTO chat_messages (id, session_id, role, text, steps, pending_action, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            msg_id, session_id, role, text,
            json.dumps(steps) if steps is not None else None,
            json.dumps(pending_action) if pending_action is not None else None,
            time.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    db_conn.commit()
    db_prune_session_messages(session_id)
    return msg_id


def db_get_messages(session_id, limit=None):
    query = "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC, rowid ASC"
    params = [session_id]
    if limit:
        query = (
            "SELECT * FROM (SELECT *, rowid AS _rid FROM chat_messages WHERE session_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?) ORDER BY created_at ASC, _rid ASC"
        )
        params.append(limit)
    rows = db_conn.execute(query, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d.pop("_rid", None)
        d["steps"] = json.loads(d["steps"]) if d["steps"] else []
        d["pending_action"] = json.loads(d["pending_action"]) if d["pending_action"] else None
        result.append(d)
    return result


def db_get_message(message_id):
    row = db_conn.execute("SELECT * FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["steps"] = json.loads(d["steps"]) if d["steps"] else []
    d["pending_action"] = json.loads(d["pending_action"]) if d["pending_action"] else None
    return d


def db_update_message_pending_action(message_id, pending_action):
    db_conn.execute(
        "UPDATE chat_messages SET pending_action = ? WHERE id = ?",
        (json.dumps(pending_action), message_id),
    )
    db_conn.commit()


def db_prune_session_messages(session_id):
    db_conn.execute(
        """DELETE FROM chat_messages WHERE session_id = ? AND id NOT IN (
               SELECT id FROM chat_messages WHERE session_id = ?
               ORDER BY created_at DESC, rowid DESC LIMIT ?
           )""",
        (session_id, session_id, MAX_MESSAGES_PER_SESSION),
    )
    db_conn.commit()


def db_prune_sessions(source):
    stale = db_conn.execute(
        "SELECT id FROM chat_sessions WHERE source = ? ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
        (source, MAX_SESSIONS_PER_SOURCE),
    ).fetchall()
    if not stale:
        return
    stale_ids = [(r["id"],) for r in stale]
    db_conn.executemany("DELETE FROM chat_messages WHERE session_id = ?", stale_ids)
    db_conn.executemany("DELETE FROM chat_sessions WHERE id = ?", stale_ids)
    db_conn.commit()


init_db()
_seed_defaults()
