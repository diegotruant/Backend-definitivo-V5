"""Daily total energy analysis from wearable / Health Connect sync — not meal planning.

Classifies non-training energy load (e.g. physical jobs) for coach energy management.
Accepts totals reported by the athlete app (Oura, Google Health / Health Connect).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload, readiness_score_from_state
from engines.integrations.health_daily_normalizer import normalize_health_daily

SCHEMA_VERSION = "daily_energy.v1"
MEASUREMENT_TIER = "HEURISTIC"


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _estimate_bmr_kcal(
    *,
    weight_kg: Optional[float],
    height_cm: Optional[float],
    age: Optional[float],
    gender: Optional[str],
) -> Optional[float]:
    if weight_kg is None or height_cm is None or age is None:
        return None
    g = str(gender or "").upper()
    if g in {"F", "FEMALE", "W"}:
        return round(10 * weight_kg + 6.25 * height_cm - 5 * age - 161, 1)
    return round(10 * weight_kg + 6.25 * height_cm - 5 * age + 5, 1)


def _classify_daily_energy_load(total_kcal: float, weight_kg: Optional[float]) -> str:
    if weight_kg and weight_kg > 0:
        per_kg = total_kcal / weight_kg
        if per_kg < 28:
            return "low"
        if per_kg < 32:
            return "moderate"
        if per_kg < 38:
            return "high"
        return "very_high"
    if total_kcal < 2200:
        return "low"
    if total_kcal < 2600:
        return "moderate"
    if total_kcal < 3000:
        return "high"
    return "very_high"


def _classify_physical_job_load(non_training_kcal: float) -> str:
    if non_training_kcal < 250:
        return "sedentary"
    if non_training_kcal < 500:
        return "light"
    if non_training_kcal < 750:
        return "moderate"
    if non_training_kcal < 1000:
        return "high"
    return "very_high"


def _occupation_hint(athlete: Dict[str, Any]) -> Optional[str]:
    occ = str(
        athlete.get("occupation_load")
        or athlete.get("occupation")
        or athlete.get("job_type")
        or ""
    ).lower()
    if not occ:
        return None
    if any(token in occ for token in ("physical", "manual", "labor", "muratore", "builder", "warehouse")):
        return "physical_job"
    if any(token in occ for token in ("desk", "office", "sedentary")):
        return "sedentary"
    return occ


def build_daily_energy_analysis(
    *,
    health_daily: Dict[str, Any],
    athlete: Optional[Dict[str, Any]] = None,
    load_state: Optional[Dict[str, Any]] = None,
    training_calories_kcal: Optional[float] = None,
    twin_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Analyze reported daily calories and classify non-training energy burden."""
    twin = twin_state or {}
    athlete_data = athlete or twin.get("athlete_profile") or {}
    load = load_state or twin.get("load_state") or {}

    normalized = normalize_health_daily(health_daily)
    total = normalized.get("total_calories_kcal")
    active = normalized.get("active_calories_kcal")
    basal_reported = normalized.get("basal_calories_kcal")

    if total is None:
        return {
            "status": "insufficient_data",
            "schema_version": SCHEMA_VERSION,
            "reason": "total_calories_kcal required (or active + basal)",
            "normalized": normalized,
        }

    weight = _num(athlete_data.get("weight_kg"))
    height = _num(athlete_data.get("height_cm"))
    age = _num(athlete_data.get("age"))
    gender = athlete_data.get("gender")

    estimated_bmr = _estimate_bmr_kcal(weight_kg=weight, height_cm=height, age=age, gender=gender)
    basal = basal_reported if basal_reported is not None else estimated_bmr

    training_kcal = _num(training_calories_kcal)
    if training_kcal is None:
        training_kcal = _num(load.get("training_calories_kcal") or load.get("session_calories_kcal"))

    non_training_active: Optional[float] = None
    if active is not None:
        non_training_active = max(0.0, active - (training_kcal or 0.0))
    elif basal is not None:
        non_training_active = max(0.0, total - basal - (training_kcal or 0.0))

    neat_kcal: Optional[float] = None
    if basal is not None and training_kcal is not None:
        neat_kcal = max(0.0, total - basal - training_kcal)
    elif basal is not None and active is not None:
        neat_kcal = max(0.0, active - (training_kcal or 0.0))

    total_per_kg = round(total / weight, 2) if weight and weight > 0 else None
    training_share_pct: Optional[float] = None
    if training_kcal is not None and total > 0:
        training_share_pct = round(100.0 * training_kcal / total, 1)

    daily_load = _classify_daily_energy_load(total, weight)
    physical_load = (
        _classify_physical_job_load(non_training_active)
        if non_training_active is not None
        else "unknown"
    )

    coach_notes: List[str] = [
        "Daily energy context for coach load management — not a meal plan or calorie prescription.",
    ]
    red_flags: List[str] = []
    coach_flags: List[str] = []

    occupation = _occupation_hint(athlete_data)
    if occupation == "physical_job" and physical_load in {"high", "very_high"}:
        coach_notes.append(
            "High non-training energy expenditure consistent with a physical occupation — "
            "account for NEAT when planning bike volume and recovery."
        )

    if non_training_active is not None and non_training_active >= 700:
        coach_flags.append("high_non_training_load")
        coach_notes.append(
            f"Non-training active burn ~{int(non_training_active)} kcal — "
            "training stress is additive to occupational load."
        )

    if daily_load in {"high", "very_high"} and total >= 2800:
        coach_flags.append("elevated_daily_total_energy")
        coach_notes.append(
            f"Total daily burn ~{int(total)} kcal — typical for athletes with heavy daily activity outside cycling."
        )

    readiness_score = readiness_score_from_state(twin.get("readiness_state") or {})
    energy_availability_risk = "low"
    if (
        daily_load in {"high", "very_high"}
        and readiness_score is not None
        and readiness_score < 50
        and (training_kcal or 0) >= 400
    ):
        energy_availability_risk = "moderate"
        red_flags.append("low_energy_availability_risk")
        coach_notes.append(
            "High total expenditure with low readiness — review fuelling around key sessions."
        )
    elif daily_load == "very_high" and (training_kcal or 0) >= 600:
        energy_availability_risk = "moderate"

    acute = _num(load.get("acute_load"))
    if acute is not None and acute >= 80 and daily_load in {"high", "very_high"}:
        coach_flags.append("stacked_training_and_lifestyle_load")
        coach_notes.append("Elevated training load on top of high daily energy expenditure.")

    confidence = 0.72 if active is not None and basal is not None else 0.62
    if estimated_bmr is not None and basal_reported is None:
        confidence -= 0.05

    payload: Dict[str, Any] = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": MEASUREMENT_TIER,
        "not_a_diet": True,
        "date": normalized.get("date"),
        "source": normalized.get("source"),
        "reported": {
            "total_calories_kcal": total,
            "active_calories_kcal": active,
            "basal_calories_kcal": basal_reported,
            "steps": normalized.get("steps"),
            "distance_m": normalized.get("distance_m"),
        },
        "derived": {
            "estimated_bmr_kcal": estimated_bmr,
            "basal_used_kcal": basal,
            "training_calories_kcal": training_kcal,
            "non_training_active_kcal": round(non_training_active, 1) if non_training_active is not None else None,
            "neat_kcal": round(neat_kcal, 1) if neat_kcal is not None else None,
            "total_per_kg": total_per_kg,
            "training_share_pct": training_share_pct,
        },
        "classifications": {
            "daily_energy_load": daily_load,
            "physical_job_load": physical_load,
            "occupation_hint": occupation,
        },
        "coach_flags": coach_flags,
        "nutrition_energy_context": {
            "energy_availability_risk": energy_availability_risk,
            "low_energy_availability_risk": energy_availability_risk,
            "high_non_training_load": "high_non_training_load" in coach_flags,
        },
        "coach_notes": coach_notes,
        "red_flags": red_flags,
        "limitations": [
            "Wearable-reported calories are estimates — vendor models differ (Oura vs Google Health).",
            "Non-training load is inferred from active/basal totals minus logged training burn when supplied.",
            "Not a TDEE prescription, diet plan or medical nutrition assessment.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="daily_energy_engine",
        method="daily_total_analysis",
        confidence=confidence,
    )
