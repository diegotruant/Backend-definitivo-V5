"""Performance fueling targets for cyclists — not diets or meal plans.

Uses metabolic curves, load and readiness to recommend carbohydrate
availability, recovery priorities and red flags.  Never outputs meal menus.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.coach.prescription_safety import evaluate_prescription_safety
from engines.core.metric_contracts import annotate_payload
from engines.metabolic.metabolic_coach_curves import build_metabolic_curves_report

SCHEMA_VERSION = "performance_fueling_targets.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"


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


def _readiness_level(readiness_state: Dict[str, Any]) -> str:
    score = _num(readiness_state.get("readiness_score") or readiness_state.get("score"))
    if score is None:
        return "unknown"
    if score < 45:
        return "low"
    if score < 65:
        return "moderate"
    return "normal"


def _load_stress(load_state: Dict[str, Any]) -> str:
    tsb = _num(load_state.get("tsb") or load_state.get("training_stress_balance"))
    if tsb is None:
        return "unknown"
    if tsb < -20:
        return "high"
    if tsb < -5:
        return "moderate"
    return "low"


def build_performance_fueling_targets(
    *,
    athlete: Optional[Dict[str, Any]] = None,
    twin_state: Optional[Dict[str, Any]] = None,
    metabolic_snapshot: Optional[Dict[str, Any]] = None,
    metabolic_curves: Optional[Dict[str, Any]] = None,
    load_state: Optional[Dict[str, Any]] = None,
    readiness_state: Optional[Dict[str, Any]] = None,
    session_context: str = "bike_endurance",
    strength_prescription: Optional[Dict[str, Any]] = None,
    injury_flags: Optional[Sequence[str]] = None,
    power_stream: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Return coach-facing fueling targets linked to TwinState physiology."""
    twin = twin_state or {}
    snapshot = metabolic_snapshot or twin.get("metabolic_snapshot") or {}
    load = load_state or twin.get("load_state") or {}
    readiness = readiness_state or twin.get("readiness_state") or {}
    athlete_data = athlete or twin.get("athlete_profile") or {}
    curves_in = metabolic_curves or twin.get("metabolic_curves") or {}

    weight = _num(athlete_data.get("weight_kg"))
    curves_report = curves_in
    if not curves_in.get("curves") and snapshot.get("status") == "success" and weight:
        curves_report = build_metabolic_curves_report(
            snapshot,
            weight_kg=weight,
            gender=athlete_data.get("gender"),
            training_years=_num(athlete_data.get("training_years")),
            discipline=athlete_data.get("discipline"),
            power_stream=power_stream,
            include_curves=["session_fuel_demand", "post_effort_recovery", "substrate_oxidation"],
        )

    fuel_summary = _curve_summary(curves_report, "session_fuel_demand")
    recovery_summary = _curve_summary(curves_report, "post_effort_recovery")
    cho_g = _num(fuel_summary.get("carbohydrate_g"))
    recovery_h = _num(recovery_summary.get("estimated_recovery_hours"))

    safety = evaluate_prescription_safety(
        injury_flags=injury_flags,
        readiness_state=readiness,
        load_state=load,
    )

    readiness_level = _readiness_level(readiness)
    load_stress = _load_stress(load)
    has_strength = bool(strength_prescription) or "strength" in session_context or "gym" in session_context

    cho_availability = "moderate"
    protein_priority = "normal"
    glycogen_risk = "low"
    hydration = "normal"
    red_flags: List[str] = []
    coach_notes: List[str] = [
        "Targets describe energetic availability for performance — not a meal plan.",
    ]

    if cho_g is not None and cho_g >= 180:
        cho_availability = "high"
        coach_notes.append("High session CHO demand estimated — prioritize availability around key bike sessions.")
    elif cho_g is not None and cho_g < 80:
        cho_availability = "moderate"

    if has_strength:
        protein_priority = "high"
        coach_notes.append(
            "Heavy strength blocks increase recovery protein priority; this is separate from on-bike CHO fueling."
        )
        if cho_availability == "high":
            glycogen_risk = "moderate"
            coach_notes.append(
                "Strength plus high CHO-demand bike work increases glycogen risk if availability is chronically low."
            )

    if readiness_level == "low" or load_stress == "high":
        cho_availability = "moderate" if cho_availability == "high" else cho_availability
        red_flags.append("low_energy_availability_risk")
        coach_notes.append("Avoid chronic low-energy availability around heavy training blocks.")

    if recovery_h is not None and recovery_h >= 36:
        protein_priority = "high"
        hydration = "high"
        coach_notes.append("Extended recovery window — prioritize repletion before the next key session.")

    if safety.get("status") == "requires_professional_review":
        red_flags.append(safety.get("reason", "medical_review"))
        coach_notes.append("Medical or injury flags present — fueling targets require coach review.")

    if "reds_risk" in [str(f).lower() for f in (injury_flags or [])]:
        red_flags.append("reds_risk_flag")
        coach_notes.append("RED-S risk flagged — do not prescribe aggressive energy restriction.")

    payload: Dict[str, Any] = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "not_a_diet": True,
        "session_context": session_context,
        "targets": {
            "carbohydrate_availability": cho_availability,
            "protein_recovery_priority": protein_priority,
            "glycogen_risk": glycogen_risk,
            "hydration_priority": hydration,
        },
        "estimated_demands": {
            "session_carbohydrate_g": cho_g,
            "estimated_recovery_hours": recovery_h,
        },
        "coach_notes": coach_notes,
        "red_flags": red_flags,
        "decision_safety": safety,
        "limitations": [
            "Performance fueling targets only — no meal menus, macros by food or medical nutrition therapy.",
            "CHO demand estimates depend on modeled substrate curves and power data when supplied.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="performance_fueling_engine",
        method="availability_targets",
        confidence=0.64 if cho_g is not None else 0.52,
    )
