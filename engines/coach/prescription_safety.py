"""Shared safety gate for coach prescriptions (strength, fueling, intensity)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.core.metric_contracts import normalize_readiness_score

MEDICAL_REVIEW_FLAGS = frozenset({
    "injury",
    "acute_pain",
    "post_surgery",
    "post_operatorio",
    "underweight",
    "reds_risk",
    "diabetes",
    "medical_condition",
    "eating_disorder",
})

ACUTE_PAIN_FLAGS = frozenset({"acute_pain", "joint_pain", "back_pain"})


def _as_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value.strip().lower()] if value.strip() else []
    out: List[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip().lower()
        if text:
            out.append(text)
    return out


def _readiness_score(readiness_state: Optional[Dict[str, Any]]) -> Optional[float]:
    if not readiness_state:
        return None
    for key in ("readiness_score", "score", "overall"):
        try:
            value = readiness_state.get(key)
        except (TypeError, ValueError):
            continue
        normalized = normalize_readiness_score(value)
        if normalized is not None:
            return normalized
    return None


def _tsb(load_state: Optional[Dict[str, Any]]) -> Optional[float]:
    if not load_state:
        return None
    for key in ("tsb", "training_stress_balance"):
        try:
            return float(load_state.get(key))
        except (TypeError, ValueError):
            continue
    return None


def _atl(load_state: Optional[Dict[str, Any]]) -> Optional[float]:
    if not load_state:
        return None
    for key in ("atl", "acute_training_load"):
        try:
            return float(load_state.get(key))
        except (TypeError, ValueError):
            continue
    return None


def evaluate_prescription_safety(
    *,
    injury_flags: Optional[Sequence[str]] = None,
    readiness_state: Optional[Dict[str, Any]] = None,
    load_state: Optional[Dict[str, Any]] = None,
    medical_flags: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Return decision_safety envelope used by strength and fueling engines."""
    flags = _as_list(injury_flags) + _as_list(medical_flags)
    reasons: List[str] = []
    level = "ok_to_auto_suggest"

    medical_hits = [f for f in flags if f in MEDICAL_REVIEW_FLAGS or any(m in f for m in MEDICAL_REVIEW_FLAGS)]
    if medical_hits:
        return {
            "level": "professional_review_recommended",
            "status": "requires_professional_review",
            "reason": "injury_or_medical_flag_present",
            "reasons": sorted(set(medical_hits)),
            "algorithm_action": "do_not_prescribe_heavy_load",
            "human_action": "coach_or_medical_review",
            "safe_output": "mobility_and_low_load_technical_work_only",
        }

    readiness = _readiness_score(readiness_state)
    tsb = _tsb(load_state)
    atl = _atl(load_state)

    if readiness is not None and readiness < 40:
        reasons.append("readiness_very_low")
        level = "coach_review_recommended"
    elif readiness is not None and readiness < 55:
        reasons.append("readiness_low")

    if tsb is not None and tsb < -25:
        reasons.append("tsb_very_negative")
        level = "coach_review_recommended"
    elif tsb is not None and tsb < -10:
        reasons.append("tsb_negative")

    if atl is not None and atl > 100:
        reasons.append("atl_high")
        if level == "ok_to_auto_suggest":
            level = "coach_review_recommended"

    if level == "coach_review_recommended":
        return {
            "level": level,
            "status": "caution",
            "reason": reasons[0] if reasons else "load_or_readiness_caution",
            "reasons": reasons,
            "algorithm_action": "reduce_volume_and_avoid_heavy_lower_body",
            "human_action": "coach_check_in",
            "safe_output": "technique_mobility_or_deload",
        }

    return {
        "level": level,
        "status": "ok",
        "reasons": reasons,
        "algorithm_action": "may_prescribe_per_model",
        "human_action": None,
        "safe_output": None,
    }
