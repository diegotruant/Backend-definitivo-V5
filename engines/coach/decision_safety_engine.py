"""Standalone decision safety for coach prescriptions and intensity progression."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.coach.checkin_engine import process_checkin
from engines.coach.prescription_safety import evaluate_prescription_safety
from engines.core.metric_contracts import (
    annotate_payload,
    compliance_score_value,
    unwrap_compliance_record,
)

SCHEMA_VERSION = "decision_safety.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"

_LEVEL_RANK = {
    "ok_to_auto_suggest": 0,
    "coach_review_recommended": 1,
    "professional_review_recommended": 2,
}


def _escalate_level(current: str, target: str) -> str:
    if _LEVEL_RANK.get(target, 0) > _LEVEL_RANK.get(current, 0):
        return target
    return current


def _context_escalation(
    *,
    pnei_context: Optional[Dict[str, Any]],
    endocrine_context: Optional[Dict[str, Any]],
    training_safety: Optional[Dict[str, Any]],
) -> tuple[str, List[str], bool]:
    reasons: List[str] = []
    level = "ok_to_auto_suggest"
    escalate = False

    pnei = pnei_context or {}
    if isinstance(pnei.get("pnei_context"), dict):
        pnei = pnei["pnei_context"]
    pnei_status = str(pnei.get("status") or "")
    if pnei_status == "professional_review":
        level = _escalate_level(level, "professional_review_recommended")
        reasons.extend(pnei.get("reasons") or ["pnei_professional_review"])
        escalate = True
    elif pnei_status in {"human_review", "caution"}:
        level = _escalate_level(level, "coach_review_recommended")
        reasons.extend(pnei.get("reasons") or [f"pnei_{pnei_status}"])
        escalate = True

    endo = endocrine_context or {}
    if isinstance(endo.get("endocrine_context"), dict):
        endo = endo["endocrine_context"]
    endo_status = str(endo.get("status") or "")
    if endo_status == "professional_review":
        level = _escalate_level(level, "professional_review_recommended")
        reasons.append("endocrine_professional_review")
        escalate = True
    elif endo_status == "caution":
        level = _escalate_level(level, "coach_review_recommended")
        reasons.append("endocrine_caution")
        escalate = True

    safety = training_safety or {}
    if isinstance(safety.get("training_safety"), dict):
        safety = safety["training_safety"]
    safety_status = str(safety.get("status") or "")
    if safety_status == "stop":
        level = _escalate_level(level, "professional_review_recommended")
        reasons.extend(safety.get("red_flags") or ["training_safety_stop"])
        escalate = True
    elif safety_status == "caution":
        level = _escalate_level(level, "coach_review_recommended")
        reasons.extend(safety.get("red_flags") or ["training_safety_caution"])
        escalate = True

    return level, sorted(set(reasons)), escalate


def _compliance_score(last_compliance: Optional[Dict[str, Any]]) -> Optional[float]:
    if not last_compliance:
        return None
    return compliance_score_value(last_compliance)


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
    pnei_context: Optional[Dict[str, Any]] = None,
    endocrine_context: Optional[Dict[str, Any]] = None,
    training_safety: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Unified safety envelope for intensity, gym and fueling decisions."""
    twin = twin_state or {}
    load = load_state or twin.get("load_state") or {}
    readiness = readiness_state or twin.get("readiness_state") or {}
    compliance = last_compliance
    if compliance is None and isinstance(twin.get("last_compliance_results"), list) and twin.get("last_compliance_results"):
        compliance = unwrap_compliance_record(twin["last_compliance_results"][0])

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

    compliance_record = unwrap_compliance_record(compliance) if isinstance(compliance, dict) else None
    score = _compliance_score(compliance_record or compliance)
    if score is not None and score < 60:
        extra_reasons.append("low_compliance")
        escalate = True
    if isinstance(compliance_record, dict) and compliance_record.get("missed_key_work"):
        extra_reasons.append("missed_key_work")
        escalate = True

    if upcoming_key_session:
        extra_reasons.append("planned_key_session_tomorrow")

    ctx_level, ctx_reasons, ctx_escalate = _context_escalation(
        pnei_context=pnei_context or twin.get("pnei_state"),
        endocrine_context=endocrine_context or twin.get("endocrine_context_state"),
        training_safety=training_safety or twin.get("training_safety_state"),
    )
    extra_reasons.extend(ctx_reasons)
    if ctx_escalate:
        escalate = True

    merged = _merge_level(base, extra_reasons, escalate)
    if _LEVEL_RANK.get(ctx_level, 0) > _LEVEL_RANK.get(merged.get("level", "ok_to_auto_suggest"), 0):
        merged["level"] = ctx_level
        if ctx_level == "professional_review_recommended":
            merged["status"] = "requires_professional_review"
            merged["algorithm_action"] = "do_not_prescribe_heavy_load"
            merged["human_action"] = "coach_or_medical_review"
        elif ctx_level == "coach_review_recommended":
            merged["status"] = "caution"
            merged["algorithm_action"] = "do_not_auto_progress"
            merged["human_action"] = "coach_check_in"

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
        "context_layers": {
            "pnei_considered": bool(pnei_context or twin.get("pnei_state")),
            "endocrine_considered": bool(endocrine_context or twin.get("endocrine_context_state")),
            "training_safety_considered": bool(training_safety or twin.get("training_safety_state")),
        },
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
