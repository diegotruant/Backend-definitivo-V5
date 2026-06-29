"""Coach-facing adherence analysis — planned vs done with reason candidates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.core.metric_contracts import annotate_payload, compliance_score_value, readiness_score_from_state, unwrap_compliance_record
from engines.workouts.compliance_engine import compare_workout_to_activity

SCHEMA_VERSION = "adherence_report.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reason_candidates(
    *,
    score: Optional[float],
    missed_key: bool,
    readiness_state: Optional[Dict[str, Any]],
    checkin: Optional[Dict[str, Any]],
    classification: Optional[str],
) -> List[str]:
    reasons: List[str] = []
    if missed_key:
        reasons.append("missed_key_work")
    if score is not None and score < 70:
        reasons.append("too_high_target")
    if classification in {"partially_completed", "not_completed_as_prescribed"}:
        reasons.append("structure_mismatch")

    readiness = readiness_score_from_state(readiness_state)
    if readiness is not None and readiness < 55:
        reasons.append("fatigue")
    if checkin:
        fatigue = _num(checkin.get("perceived_fatigue"))
        motivation = _num(checkin.get("motivation"))
        if fatigue is not None and fatigue >= 8:
            reasons.append("poor_recovery")
        if motivation is not None and motivation <= 4:
            reasons.append("low_motivation")
    if not reasons and score is not None and score < 85:
        reasons.append("external_constraint")
    return sorted(set(reasons))


def _coach_note(score: Optional[float], reasons: List[str], missed_key: bool) -> str:
    if missed_key:
        return "Reduce next intensity or ask for subjective feedback before progressing."
    if score is not None and score < 60:
        return "Compliance is low — review target realism, fatigue and session structure."
    if "fatigue" in reasons or "poor_recovery" in reasons:
        return "Consider recovery emphasis; athlete may be under-recovered for prescribed load."
    if score is not None and score >= 90:
        return "Good adherence — progression can continue if readiness supports it."
    return "Review planned vs performed before adjusting the next block."


def evaluate_adherence(
    *,
    athlete_id: Optional[str] = None,
    planned_workout: Optional[Dict[str, Any]] = None,
    performed_compliance: Optional[Dict[str, Any]] = None,
    activity_stream: Any = None,
    athlete_profile: Optional[Dict[str, Any]] = None,
    compliance_history: Optional[Sequence[Dict[str, Any]]] = None,
    readiness_state: Optional[Dict[str, Any]] = None,
    checkin: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return coach-facing adherence/compliance with reason candidates."""
    compliance = performed_compliance
    if compliance is None and planned_workout is not None and activity_stream is not None:
        compliance = compare_workout_to_activity(
            planned_workout,
            activity_stream,
            athlete_profile=athlete_profile,
        )

    if compliance is None and compliance_history:
        compliance = compliance_history[-1] if isinstance(compliance_history, list) else None

    if not compliance:
        return annotate_payload(
            {
                "status": "insufficient_data",
                "schema_version": SCHEMA_VERSION,
                "measurement_tier": PRESCRIPTION_MODEL,
                "reason": "missing_compliance_input",
                "limitations": ["Provide performed_compliance, compliance_history, or planned_workout + activity_stream."],
            },
            module_name="adherence_engine",
            method="coach_adherence",
            confidence=0.0,
        )

    score = compliance_score_value(compliance)
    compliance_record = unwrap_compliance_record(compliance) or (compliance if isinstance(compliance, dict) else {})
    classification = compliance_record.get("classification")
    summary = compliance_record.get("summary") if isinstance(compliance_record.get("summary"), dict) else {}
    missed_key = bool(summary.get("planned_key_intervals")) and (
        summary.get("completed_key_intervals", 0) < summary.get("planned_key_intervals", 0)
    )
    if compliance_record.get("missed_key_work"):
        missed_key = True

    reasons = _reason_candidates(
        score=score,
        missed_key=missed_key,
        readiness_state=readiness_state,
        checkin=checkin,
        classification=classification,
    )

    trend = "stable"
    history_scores = [
        compliance_score_value(row)
        for row in (compliance_history or [])
    ]
    history_scores = [s for s in history_scores if s is not None]
    if len(history_scores) >= 3:
        recent = history_scores[-3:]
        if all(s < 70 for s in recent):
            trend = "declining"
        elif all(s >= 85 for s in recent):
            trend = "strong"

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete_id,
        "compliance": {
            "score": score,
            "classification": classification,
            "completed_structure": "full" if score and score >= 90 else "partial" if score and score >= 55 else "low",
            "missed_key_work": missed_key,
            "trend": trend,
            "reason_candidates": reasons,
            "coach_note": _coach_note(score, reasons, missed_key),
        },
        "source_compliance": compliance,
        "limitations": [
            "Adherence interpretation depends on prescription quality and sensor availability in performed files.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="adherence_engine",
        method="coach_adherence",
        confidence=float(compliance.get("confidence_score") or 0.55),
    )
