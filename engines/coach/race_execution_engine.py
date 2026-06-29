"""Race execution plan — pacing, fueling and failure modes for coach review."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload

SCHEMA_VERSION = "race_execution_plan.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"

EVENT_PROFILES = {
    "granfondo": {"duration_h": 5.0, "intensity_cap_pct_mlss": 0.78, "cho_multiplier": 1.0},
    "time_trial": {"duration_h": 1.0, "intensity_cap_pct_mlss": 0.98, "cho_multiplier": 0.7},
    "criterium": {"duration_h": 1.5, "intensity_cap_pct_mlss": 0.92, "cho_multiplier": 1.1},
    "climbing": {"duration_h": 3.5, "intensity_cap_pct_mlss": 0.82, "cho_multiplier": 1.05},
}


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _curve_summary(metabolic_curves: Dict[str, Any], curve_id: str) -> Dict[str, Any]:
    curves = metabolic_curves.get("curves") if isinstance(metabolic_curves.get("curves"), dict) else metabolic_curves
    if not isinstance(curves, dict):
        return {}
    curve = curves.get(curve_id) or {}
    return curve.get("summary") if isinstance(curve.get("summary"), dict) else {}


def build_race_execution_plan(
    *,
    athlete_id: Optional[str] = None,
    target_event: str = "granfondo",
    metabolic_snapshot: Optional[Dict[str, Any]] = None,
    metabolic_curves: Optional[Dict[str, Any]] = None,
    twin_state: Optional[Dict[str, Any]] = None,
    race_simulation: Optional[Dict[str, Any]] = None,
    duration_h: Optional[float] = None,
) -> Dict[str, Any]:
    """Build coach-facing race execution plan from physiology and optional GPX simulation."""
    twin = twin_state or {}
    snapshot = metabolic_snapshot or twin.get("metabolic_snapshot") or {}
    curves = metabolic_curves or twin.get("metabolic_curves") or {}
    event = str(target_event or "granfondo").strip().lower().replace(" ", "_")
    profile = EVENT_PROFILES.get(event, EVENT_PROFILES["granfondo"])

    mlss = _num(snapshot.get("mlss_power_watts") or snapshot.get("mlss_power_w"))
    fatmax = _num(snapshot.get("fatmax_power_watts") or snapshot.get("fatmax_power_w"))
    w_prime = _num(snapshot.get("w_prime_j") or snapshot.get("w_prime"))
    duration = duration_h or profile["duration_h"]

    sim_prediction = {}
    if race_simulation:
        sim_prediction = race_simulation.get("prediction") or race_simulation.get("race_prediction") or {}
        if sim_prediction.get("estimated_time_h"):
            duration = float(sim_prediction["estimated_time_h"])

    fuel_summary = _curve_summary(curves, "session_fuel_demand")
    cho_g = _num(sim_prediction.get("estimated_carbohydrate_g")) or _num(fuel_summary.get("carbohydrate_g"))
    if cho_g is None and mlss:
        cho_g = duration * 55.0 * profile["cho_multiplier"]

    cap = profile["intensity_cap_pct_mlss"]
    pacing = {
        "first_hour": f"cap at {int(cap * 100)}% MLSS" if mlss else f"cap IF ~{cap:.2f}",
        "climbs": "avoid repeated efforts above 105% MLSS" if mlss else "limit repeated surges above threshold",
        "final_hour": "allow threshold surges only if CHO risk is controlled",
    }
    if fatmax and mlss:
        pacing["steady_sections"] = f"use {int(fatmax)}–{int(mlss * 0.85)} W band when course allows"

    failure_modes: List[str] = [
        "early carbohydrate overuse",
        "pacing too hard in the first third",
    ]
    if w_prime and w_prime < 15000:
        failure_modes.append("W_prime depletion on repeated climbs")
    if duration >= 3.5:
        failure_modes.append("durability drop after hour 3")
    if race_simulation and (race_simulation.get("course") or {}).get("elevation_gain_m", 0) > 2500:
        failure_modes.append("climb accumulation without recovery on descents")

    fueling = {
        "carbohydrate_availability": "high" if duration >= 3 else "moderate",
        "estimated_cho_demand_g": round(cho_g, 0) if cho_g is not None else None,
        "risk": "moderate" if duration >= 4 else "low",
    }

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete_id,
        "race_execution_plan": {
            "target_event": event,
            "duration_h": round(duration, 2),
            "pacing_strategy": pacing,
            "fueling_targets": fueling,
            "failure_modes": failure_modes,
            "anchors": {
                "mlss_w": mlss,
                "fatmax_w": fatmax,
                "w_prime_j": w_prime,
            },
        },
        "source_simulation": race_simulation is not None,
        "limitations": [
            "Race execution plan is model-guided — weather, tactics and nutrition execution can dominate outcomes.",
            "Use GPX simulation when available for course-specific pacing refinements.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="race_execution_engine",
        method="coach_race_execution",
        confidence=0.7 if mlss else 0.45,
    )
