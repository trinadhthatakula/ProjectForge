from __future__ import annotations

from typing import Any
from uuid import uuid4

from .common import now_utc
from .security import redact_sensitive


_EVENT_FIELDS: dict[str, set[str]] = {
    "manifest_initialized": set(),
    "manifest_migrated": {"source_version"},
    "classification_applied": {"classification"},
    "capability_discovery_applied": {"affected_count"},
    "team_plan_applied": {"affected_count"},
    "dependency_resolution_applied": {"affected_count"},
    "capability_verification_applied": {"affected_count"},
    "agent_result_recorded": {"assignment_id", "result_id"},
    "agent_result_reviewed": {"assignment_id", "result_id", "previous_review_status", "review_status"},
    "estimate_applied": set(),
}


def append_execution_event(manifest: dict[str, Any], event_type: str, **metadata: Any) -> dict[str, Any]:
    """Append a constrained metadata-only event to a manifest execution log."""
    expected = _EVENT_FIELDS.get(event_type)
    if expected is None:
        raise ValueError(f"Unsupported execution event type {event_type!r}")
    if set(metadata) != expected:
        raise ValueError(f"Event {event_type!r} requires exactly these metadata fields: {', '.join(sorted(expected)) or '(none)'}")
    if redact_sensitive(metadata) != metadata:
        raise ValueError("Secret-like values cannot be written to execution event metadata")
    execution = manifest.setdefault("execution", {})
    events = execution.setdefault("events", [])
    event = {"event_id": str(uuid4()), "occurred_at": now_utc(), "event_type": event_type, **metadata}
    events.append(event)
    return event
