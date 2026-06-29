"""Testing scheduler — recommend when to re-test, not auto-schedule workouts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload

SCHEMA_VERSION = "testing_plan.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reliability(snapshot: Dict[str, Any], key: str) -> bool:
    expr = snapshot.get("expressiveness") or {}
    rel = expr.get("reliability") if isinstance(expr.get("reliability"), dict) else {}
    if key in rel:
        return bool(rel.get(key))
    return bool(expr.get(f"{key}_reliable", True))


def build_testing_plan(
    *,
    athlete_id: Optional[str] = None,
    metabolic_snapshot: Optional[Dict[str, Any]] = None,
    lactate_state: Optional[Dict[str, Any]] = None,
    twin_state: Optional[Dict[str, Any]] = None,
    season_phase: str = "base",
    days_since_last_lactate_test: Optional[int] = None,
) -> Dict[str, Any]:
    """Suggest priority tests to improve model calibration."""
    twin = twin_state or {}
    snapshot = metabolic_snapshot or twin.get("metabolic_snapshot") or {}
    lactate = lactate_state or twin.get("lactate_state") or {}
    recommendations: List[Dict[str, Any]] = []

    confidence = _num(snapshot.get("confidence_score")) or 0.0
    mlss_w = _num(snapshot.get("mlss_power_watts") or snapshot.get("mlss_power_w"))
    vlamax = _num(snapshot.get("estimated_vlamax_mmol_L_s") or snapshot.get("vlamax_mmol_L_s"))
    has_lactate = bool(lactate.get("thresholds") or lactate.get("latest_curve"))

    if not has_lactate and (not _reliability(snapshot, "mlss") or confidence < 0.55):
        recommendations.append({
            "priority": "high",
            "test": "lactate_step_test",
            "reason": "MLSS model confidence is low and no measured lactate curve is stored.",
            "expected_value": "Improve calibration of MLSS, lactate curve and substrate curves.",
        })

    if not _reliability(snapshot, "vlamax") or vlamax is None:
        recommendations.append({
            "priority": "high",
            "test": "sprint_15s_vlamax",
            "reason": "VLamax estimate is masked or missing from snapshot expressiveness.",
            "expected_value": "Anchor glycolytic phenotype and sprint-zone prescriptions.",
        })

    if mlss_w is None or not _reliability(snapshot, "mlss"):
        recommendations.append({
            "priority": "medium",
            "test": "critical_power_test",
            "reason": "CP/MLSS anchor is weak for threshold and pacing models.",
            "expected_value": "Stabilize threshold power and W' balance models.",
        })

    if not _reliability(snapshot, "fatmax"):
        recommendations.append({
            "priority": "medium",
            "test": "fatmax_lab_or_field_proxy",
            "reason": "FATmax/substrate curve relies on model estimate only.",
            "expected_value": "Improve substrate oxidation and fueling target confidence.",
        })

    if days_since_last_lactate_test is not None and days_since_last_lactate_test > 120 and has_lactate:
        recommendations.append({
            "priority": "low",
            "test": "lactate_retest",
            "reason": "Measured lactate thresholds are older than 120 days.",
            "expected_value": "Refresh threshold anchors after training block changes.",
        })

    if season_phase in {"build", "race"} and confidence < 0.65 and not recommendations:
        recommendations.append({
            "priority": "medium",
            "test": "field_fitness_check",
            "reason": "Entering key phase with moderate snapshot confidence.",
            "expected_value": "Validate zones before race-specific prescriptions.",
        })

    if not recommendations:
        recommendations.append({
            "priority": "low",
            "test": "maintain_current_calibration",
            "reason": "No urgent calibration gap detected from current TwinState.",
            "expected_value": "Continue training; retest after major block or phenotype shift.",
        })

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    recommendations.sort(key=lambda row: priority_rank.get(str(row.get("priority")), 9))

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete_id,
        "testing_recommendation": recommendations[0],
        "testing_recommendations": recommendations,
        "snapshot_confidence": confidence,
        "limitations": [
            "Testing suggestions support coach planning — not automatic test scheduling.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="testing_scheduler_engine",
        method="calibration_recommendations",
        confidence=0.66 if confidence >= 0.5 else 0.48,
    )
