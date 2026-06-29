"""Athlete subjective check-in — signals for coach review, not mental-health diagnosis."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.core.metric_contracts import annotate_payload

SCHEMA_VERSION = "athlete_checkin.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _scale_1_10(value: Any) -> Optional[float]:
    n = _num(value)
    if n is None:
        return None
    return max(1.0, min(10.0, n))


def _psychological_support_flag(
  *,
  motivation: Optional[float],
  stress: Optional[float],
  recent_history: Sequence[Dict[str, Any]],
  pain_flags: Sequence[str],
) -> Dict[str, Any]:
    """Flag when a human coach conversation is recommended — not a diagnosis."""
    low_motivation_days = 0
    high_stress_days = 0
    for row in recent_history:
        m = _scale_1_10(row.get("motivation"))
        s = _scale_1_10(row.get("stress"))
        if m is not None and m <= 4:
            low_motivation_days += 1
        if s is not None and s >= 8:
            high_stress_days += 1

    if motivation is not None and motivation <= 4:
        low_motivation_days += 1

    reasons: List[str] = []
    if low_motivation_days >= 5:
        reasons.append("motivation_low_for_5_days")
    if stress is not None and stress >= 8:
        reasons.append("subjective_stress_high")
    if high_stress_days >= 3:
        reasons.append("sustained_stress_reports")
    if pain_flags:
        reasons.append("pain_reported_in_checkin")

    if not reasons:
        return {
            "status": "no_flag",
            "human_check_recommended": False,
            "safe_action": None,
        }

    return {
        "status": "human_check_recommended",
        "human_check_recommended": True,
        "reason": reasons[0],
        "reasons": reasons,
        "safe_action": "Coach conversation recommended. Do not escalate training load automatically.",
        "not_a_diagnosis": True,
    }


def process_checkin(
    *,
    athlete_id: Optional[str] = None,
    sleep_quality: Optional[float] = None,
    stress: Optional[float] = None,
    motivation: Optional[float] = None,
    muscle_soreness: Optional[float] = None,
    joint_pain: Optional[float] = None,
    perceived_fatigue: Optional[float] = None,
    willingness_to_train: Optional[float] = None,
    notes: Optional[str] = None,
    pain_flags: Optional[Sequence[str]] = None,
    recent_checkins: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Normalize a subjective check-in and emit coach-facing flags."""
    sleep = _scale_1_10(sleep_quality)
    stress_n = _scale_1_10(stress)
    motivation_n = _scale_1_10(motivation)
    soreness = _scale_1_10(muscle_soreness)
    joint = _scale_1_10(joint_pain)
    fatigue = _scale_1_10(perceived_fatigue)
    willingness = _scale_1_10(willingness_to_train)
    flags = list(pain_flags or [])
    if joint is not None and joint >= 7:
        flags.append("joint_pain_reported")
    if soreness is not None and soreness >= 8:
        flags.append("high_muscle_soreness")

    psych = _psychological_support_flag(
        motivation=motivation_n,
        stress=stress_n,
        recent_history=list(recent_checkins or []),
        pain_flags=flags,
    )

    summary = {
        "sleep_quality": sleep,
        "stress": stress_n,
        "motivation": motivation_n,
        "muscle_soreness": soreness,
        "joint_pain": joint,
        "perceived_fatigue": fatigue,
        "willingness_to_train": willingness,
    }

    coach_notes: List[str] = []
    if fatigue is not None and fatigue >= 8:
        coach_notes.append("High perceived fatigue — verify recovery before intensity.")
    if willingness is not None and willingness <= 4:
        coach_notes.append("Low willingness to train — subjective check-in before prescribing load.")

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete_id,
        "checkin_summary": summary,
        "pain_flags": sorted(set(flags)),
        "notes": notes,
        "psychological_support_flag": psych,
        "coach_notes": coach_notes,
        "limitations": [
            "Subjective check-in only — not a mental-health assessment or diagnosis.",
            "Use alongside objective load, readiness and coach judgment.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="checkin_engine",
        method="subjective_checkin",
        confidence=0.55,
    )
