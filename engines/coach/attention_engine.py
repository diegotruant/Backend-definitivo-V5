"""Coach attention prioritization — who needs review today."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.coach.checkin_engine import process_checkin
from engines.coach.prescription_safety import evaluate_prescription_safety
from engines.core.metric_contracts import (
    annotate_payload,
    compliance_score_value,
    normalize_readiness_score,
    unwrap_compliance_record,
)

SCHEMA_VERSION = "coach_attention.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"


def _score_attention(
    *,
    twin_state: Dict[str, Any],
    load_state: Dict[str, Any],
    readiness_state: Dict[str, Any],
    checkin: Optional[Dict[str, Any]],
    last_compliance: Optional[Dict[str, Any]],
    upcoming_key_session: bool,
    recent_checkins: Optional[Sequence[Dict[str, Any]]],
) -> tuple[int, List[str], str, str]:
    reasons: List[str] = []
    score = 0

    safety = evaluate_prescription_safety(
        readiness_state=readiness_state,
        load_state=load_state,
        injury_flags=checkin.get("pain_flags") if checkin else None,
    )
    if safety.get("level") == "professional_review_recommended":
        score += 50
        reasons.append("medical_or_injury_flag")
    elif safety.get("level") == "coach_review_recommended":
        score += 30
        reasons.extend(safety.get("reasons") or ["load_or_readiness_caution"])

    readiness = readiness_state.get("readiness_score") or readiness_state.get("score")
    try:
        readiness_norm = normalize_readiness_score(readiness)
        if readiness_norm is not None and readiness_norm < 50:
            score += 20
            reasons.append("readiness_drop")
    except (TypeError, ValueError):
        pass

    if upcoming_key_session:
        score += 15
        reasons.append("planned_key_session_tomorrow")

    if last_compliance:
        compliance_record = unwrap_compliance_record(last_compliance) or last_compliance
        c_score = compliance_score_value(compliance_record)
        if c_score is not None and c_score < 65:
            score += 15
            reasons.append("high_fatigue_low_compliance")
        if compliance_record.get("missed_key_work"):
            score += 20
            reasons.append("missed_key_work")

    if checkin:
        checkin_payload = {k: v for k, v in checkin.items() if k not in {"athlete_id", "recent_checkins"}}
        processed = process_checkin(recent_checkins=recent_checkins, **checkin_payload)
        psych = processed.get("psychological_support_flag") or {}
        if psych.get("human_check_recommended"):
            score += 25
            reasons.append("subjective_stress_high")

    if score >= 45:
        priority = "high"
        action = "Check in before prescribing intensity."
    elif score >= 20:
        priority = "medium"
        action = "Review plan; consider adjusting next session."
    else:
        priority = "low"
        action = "Routine monitoring."

    return score, sorted(set(reasons)), priority, action


def evaluate_athlete_attention(
    *,
    athlete_id: str,
    twin_state: Optional[Dict[str, Any]] = None,
    load_state: Optional[Dict[str, Any]] = None,
    readiness_state: Optional[Dict[str, Any]] = None,
    checkin: Optional[Dict[str, Any]] = None,
    last_compliance: Optional[Dict[str, Any]] = None,
    upcoming_key_session: bool = False,
    recent_checkins: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return attention priority for a single athlete."""
    twin = twin_state or {}
    load = load_state or twin.get("load_state") or {}
    readiness = readiness_state or twin.get("readiness_state") or {}
    compliance = last_compliance
    if compliance is None and isinstance(twin.get("last_compliance_results"), list) and twin["last_compliance_results"]:
        compliance = unwrap_compliance_record(twin["last_compliance_results"][0])

    score, reasons, priority, action = _score_attention(
        twin_state=twin,
        load_state=load,
        readiness_state=readiness,
        checkin=checkin,
        last_compliance=compliance if isinstance(compliance, dict) else None,
        upcoming_key_session=upcoming_key_session,
        recent_checkins=recent_checkins,
    )

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete_id,
        "athlete_attention": {
            "priority": priority,
            "attention_score": score,
            "reasons": reasons,
            "recommended_coach_action": action,
        },
        "limitations": [
            "Attention ranking supports coach workflow — not autonomous training decisions.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="attention_engine",
        method="athlete_attention",
        confidence=0.62,
    )


def evaluate_roster_attention(
    roster: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Rank multiple athletes by attention score for coach dashboard."""
    ranked: List[Dict[str, Any]] = []
    for entry in roster:
        athlete_id = str(entry.get("athlete_id") or "unknown")
        result = evaluate_athlete_attention(
            athlete_id=athlete_id,
            twin_state=entry.get("twin_state"),
            load_state=entry.get("load_state"),
            readiness_state=entry.get("readiness_state"),
            checkin=entry.get("checkin"),
            last_compliance=entry.get("last_compliance"),
            upcoming_key_session=bool(entry.get("upcoming_key_session")),
            recent_checkins=entry.get("recent_checkins"),
        )
        ranked.append({
            "athlete_id": athlete_id,
            **result["athlete_attention"],
        })
    ranked.sort(key=lambda row: (-row.get("attention_score", 0), row.get("athlete_id", "")))

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "roster_attention": ranked,
        "high_priority_count": sum(1 for r in ranked if r.get("priority") == "high"),
        "limitations": [
            "Roster attention is a triage aid — coach validates before contacting athletes.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="attention_engine",
        method="roster_attention",
        confidence=0.6,
    )
