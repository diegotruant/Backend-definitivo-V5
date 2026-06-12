"""Small backend calendar state helpers.

The DB will store assignments; this module centralises status transitions so
frontend clients do not invent their own workflow rules.
"""

from __future__ import annotations

from typing import Dict, Set

VALID_ASSIGNMENT_STATUSES: Set[str] = {
    "draft",
    "assigned",
    "scheduled",
    "started",
    "completed",
    "missed",
    "skipped",
    "rescheduled",
    "replaced",
    "analyzed",
}

_ALLOWED_TRANSITIONS = {
    "draft": {"assigned", "skipped"},
    "assigned": {"scheduled", "started", "rescheduled", "replaced", "skipped", "missed"},
    "scheduled": {"started", "rescheduled", "replaced", "skipped", "missed"},
    "started": {"completed", "skipped"},
    "completed": {"analyzed"},
    "analyzed": set(),
    "missed": {"rescheduled", "replaced"},
    "skipped": {"rescheduled", "replaced"},
    "rescheduled": {"scheduled", "started", "skipped", "missed"},
    "replaced": {"assigned", "scheduled"},
}


def validate_status_transition(current: str, desired: str) -> Dict[str, object]:
    if current not in VALID_ASSIGNMENT_STATUSES:
        return {"status": "invalid", "allowed": False, "reason": f"Unknown current status: {current}"}
    if desired not in VALID_ASSIGNMENT_STATUSES:
        return {"status": "invalid", "allowed": False, "reason": f"Unknown desired status: {desired}"}
    allowed = desired in _ALLOWED_TRANSITIONS.get(current, set()) or current == desired
    return {
        "status": "valid" if allowed else "invalid",
        "allowed": bool(allowed),
        "current": current,
        "desired": desired,
        "allowed_next_statuses": sorted(_ALLOWED_TRANSITIONS.get(current, set())),
    }
