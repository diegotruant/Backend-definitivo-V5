"""Injury and illness red flags — prudential training safety, not diagnosis."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.coach.prescription_safety import evaluate_prescription_safety
from engines.core.metric_contracts import annotate_payload, readiness_score_from_state

SCHEMA_VERSION = "training_safety.v1"
RISK_MODEL = "RISK_MODEL"


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_training_safety(
    *,
    athlete_id: Optional[str] = None,
    twin_state: Optional[Dict[str, Any]] = None,
    injury_flags: Optional[Sequence[str]] = None,
    illness_symptoms: Optional[bool] = None,
    checkin: Optional[Dict[str, Any]] = None,
    recent_checkins: Optional[Sequence[Dict[str, Any]]] = None,
    load_state: Optional[Dict[str, Any]] = None,
    readiness_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Dedicated injury/illness prudence layer for coach review."""
    twin = twin_state or {}
    load = load_state or twin.get("load_state") or {}
    readiness = readiness_state or twin.get("readiness_state") or {}
    checkin_data = checkin or twin.get("checkin_state") or {}
    if isinstance(checkin_data, dict) and checkin_data.get("checkin_summary"):
        merged = {**checkin_data.get("checkin_summary", {}), **checkin_data}
    else:
        merged = checkin_data if isinstance(checkin_data, dict) else {}

    base = evaluate_prescription_safety(
        injury_flags=injury_flags or merged.get("pain_flags"),
        readiness_state=readiness,
        load_state=load,
    )

    red_flags: List[str] = list(base.get("reasons") or [])
    if illness_symptoms or merged.get("illness_symptoms") or merged.get("sore_throat"):
        red_flags.append("illness_symptoms_reported")

    joint = _num(merged.get("joint_pain"))
    fatigue = _num(merged.get("perceived_fatigue") or merged.get("fatigue"))
    if joint is not None and joint >= 7:
        red_flags.append("joint_pain_reported")
    if fatigue is not None and fatigue >= 8:
        red_flags.append("fatigue_high")

    high_fatigue_days = 0
    for row in recent_checkins or []:
        if not isinstance(row, dict):
            continue
        f = _num(row.get("perceived_fatigue") or row.get("fatigue"))
        if f is not None and f >= 8:
            high_fatigue_days += 1
    if fatigue is not None and fatigue >= 8:
        high_fatigue_days += 1
    if high_fatigue_days >= 4:
        red_flags.append("fatigue_high_4_days")

    tsb = _num(load.get("tsb") or load.get("training_stress_balance"))
    if tsb is not None and tsb < -20:
        red_flags.append("load_spike")
    if load.get("acute_load_spike"):
        red_flags.append("acute_load_spike")

    readiness_score = readiness_score_from_state(readiness)
    if readiness_score is not None and readiness_score < 50:
        red_flags.append("readiness_low")

    red_flags = sorted(set(red_flags))
    status = "ok"
    safe_recommendation = "Training may proceed per plan if coach agrees."

    persisted = twin.get("training_safety_state") or {}
    if isinstance(persisted, dict):
        persisted_review = persisted.get("training_safety") or {}
        if isinstance(persisted_review, dict):
            red_flags = sorted(set(red_flags + list(persisted_review.get("red_flags") or [])))
            persisted_status = persisted_review.get("status")
            if persisted_status == "stop":
                status = "stop"
            elif persisted_status == "caution" and status == "ok":
                status = "caution"

    if status == "ok":
        if base.get("level") == "professional_review_recommended" or "illness_symptoms_reported" in red_flags:
            status = "stop"
        elif len(red_flags) >= 2 or base.get("level") == "coach_review_recommended":
            status = "caution"

    if status == "stop":
        safe_recommendation = "No high-intensity or heavy gym today. Professional or coach review required."
    elif status == "caution":
        safe_recommendation = "No high-intensity or heavy gym today. Coach review required."

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": RISK_MODEL,
        "athlete_id": athlete_id,
        "training_safety": {
            "status": status,
            "red_flags": red_flags,
            "safe_recommendation": safe_recommendation,
            "avoid_today": (
                ["high_intensity", "heavy_gym", "anaerobic_intervals"]
                if status in {"caution", "stop"}
                else []
            ),
            "allowed_today": (
                ["zone2", "mobility", "rest"]
                if status in {"caution", "stop"}
                else ["prescribed_training"]
            ),
        },
        "limitations": [
            "Training safety flags are prudential — not a medical diagnosis.",
            "Illness symptoms require human judgment before returning to intensity.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="injury_illness_engine",
        method="evaluate_training_safety",
        confidence=0.65 if red_flags else 0.45,
    )
