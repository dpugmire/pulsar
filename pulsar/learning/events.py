"""Versioned interaction-event vocabulary and validation."""

from datetime import datetime
from typing import Any, Dict, List, Mapping
from uuid import uuid4


EVENT_SCHEMA_VERSION = 1

EVENT_TYPES = frozenset(
    {
        "session.started",
        "session.ended",
        "query.applied",
        "query.cleared",
        "visualization.assigned",
        "visualization.changed",
        "visualization.removed",
        "plugin.executed",
        "workspace.tab_activated",
        "workspace.tab_created",
        "workspace.tab_renamed",
        "workspace.tab_closed",
        "workspace.tab_reordered",
        "workspace.tab_moved",
        "workspace.pane_split",
        "workspace.pane_closed",
        "workspace.pane_resized",
        "workspace.cell_moved",
        "workspace.cell_spanned",
        "workspace.layout_changed",
        "workspace.timeline_driver_changed",
        "workspace.saved",
        "workspace.loaded",
        "workspace.snapshot",
    }
)

_REQUIRED_FIELDS = (
    "schema_version",
    "event_id",
    "event_sequence",
    "timestamp_utc",
    "elapsed_session_ms",
    "user_profile_id",
    "session_id",
    "campaign_version_id",
    "event_type",
    "source",
    "model_version",
    "payload",
)


def new_identifier(kind: str) -> str:
    prefix = str(kind or "id").strip().replace(" ", "-") or "id"
    return f"{prefix}:{uuid4()}"


def _valid_timestamp(value: Any) -> bool:
    text = str(value or "")
    if not text.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def validate_event(event: Any) -> List[str]:
    """Return human-readable validation errors for one decoded event."""

    if not isinstance(event, Mapping):
        return ["event must be a JSON object"]

    errors: List[str] = []
    missing = [field for field in _REQUIRED_FIELDS if field not in event]
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
        return errors

    if event.get("schema_version") != EVENT_SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {event.get('schema_version')}")
    if str(event.get("event_type", "")) not in EVENT_TYPES:
        errors.append(f"unsupported event_type: {event.get('event_type')}")
    for field in (
        "event_id",
        "user_profile_id",
        "session_id",
        "campaign_version_id",
        "source",
        "model_version",
    ):
        if not isinstance(event.get(field), str) or not event.get(field):
            errors.append(f"{field} must be non-empty text")

    sequence = event.get("event_sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        errors.append("event_sequence must be a positive integer")

    elapsed = event.get("elapsed_session_ms")
    if isinstance(elapsed, bool) or not isinstance(elapsed, int) or elapsed < 0:
        errors.append("elapsed_session_ms must be a non-negative integer")
    if not _valid_timestamp(event.get("timestamp_utc")):
        errors.append("timestamp_utc must be an ISO-8601 UTC timestamp")
    if not isinstance(event.get("payload"), Mapping):
        errors.append("payload must be a JSON object")
    return errors
