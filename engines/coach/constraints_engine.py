"""Athlete lifestyle constraints — adapt prescriptions to real life."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.core.metric_contracts import annotate_payload

SCHEMA_VERSION = "constraints_adaptation.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"


def evaluate_constraints(
    *,
    athlete_id: Optional[str] = None,
    constraints: Optional[Dict[str, Any]] = None,
    season_phase: str = "build",
    planned_weekly_hours: Optional[float] = None,
) -> Dict[str, Any]:
    """Translate lifestyle constraints into coach-facing adaptation hints."""
    c = dict(constraints or {})
    available_days = [str(d).lower()[:3] for d in (c.get("available_days") or [])]
    max_duration = c.get("max_session_duration_min")
    travel_week = bool(c.get("travel_week"))
    sleep_restricted = bool(c.get("sleep_restricted"))
    work_stress = bool(c.get("work_stress_high") or c.get("high_work_stress"))
    family_constraints = bool(c.get("family_constraints"))

    adaptations: List[str] = []
    volume_factor = 1.0
    intensity_cap = "normal"

    if travel_week:
        volume_factor *= 0.75
        intensity_cap = "hold"
        adaptations.append("Travel week — maintain stimulus, reduce volume and session complexity.")
    if sleep_restricted:
        volume_factor *= 0.85
        if intensity_cap == "normal":
            intensity_cap = "reduce"
        adaptations.append("Sleep restricted — avoid stacking intensity and gym in the same week.")
    if work_stress or family_constraints:
        adaptations.append("External stress high — prioritize consistency over progression.")
        if intensity_cap == "normal":
            intensity_cap = "reduce"

    if max_duration is not None:
        try:
            if float(max_duration) < 60:
                adaptations.append("Short sessions only — use density or quality over duration.")
        except (TypeError, ValueError):
            pass

    if available_days and len(available_days) <= 3:
        adaptations.append("Limited training days — use polarized mini-block with one key session.")
        if season_phase in {"build", "peak"}:
            adaptations.append("This week is not a full build block — keep one quality stimulus.")

    if not adaptations:
        adaptations.append("No major constraints flagged — proceed with planned structure.")

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete_id,
        "constraints": {
            "reported": c,
            "available_days": available_days,
            "max_session_duration_min": max_duration,
            "travel_week": travel_week,
            "sleep_restricted": sleep_restricted,
        },
        "adaptation": {
            "volume_factor": round(volume_factor, 2),
            "intensity_cap": intensity_cap,
            "coach_notes": adaptations,
            "planned_weekly_hours_hint": (
                round(planned_weekly_hours * volume_factor, 1) if planned_weekly_hours else None
            ),
        },
        "limitations": [
            "Constraint adaptation is heuristic — coach confirms with athlete before changing the plan.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="constraints_engine",
        method="evaluate_constraints",
        confidence=0.6 if c else 0.35,
    )
