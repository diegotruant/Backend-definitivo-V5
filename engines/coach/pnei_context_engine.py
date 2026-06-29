"""PNEI context — psycho-neuro-endocrine-immune risk layer, not diagnosis."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.core.metric_contracts import annotate_payload, readiness_score_from_state

SCHEMA_VERSION = "pnei_context.v1"
RISK_MODEL = "RISK_MODEL"


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _scale(value: Any) -> Optional[float]:
    n = _num(value)
    if n is None:
        return None
    return max(1.0, min(10.0, n))


def _strain_level(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "moderate"
    return "low"


def classify_psychological_strain(
    *,
    checkin: Optional[Dict[str, Any]] = None,
    recent_checkins: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    checkin = checkin or {}
    stress = _scale(checkin.get("stress"))
    motivation = _scale(checkin.get("motivation"))
    fatigue = _scale(checkin.get("perceived_fatigue") or checkin.get("fatigue"))
    mood = _scale(checkin.get("mood"))

    score = 0.0
    reasons: List[str] = []
    if stress is not None and stress >= 8:
        score += 0.35
        reasons.append("subjective_stress_high")
    if motivation is not None and motivation <= 4:
        score += 0.3
        reasons.append("motivation_low")
    if fatigue is not None and fatigue >= 8:
        score += 0.25
        reasons.append("perceived_fatigue_high")
    if mood is not None and mood <= 4:
        score += 0.2
        reasons.append("mood_low")

    low_mot_days = sum(
        1 for row in (recent_checkins or [])
        if isinstance(row, dict) and (_scale(row.get("motivation")) or 10) <= 4
    )
    if motivation is not None and motivation <= 4:
        low_mot_days += 1
    if low_mot_days >= 5:
        score = max(score, 0.65)
        reasons.append("motivation_low_for_5_days")

    return {
        "strain": _strain_level(score),
        "score": round(min(1.0, score), 2),
        "reasons": sorted(set(reasons)),
    }


def classify_autonomic_strain(
    *,
    readiness_state: Optional[Dict[str, Any]] = None,
    load_state: Optional[Dict[str, Any]] = None,
    sleep: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    readiness = readiness_state or {}
    load = load_state or {}
    sleep = sleep or {}

    hrv_baseline = _num(readiness.get("hrv_baseline") or readiness.get("hrv_rmssd_baseline"))
    hrv_7d = _num(readiness.get("hrv_7d") or readiness.get("hrv_rmssd_7d") or readiness.get("hrv_rmssd"))
    rhr_baseline = _num(readiness.get("resting_hr_baseline") or readiness.get("rhr_baseline"))
    rhr_7d = _num(readiness.get("resting_hr_7d") or readiness.get("rhr_7d") or readiness.get("resting_hr"))
    sleep_hours = _num(sleep.get("sleep_hours_7d") or sleep.get("hours"))
    sleep_quality = _num(sleep.get("sleep_quality"))

    score = 0.0
    reasons: List[str] = []

    if hrv_baseline and hrv_7d and hrv_7d < hrv_baseline * 0.85:
        score += 0.35
        reasons.append("hrv_below_baseline")
    if rhr_baseline and rhr_7d and rhr_7d > rhr_baseline + 5:
        score += 0.3
        reasons.append("resting_hr_elevated")
    if sleep_hours is not None and sleep_hours < 6.5:
        score += 0.25
        reasons.append("sleep_hours_low")
    if sleep_quality is not None and sleep_quality < 0.5:
        score += 0.2
        reasons.append("sleep_quality_low")

    tsb = _num(load.get("tsb") or load.get("training_stress_balance"))
    if tsb is not None and tsb < -20:
        score += 0.25
        reasons.append("acute_load_spike")
    if load.get("acute_load_spike"):
        score += 0.2
        reasons.append("acute_load_spike")

    readiness_score = readiness_score_from_state(readiness)
    if readiness_score is not None and readiness_score < 50:
        score += 0.2
        reasons.append("readiness_low")

    return {
        "strain": _strain_level(score),
        "score": round(min(1.0, score), 2),
        "reasons": sorted(set(reasons)),
    }


def classify_immune_risk(
    *,
    checkin: Optional[Dict[str, Any]] = None,
    illness_symptoms: Optional[bool] = None,
    recent_illness_count: Optional[int] = None,
) -> Dict[str, Any]:
    checkin = checkin or {}
    symptoms = illness_symptoms
    if symptoms is None:
        symptoms = bool(checkin.get("illness_symptoms") or checkin.get("sore_throat"))

    score = 0.0
    reasons: List[str] = []
    if symptoms:
        score = 0.85
        reasons.append("illness_symptoms_reported")
    if recent_illness_count is not None and recent_illness_count >= 2:
        score = max(score, 0.55)
        reasons.append("recurrent_illness_reports")

    return {
        "risk": "high" if score >= 0.7 else "moderate" if score >= 0.35 else "low",
        "score": round(score, 2),
        "reasons": reasons,
    }


def _training_permission(
    status: str,
    *,
    immune_high: bool,
) -> Dict[str, Any]:
    if status == "professional_review" or immune_high:
        return {
            "permission": "stop_and_review",
            "avoid": ["VO2max", "heavy_gym", "anaerobic_intervals", "high_intensity"],
            "allowed": ["rest", "mobility", "easy_walk"],
            "coach_action": "Human review before any intensity. Consider rest if illness symptoms present.",
        }
    if status == "human_review":
        return {
            "permission": "hold_intensity",
            "avoid": ["VO2max", "heavy_gym", "anaerobic_intervals"],
            "allowed": ["zone2", "mobility", "technical_skills"],
            "coach_action": "Coach check-in before intensity progression.",
        }
    if status == "caution":
        return {
            "permission": "modify",
            "avoid": ["VO2max_block", "heavy_gym_progression"],
            "allowed": ["zone2", "endurance_easy", "mobility"],
            "coach_action": "Reduce intensity or volume; avoid stacking stressors.",
        }
    return {
        "permission": "normal",
        "avoid": [],
        "allowed": ["prescribed_training"],
        "coach_action": "Routine monitoring.",
    }


def build_pnei_context(
    *,
    athlete_id: Optional[str] = None,
    twin_state: Optional[Dict[str, Any]] = None,
    load_state: Optional[Dict[str, Any]] = None,
    readiness_state: Optional[Dict[str, Any]] = None,
    checkin: Optional[Dict[str, Any]] = None,
    recent_checkins: Optional[Sequence[Dict[str, Any]]] = None,
    sleep: Optional[Dict[str, Any]] = None,
    nutrition_energy: Optional[Dict[str, Any]] = None,
    performance: Optional[Dict[str, Any]] = None,
    illness_symptoms: Optional[bool] = None,
    endocrine_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build PNEI risk context from non-invasive proxy signals."""
    twin = twin_state or {}
    load = load_state or twin.get("load_state") or {}
    readiness = readiness_state or twin.get("readiness_state") or {}
    checkin_data = checkin or twin.get("checkin_state") or {}
    if isinstance(checkin_data, dict) and checkin_data.get("checkin_summary"):
        merged_checkin = {**checkin_data.get("checkin_summary", {}), **checkin_data}
    else:
        merged_checkin = checkin_data if isinstance(checkin_data, dict) else {}

    sleep_ctx = sleep or twin.get("sleep_state") or {}
    nutrition = nutrition_energy or twin.get("nutrition_performance_state") or {}
    perf = performance or {}
    endocrine = endocrine_context or twin.get("endocrine_context_state") or {}

    psych = classify_psychological_strain(checkin=merged_checkin, recent_checkins=recent_checkins)
    autonomic = classify_autonomic_strain(readiness_state=readiness, load_state=load, sleep=sleep_ctx)
    immune = classify_immune_risk(checkin=merged_checkin, illness_symptoms=illness_symptoms)

    energy_risk = str(
        nutrition.get("energy_availability_risk")
        or (endocrine.get("subsystems") or {}).get("energy_availability", {}).get("risk")
        or nutrition.get("red_flags")
        or "unknown"
    )
    if isinstance(energy_risk, list):
        energy_risk = "moderate" if energy_risk else "low"

    global_index = (
        psych["score"] * 0.3
        + autonomic["score"] * 0.35
        + immune["score"] * 0.2
        + (0.25 if str(energy_risk) in {"moderate", "high"} else 0.0)
    )
    if perf.get("failed_key_sessions", 0) >= 2:
        global_index = min(1.0, global_index + 0.15)
    if perf.get("power_drop") or perf.get("rpe_decoupling"):
        global_index = min(1.0, global_index + 0.1)

    status = "ok"
    if immune["risk"] == "high" or str(endocrine.get("status")) == "professional_review":
        status = "professional_review"
    elif global_index >= 0.65 or psych["strain"] == "high" or autonomic["strain"] == "high":
        status = "human_review"
    elif global_index >= 0.4 or psych["strain"] == "moderate" or autonomic["strain"] == "moderate":
        status = "caution"

    reasons = sorted(
        set(
            psych.get("reasons", [])
            + autonomic.get("reasons", [])
            + immune.get("reasons", [])
        )
    )
    if str(energy_risk) in {"moderate", "high"}:
        reasons.append("energy_availability_risk")

    training = _training_permission(status, immune_high=immune["risk"] == "high")

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": RISK_MODEL,
        "athlete_id": athlete_id,
        "pnei_context": {
            "status": status,
            "global_stress_index": round(min(1.0, global_index), 2),
            "subsystems": {
                "psychological": psych,
                "autonomic": autonomic,
                "endocrine_energy": {
                    "risk": energy_risk if isinstance(energy_risk, str) else "moderate",
                    "source": "nutrition_or_endocrine_proxy",
                },
                "immune": immune,
            },
            "training_decision": training,
            "reasons": reasons,
            "human_action": training["coach_action"],
        },
        "limitations": [
            "This is not a medical diagnosis.",
            "Immune and endocrine status are inferred from proxy data unless biomarkers are provided.",
            "HRV and resting HR must be interpreted as individual trends, not absolute values.",
        ],
    }
    conf = 0.45
    if psych["reasons"] or autonomic["reasons"]:
        conf = 0.62
    if psych["reasons"] and autonomic["reasons"]:
        conf = 0.72
    return annotate_payload(
        payload,
        module_name="pnei_context_engine",
        method="build_pnei_context",
        confidence=conf,
    )
