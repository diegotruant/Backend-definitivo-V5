"""Endocrine context — energy availability and recovery risk proxies, not hormone diagnosis."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.core.metric_contracts import annotate_payload, readiness_score_from_state

SCHEMA_VERSION = "endocrine_context.v1"
RISK_MODEL = "RISK_MODEL"
LAB_REPORTED = "LAB_REPORTED"


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_energy_availability_risk(
    *,
    nutrition_energy: Optional[Dict[str, Any]] = None,
    weight_trend: Optional[str] = None,
    fuel_deficit_g: Optional[float] = None,
    checkin: Optional[Dict[str, Any]] = None,
    performance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    nutrition = nutrition_energy or {}
    checkin = checkin or {}
    perf = performance or {}

    score = 0.0
    reasons: List[str] = []

    lea = str(nutrition.get("low_energy_availability_risk") or nutrition.get("energy_availability_risk") or "")
    if lea in {"moderate", "high"}:
        score += 0.45 if lea == "moderate" else 0.7
        reasons.append(f"low_energy_availability_risk_{lea}")

    red_flags = [str(f).lower() for f in (nutrition.get("red_flags") or [])]
    if "low_energy_availability_risk" in red_flags or "reds_risk_flag" in red_flags:
        score = max(score, 0.65)
        reasons.append("reds_risk_flag")

    deficit = fuel_deficit_g or _num(nutrition.get("session_fuel_deficit_g"))
    if deficit is not None and deficit >= 60:
        score += 0.25
        reasons.append("session_fuel_deficit_high")

    trend = str(weight_trend or nutrition.get("weight_trend") or "").lower()
    if trend in {"down_fast", "rapid_loss", "down"}:
        score += 0.35 if "fast" in trend or trend == "down_fast" else 0.2
        reasons.append("weight_trend_down")

    fatigue = _num(checkin.get("perceived_fatigue") or checkin.get("fatigue"))
    motivation = _num(checkin.get("motivation"))
    if fatigue is not None and fatigue >= 8:
        score += 0.15
        reasons.append("persistent_fatigue")
    if motivation is not None and motivation <= 4:
        score += 0.1
        reasons.append("low_motivation")

    if perf.get("power_drop") or perf.get("declining_performance"):
        score += 0.15
        reasons.append("declining_performance")

    risk = "high" if score >= 0.65 else "moderate" if score >= 0.35 else "low"
    return {"risk": risk, "score": round(min(1.0, score), 2), "reasons": sorted(set(reasons))}


def classify_stress_axis_load(
    *,
    load_state: Optional[Dict[str, Any]] = None,
    readiness_state: Optional[Dict[str, Any]] = None,
    sleep: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    load = load_state or {}
    readiness = readiness_state or {}
    sleep = sleep or {}

    score = 0.0
    reasons: List[str] = []
    tsb = _num(load.get("tsb") or load.get("training_stress_balance"))
    if tsb is not None and tsb < -25:
        score += 0.4
        reasons.append("tsb_very_negative")
    elif tsb is not None and tsb < -12:
        score += 0.2
        reasons.append("tsb_negative")

    if load.get("acute_load_spike"):
        score += 0.25
        reasons.append("acute_load_spike")

    readiness_score = readiness_score_from_state(readiness)
    if readiness_score is not None and readiness_score < 45:
        score += 0.25
        reasons.append("readiness_low")

    sleep_h = _num(sleep.get("sleep_hours_7d") or sleep.get("hours"))
    if sleep_h is not None and sleep_h < 6.0:
        score += 0.2
        reasons.append("sleep_restricted")

    load_level = "high" if score >= 0.55 else "moderate" if score >= 0.3 else "low"
    return {"load": load_level, "score": round(min(1.0, score), 2), "reasons": sorted(set(reasons))}


def classify_reproductive_axis_context(
    *,
    cycle_context: Optional[Dict[str, Any]] = None,
    female_athlete_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Optional self-reported context — never auto-prescribe from cycle."""
    cycle = cycle_context or female_athlete_context or {}
    if not cycle:
        return {
            "status": "not_reported",
            "coach_note": "No cycle context provided.",
            "professional_review_recommended": False,
        }

    irregular = bool(cycle.get("menstrual_irregularity") or cycle.get("amenorrhea_reported"))
    symptoms = cycle.get("symptoms") or []
    note = (
        "Menstrual irregularity reported — professional review recommended before load increase."
        if irregular
        else "Use subjective symptoms and readiness; do not auto-prescribe from cycle phase."
    )
    return {
        "status": "optional_context_available",
        "irregularity_reported": irregular,
        "symptoms_reported": list(symptoms) if isinstance(symptoms, list) else [],
        "coach_note": note,
        "professional_review_recommended": irregular,
        "not_a_diagnosis": True,
    }


def _biomarker_flags(biomarkers: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not biomarkers:
        return {"available": False, "flags": [], "requires_professional_interpretation": True}

    flags: List[str] = []
    markers = biomarkers if isinstance(biomarkers, dict) else {}
    for key, meta in markers.items():
        if not isinstance(meta, dict):
            continue
        status = str(meta.get("status") or meta.get("classification") or "").lower()
        if status in {"low", "below_range", "deficient"}:
            flags.append(f"{key}_below_range_reported")
        elif status in {"high", "above_range"}:
            flags.append(f"{key}_above_range_reported")

    return {
        "available": True,
        "flags": sorted(set(flags)),
        "requires_professional_interpretation": True,
        "measurement_tier": LAB_REPORTED,
    }


def build_endocrine_context(
    *,
    athlete_id: Optional[str] = None,
    twin_state: Optional[Dict[str, Any]] = None,
    nutrition_energy: Optional[Dict[str, Any]] = None,
    load_state: Optional[Dict[str, Any]] = None,
    readiness_state: Optional[Dict[str, Any]] = None,
    checkin: Optional[Dict[str, Any]] = None,
    sleep: Optional[Dict[str, Any]] = None,
    performance: Optional[Dict[str, Any]] = None,
    weight_trend: Optional[str] = None,
    fuel_deficit_g: Optional[float] = None,
    cycle_context: Optional[Dict[str, Any]] = None,
    female_athlete_context: Optional[Dict[str, Any]] = None,
    biomarkers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build endocrine risk context from proxies and optional lab-reported biomarkers."""
    twin = twin_state or {}
    nutrition = nutrition_energy or twin.get("nutrition_performance_state") or {}
    load = load_state or twin.get("load_state") or {}
    readiness = readiness_state or twin.get("readiness_state") or {}
    checkin_data = checkin or twin.get("checkin_state") or {}
    if isinstance(checkin_data, dict) and checkin_data.get("checkin_summary"):
        merged_checkin = {**checkin_data.get("checkin_summary", {}), **checkin_data}
    else:
        merged_checkin = checkin_data if isinstance(checkin_data, dict) else {}

    energy = classify_energy_availability_risk(
        nutrition_energy=nutrition,
        weight_trend=weight_trend,
        fuel_deficit_g=fuel_deficit_g,
        checkin=merged_checkin,
        performance=performance,
    )
    stress_axis = classify_stress_axis_load(
        load_state=load,
        readiness_state=readiness,
        sleep=sleep or twin.get("sleep_state") or {},
    )
    reproductive = classify_reproductive_axis_context(
        cycle_context=cycle_context,
        female_athlete_context=female_athlete_context,
    )
    biomarker_ctx = _biomarker_flags(biomarkers)

    status = "ok"
    if reproductive.get("professional_review_recommended") or energy["risk"] == "high":
        status = "professional_review"
    elif energy["risk"] == "moderate" or stress_axis["load"] in {"moderate", "high"}:
        status = "caution"

    if biomarker_ctx.get("available") and biomarker_ctx.get("flags"):
        status = "professional_review"

    permission = "normal"
    avoid: List[str] = []
    allowed: List[str] = ["prescribed_training"]
    coach_action = "Routine monitoring."

    if status == "professional_review":
        permission = "professional_review"
        avoid = ["VO2max_block", "heavy_gym_progression", "weight_loss_phase", "high_intensity"]
        allowed = ["endurance_easy", "mobility", "technical_work"]
        coach_action = "Refer to qualified clinician/dietitian before further load increase."
    elif status == "caution":
        permission = "modify"
        avoid = ["VO2max_block", "heavy_gym_progression", "weight_loss_phase"]
        allowed = ["endurance_easy", "mobility", "technical_work"]
        coach_action = "Do not progress load this week; check fueling and recovery."

    tier = LAB_REPORTED if biomarker_ctx.get("available") else RISK_MODEL

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": tier,
        "athlete_id": athlete_id,
        "endocrine_context": {
            "status": status,
            "subsystems": {
                "energy_availability": energy,
                "stress_axis": stress_axis,
                "anabolic_recovery": {
                    "suppression_risk": "possible" if energy["risk"] != "low" and stress_axis["load"] != "low" else "low",
                    "reasons": sorted(set(energy.get("reasons", []) + stress_axis.get("reasons", []))),
                },
                "reproductive_axis": reproductive,
                "biomarker_context": biomarker_ctx,
            },
            "training_decision": {
                "permission": permission,
                "avoid": avoid,
                "allowed": allowed,
                "coach_action": coach_action,
            },
            "requires_professional_interpretation": biomarker_ctx.get("available", False) or status == "professional_review",
        },
        "limitations": [
            "This is not a medical diagnosis.",
            "Hormonal interpretation requires qualified clinical review.",
            "Never use proxy models to suggest hormone therapy or supplements.",
        ],
    }
    conf = 0.5 if tier == RISK_MODEL else 0.65
    if energy["reasons"] and stress_axis["reasons"]:
        conf = min(0.78, conf + 0.1)
    return annotate_payload(
        payload,
        module_name="endocrine_context_engine",
        method="build_endocrine_context",
        confidence=conf,
    )
