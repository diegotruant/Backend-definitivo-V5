"""Standalone decision safety for coach prescriptions and intensity progression."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.coach.checkin_engine import process_checkin
from engines.coach.prescription_safety import evaluate_prescription_safety
from engines.core.metric_contracts import annotate_payload

SCHEMA_VERSION = "decision_safety.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"


def _compliance_score(last_compliance: Optional[Dict[str, Any]]) -> Optional[float]:
    if not last_compliance:
        return None
    for key in ("compliance_score", "score"):
        try:
            return float(last_compliance.get(key))
        except (TypeError, ValueError):
            continue
    return None


def _merge_level(base: Dict[str, Any], extra_reasons: List[str], escalate: bool) -> Dict[str, Any]:
    out = dict(base)
    reasons = list(out.get("reasons") or [])
    reasons.extend(extra_reasons)
    out["reasons"] = sorted(set(reasons))
    if escalate and out.get("level") == "ok_to_auto_suggest":
        out["level"] = "coach_review_recommended"
        out["status"] = "caution"
        out["algorithm_action"] = "do_not_auto_progress"
        out["human_action"] = "coach_check_in"
    return out


def evaluate_decision_safety(
    *,
    athlete_id: Optional[str] = None,
    twin_state: Optional[Dict[str, Any]] = None,
    load_state: Optional[Dict[str, Any]] = None,
    readiness_state: Optional[Dict[str, Any]] = None,
    last_compliance: Optional[Dict[str, Any]] = None,
    injury_flags: Optional[Sequence[str]] = None,
    checkin: Optional[Dict[str, Any]] = None,
    recent_checkins: Optional[Sequence[Dict[str, Any]]] = None,
    upcoming_key_session: Optional[bool] = None,
) -> Dict[str, Any]:
    """Unified safety envelope for intensity, gym and fueling decisions."""
    twin = twin_state or {}
    load = load_state or twin.get("load_state") or {}
    readiness = readiness_state or twin.get("readiness_state") or {}
    compliance = last_compliance or (
        twin.get("last_compliance_results")[0]
        if isinstance(twin.get("last_compliance_results"), list) and twin.get("last_compliance_results")
        else None
    )

    base = evaluate_prescription_safety(
        injury_flags=injury_flags,
        readiness_state=readiness,
        load_state=load,
    )

    extra_reasons: List[str] = []
    escalate = False
    psych_flag: Dict[str, Any] = {"status": "no_flag", "human_check_recommended": False}

    if checkin:
        processed = process_checkin(
            athlete_id=athlete_id,
            recent_checkins=recent_checkins,
            **{k: v for k, v in checkin.items() if k not in {"athlete_id", "recent_checkins"}},
        )
        psych_flag = processed.get("psychological_support_flag") or psych_flag
        if psych_flag.get("human_check_recommended"):
            extra_reasons.extend(psych_flag.get("reasons") or [])
            escalate = True
        for flag in processed.get("pain_flags") or []:
            extra_reasons.append(flag)

    score = _compliance_score(compliance if isinstance(compliance, dict) else None)
    if score is not None and score < 60:
        extra_reasons.append("low_compliance")
        escalate = True
    if isinstance(compliance, dict) and compliance.get("missed_key_work"):
        extra_reasons.append("missed_key_work")
        escalate = True

    if upcoming_key_session:
        extra_reasons.append("planned_key_session_tomorrow")

    merged = _merge_level(base, extra_reasons, escalate)

    if merged.get("level") == "professional_review_recommended":
        intensity_gate = "do_not_prescribe_intensity"
    elif merged.get("level") == "coach_review_recommended":
        intensity_gate = "do_not_auto_progress"
    else:
        intensity_gate = "ok_to_auto_suggest"

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete_id,
        "decision_safety": {
            "level": merged.get("level"),
            "status": merged.get("status"),
            "reason": merged.get("reason") or (merged.get("reasons") or [None])[0],
            "reasons": merged.get("reasons") or [],
            "algorithm_action": merged.get("algorithm_action"),
            "human_action": merged.get("human_action"),
            "intensity_gate": intensity_gate,
            "safe_output": merged.get("safe_output"),
        },
        "psychological_support_flag": psych_flag,
        "limitations": [
            "Safety recommendations only — not medical advice or mental-health diagnosis.",
            "Coach must confirm before changing training load or gym prescription.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="decision_safety_engine",
        method="unified_safety_gate",
        confidence=0.7 if merged.get("status") == "ok" else 0.55,
    )
