"""Periodization coherence — phase/goal alignment, load risk and gym/bike conflicts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.core.metric_contracts import annotate_payload
from engines.planning.season_planner import check_load_risk, create_season_plan

SCHEMA_VERSION = "periodization_review.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"

PHASE_ORDER = ("base", "build", "peak", "taper")
GOAL_PHASE_HINTS = {
    "vo2": {"preferred_phases": ("build", "peak"), "avoid_in": ("taper",)},
    "threshold": {"preferred_phases": ("build", "peak"), "avoid_in": ("base",)},
    "endurance": {"preferred_phases": ("base", "build"), "avoid_in": ("peak",)},
    "granfondo": {"preferred_phases": ("base", "build", "peak"), "avoid_in": ()},
    "fat_loss": {"preferred_phases": ("base",), "avoid_in": ("peak",)},
}


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _session_date(session: Dict[str, Any]) -> Optional[str]:
    for key in ("date", "day", "scheduled_date"):
        if session.get(key):
            return str(session[key])[:10]
    return None


def _gym_bike_conflicts(
  upcoming_bike_sessions: Sequence[Dict[str, Any]],
  strength_days: Sequence[str],
) -> List[Dict[str, Any]]:
    conflicts: List[Dict[str, Any]] = []
    key_bike = [
        s for s in upcoming_bike_sessions
        if isinstance(s, dict) and str(s.get("type", "")).lower() in {
            "threshold", "vo2", "anaerobic", "race", "key", "intervals",
        }
    ]
    for bike in key_bike:
        bike_date = _session_date(bike)
        if not bike_date:
            continue
        for gym_day in strength_days:
            if gym_day and gym_day[:10] == bike_date:
                conflicts.append({
                    "type": "gym_before_key_bike",
                    "date": bike_date,
                    "message": "Heavy gym on same day as key bike session — interference risk.",
                })
    return conflicts


def _phase_alignment(season_phase: str, goal: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    focus = str((goal or {}).get("focus") or "balanced").strip().lower()
    hints = GOAL_PHASE_HINTS.get(focus, {"preferred_phases": PHASE_ORDER, "avoid_in": ()})
    phase = str(season_phase or "base").strip().lower()
    aligned = phase in hints["preferred_phases"]
    misaligned = phase in hints["avoid_in"]
    status = "aligned" if aligned and not misaligned else "misaligned" if misaligned else "review"
    return {
        "current_phase": phase,
        "goal_focus": focus,
        "status": status,
        "preferred_phases": list(hints["preferred_phases"]),
        "note": (
            f"Current phase '{phase}' fits goal '{focus}'."
            if aligned and not misaligned
            else f"Phase '{phase}' may be early/late for goal '{focus}' — coach review suggested."
        ),
    }


def review_periodization(
    *,
    athlete_id: Optional[str] = None,
    season_plan: Optional[List[Dict[str, Any]]] = None,
    start_date: Optional[str] = None,
    target_date: Optional[str] = None,
    weekly_hours: float = 8.0,
    goal: Optional[Dict[str, Any]] = None,
    season_phase: str = "base",
    strength_prescription: Optional[Dict[str, Any]] = None,
    upcoming_bike_sessions: Optional[Sequence[Dict[str, Any]]] = None,
    load_state: Optional[Dict[str, Any]] = None,
    twin_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Review macro plan coherence — not an autonomous plan rewrite."""
    twin = twin_state or {}
    plan_weeks = list(season_plan or [])
    if not plan_weeks and (start_date or target_date or goal):
        generated = create_season_plan(
            start_date=start_date,
            target_date=target_date,
            weekly_hours=weekly_hours,
            goal=goal,
        )
        plan_weeks = generated.get("weeks") or []

    chronic = _num((load_state or twin.get("load_state") or {}).get("chronic_load"))
    load_review = check_load_risk(plan_weeks, chronic_load=chronic or 50.0)

    strength = strength_prescription or twin.get("strength_state", {}).get("prescription") or {}
    strength_days = [
        str(d)[:10]
        for d in (strength.get("scheduled_days") or strength.get("gym_days") or [])
    ]
    bike_sessions = list(upcoming_bike_sessions or [])
    conflicts = _gym_bike_conflicts(bike_sessions, strength_days)

    phase_review = _phase_alignment(season_phase, goal)
    suggestions: List[str] = []
    if phase_review["status"] != "aligned":
        suggestions.append("Align session quality with current macro phase before adding load.")
    if load_review.get("risk") in {"moderate", "high"}:
        suggestions.append("Reduce weekly load jump or insert recovery week.")
    for warning in load_review.get("warnings") or []:
        if isinstance(warning, dict) and warning.get("warning") == "large_weekly_load_jump":
            suggestions.append(f"Large load jump at week {warning.get('week_index')} — smooth progression.")
    if conflicts:
        suggestions.append("Separate heavy gym from key bike by at least 24–48 h when possible.")

    coherence = "aligned"
    if conflicts or load_review.get("risk") == "high" or phase_review["status"] == "misaligned":
        coherence = "review_recommended"
    if load_review.get("risk") == "high" and phase_review["status"] == "misaligned":
        coherence = "misaligned"

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete_id,
        "periodization_review": {
            "coherence_status": coherence,
            "phase_alignment": phase_review,
            "load_risk": {
                "level": load_review.get("risk"),
                "weekly_loads": load_review.get("weekly_loads"),
                "warnings": load_review.get("warnings"),
            },
            "conflicts": conflicts,
            "suggestions": suggestions or ["Macro structure looks coherent — continue monitoring adherence."],
            "weeks_reviewed": len(plan_weeks),
        },
        "limitations": [
            "Periodization review is heuristic — athlete response and life constraints override templates.",
            "Provide season_plan or start/target dates for load-risk analysis.",
        ],
    }
    conf = 0.65 if plan_weeks else 0.4
    return annotate_payload(
        payload,
        module_name="periodization_engine",
        method="coach_periodization_review",
        confidence=conf,
    )
