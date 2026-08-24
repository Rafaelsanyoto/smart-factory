"""Runtime-mutable state — the values that change while the app runs, loaded from the DB
at startup and mirrored here for fast reads on the hot path (every detected frame reads
ZONE_RULES / active_confidence / context_visibility).

IMPORTANT: the scalars below (active_model_id, active_confidence, agent_permission_mode)
get REASSIGNED at runtime by actions.apply_*(). Always read them as `state.active_...`
(module-attribute access), never `from state import active_confidence` — the latter
copies the value at import time and would never see later updates. The dicts (ZONE_RULES,
context_visibility, latest_detections) are mutated in place, so importing them by name
would technically work, but for consistency everything here is accessed as `state.X`."""
import json

from .config import DEFAULT_MODEL, CONTEXT_CLASSES, PPE_TO_VIOLATION, EMERGENCY_CLASSES, PERMISSION_MODES
from . import database as db

# Fast in-memory mirrors of DB-persisted config. Writes go through actions.apply_*(),
# which update both this mirror AND the DB (so the next restart picks up the latest).
ZONE_RULES = db.db_load_zone_rules()
active_model_id = db.db_load_config("active_model_id", DEFAULT_MODEL)
active_confidence = float(db.db_load_config("active_confidence", "0.25"))
context_visibility = json.loads(db.db_load_config("context_visibility") or "{}") or {c: True for c in CONTEXT_CLASSES}

agent_permission_mode = db.db_load_config("agent_permission_mode", "standard")
if agent_permission_mode not in PERMISSION_MODES:
    agent_permission_mode = "standard"

# Most recent per-stream detection breakdown, written by each camera's ai_loop and read by
# the /api/data/{stream_id} endpoint. Mutated in place (keyed by stream_id).
latest_detections = {"stream_01": [], "stream_02": []}


def violation_classes_for(stream_id):
    """The set of NO-* classes that count as violations in a given zone."""
    rule = ZONE_RULES.get(stream_id, {})
    return {PPE_TO_VIOLATION[p] for p in rule.get("required", []) if p in PPE_TO_VIOLATION}


def emergency_classes_for(stream_id):
    """The set of emergency classes (Fire/Smoke) enabled for a given zone."""
    rule = ZONE_RULES.get(stream_id, {})
    return {c for c in rule.get("emergency", []) if c in EMERGENCY_CLASSES}


def is_context_visible(class_name):
    return context_visibility.get(class_name, True)
