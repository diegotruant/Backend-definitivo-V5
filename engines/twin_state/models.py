"""Canonical, versioned TwinState model.

The frontend and database should persist one JSON blob instead of trying to
recompose profile snapshots, rolling curves, load state, calendar state and
sensor quality from many endpoint-specific payloads.  The object is intentionally
plain JSON: stable to serialize, replay and migrate.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

TWIN_STATE_SCHEMA_VERSION = "twin_state.v1"

_REQUIRED_TOP_LEVEL = {
    "schema_version",
    "athlete_id",
    "created_at",
    "updated_at",
    "athlete_profile",
    "measured_anchor",
    "metabolic_snapshot",
    "rolling_power_curve",
    "load_state",
    "readiness_state",
    "sensor_quality",
    "workout_calendar_state",
    "last_compliance_results",
    "team_calibration_state",
    "state_confidence",
    "warnings",
    "event_log",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_clean(obj: Any) -> Any:
    """Return a JSON-safe copy: no numpy scalars, NaN or Inf."""
    if isinstance(obj, dict):
        return {str(k): _json_clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_json_clean(v) for v in obj.tolist()]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        obj = float(obj)
    if isinstance(obj, float):
        return None if (np.isnan(obj) or np.isinf(obj)) else obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _as_dict(value: Any) -> Dict[str, Any]:
    return _json_clean(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return _json_clean(value) if isinstance(value, list) else []


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(out) or np.isinf(out):
        return None
    return out


def _first_num(source: Dict[str, Any], names: Iterable[str]) -> Optional[float]:
    for name in names:
        value = _num(source.get(name))
        if value is not None:
            return value
    return None


def _extract_metabolic_metrics(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize common metabolic field names into a frontend-friendly summary."""
    if not snapshot:
        return {}
    estimates = _as_dict(snapshot.get("estimates"))
    metrics = _as_dict(snapshot.get("metrics"))
    flat = {**snapshot, **estimates, **metrics}
    return {
        "cp_w": _first_num(flat, ("cp_w", "critical_power_w", "mlss_w", "mlss", "mlss_watts")),
        "w_prime_j": _first_num(flat, ("w_prime_j", "wprime_j", "w_prime", "w_prime_kj")),
        "vo2max_ml_kg_min": _first_num(flat, ("vo2max", "vo2max_ml_kg_min", "vo2max_estimate")),
        "vlamax_mmol_l_s": _first_num(flat, ("vlamax", "vlamax_mmol_l_s")),
        "fatmax_w": _first_num(flat, ("fatmax_w", "fatmax")),
        "map_w": _first_num(flat, ("map_w", "map_aerobic_w")),
    }


def _extract_lactate_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize measured lactate curve/thresholds into TwinState when available."""
    direct = _as_dict(payload.get("lactate_state"))
    if direct:
        direct.setdefault("schema_version", "lactate_state.v1")
        return direct

    metabolic_curves = _as_dict(payload.get("metabolic_curves") or payload.get("curves_report"))
    curves = _as_dict(metabolic_curves.get("curves"))
    lactate_curve = _as_dict(payload.get("lactate_curve") or curves.get("lactate"))
    if not lactate_curve:
        return {}
    points = _as_list(lactate_curve.get("points"))
    thresholds = _as_dict(lactate_curve.get("thresholds"))
    if not points and not thresholds:
        return {}
    return {
        "schema_version": "lactate_state.v1",
        "measurement_tier": lactate_curve.get("measurement_tier", "LAB_MEASURED"),
        "latest_curve": lactate_curve,
        "thresholds": thresholds,
        "last_test_summary": {
            "points_count": len(points),
            "mlss_dmax_watts": thresholds.get("mlss_dmax_watts"),
            "obla_4mmol_watts": thresholds.get("obla_4mmol_watts"),
            "aerobic_2mmol_watts": thresholds.get("aerobic_2mmol_watts"),
        },
        "updated_at": payload.get("updated_at") or _now_iso(),
    }


def _extract_strength_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("strength_state"))
    if direct:
        direct.setdefault("schema_version", "strength_state.v1")
        return direct
    prescription = _as_dict(payload.get("strength_prescription"))
    if not prescription or prescription.get("schema_version") != "strength_prescription.v1":
        return {}
    return {
        "schema_version": "strength_state.v1",
        "measurement_tier": prescription.get("measurement_tier", "PRESCRIPTION_MODEL"),
        "latest_prescription": prescription,
        "primary_need": prescription.get("primary_need"),
        "primary_goal": prescription.get("primary_goal"),
        "weekly_frequency": prescription.get("weekly_frequency"),
        "interference_risk": prescription.get("interference_risk"),
        "decision_safety": _as_dict(prescription.get("decision_safety")),
        "updated_at": payload.get("updated_at") or _now_iso(),
    }


def _extract_nutrition_performance_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("nutrition_performance_state"))
    if direct:
        direct.setdefault("schema_version", "nutrition_performance_state.v1")
        return direct
    fueling = _as_dict(payload.get("performance_fueling_targets") or payload.get("nutrition_targets"))
    if not fueling or fueling.get("schema_version") != "performance_fueling_targets.v1":
        return {}
    return {
        "schema_version": "nutrition_performance_state.v1",
        "measurement_tier": fueling.get("measurement_tier", "PRESCRIPTION_MODEL"),
        "latest_targets": fueling,
        "targets": _as_dict(fueling.get("targets")),
        "red_flags": _as_list(fueling.get("red_flags")),
        "not_a_diet": fueling.get("not_a_diet", True),
        "updated_at": payload.get("updated_at") or _now_iso(),
    }


def _extract_checkin_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("checkin_state") or payload.get("athlete_checkin_state"))
    if direct:
        direct.setdefault("schema_version", "athlete_checkin.v1")
        return direct
    checkin = _as_dict(payload.get("checkin") or payload.get("checkin_response"))
    if checkin.get("schema_version") == "athlete_checkin.v1":
        return {
            "schema_version": "athlete_checkin.v1",
            "latest_checkin": checkin,
            "checkin_summary": _as_dict(checkin.get("checkin_summary")),
            "psychological_support_flag": _as_dict(checkin.get("psychological_support_flag")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_decision_safety_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("decision_safety_state"))
    if direct:
        direct.setdefault("schema_version", "decision_safety_state.v1")
        return direct
    safety = _as_dict(payload.get("decision_safety_response") or payload.get("decision_safety"))
    if safety.get("schema_version") == "decision_safety.v1":
        return {
            "schema_version": "decision_safety_state.v1",
            "latest_evaluation": safety,
            "decision_safety": _as_dict(safety.get("decision_safety")),
            "psychological_support_flag": _as_dict(safety.get("psychological_support_flag")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_coach_attention_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("coach_attention_state"))
    if direct:
        direct.setdefault("schema_version", "coach_attention_state.v1")
        return direct
    attention = _as_dict(payload.get("coach_attention") or payload.get("attention_response"))
    if attention.get("schema_version") == "coach_attention.v1":
        return {
            "schema_version": "coach_attention_state.v1",
            "latest_attention": attention,
            "athlete_attention": _as_dict(attention.get("athlete_attention")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_adherence_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("adherence_state"))
    if direct:
        direct.setdefault("schema_version", "adherence_state.v1")
        return direct
    report = _as_dict(payload.get("adherence_report") or payload.get("adherence"))
    if report.get("schema_version") == "adherence_report.v1":
        return {
            "schema_version": "adherence_state.v1",
            "latest_report": report,
            "compliance": _as_dict(report.get("compliance")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_testing_plan_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("testing_plan_state"))
    if direct:
        direct.setdefault("schema_version", "testing_plan_state.v1")
        return direct
    plan = _as_dict(payload.get("testing_plan") or payload.get("testing_plan_response"))
    if plan.get("schema_version") == "testing_plan.v1":
        return {
            "schema_version": "testing_plan_state.v1",
            "latest_plan": plan,
            "testing_recommendation": _as_dict(plan.get("testing_recommendation")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_race_execution_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("race_execution_state"))
    if direct:
        direct.setdefault("schema_version", "race_execution_state.v1")
        return direct
    plan = _as_dict(payload.get("race_execution_plan") or payload.get("race_execution_response"))
    if plan.get("schema_version") == "race_execution_plan.v1":
        return {
            "schema_version": "race_execution_state.v1",
            "latest_plan": plan,
            "race_execution_plan": _as_dict(plan.get("race_execution_plan")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_periodization_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("periodization_state"))
    if direct:
        direct.setdefault("schema_version", "periodization_state.v1")
        return direct
    review = _as_dict(payload.get("periodization_review") or payload.get("periodization_response"))
    if review.get("schema_version") == "periodization_review.v1":
        return {
            "schema_version": "periodization_state.v1",
            "latest_review": review,
            "periodization_review": _as_dict(review.get("periodization_review")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_communication_draft_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("communication_draft_state"))
    if direct:
        direct.setdefault("schema_version", "communication_draft_state.v1")
        return direct
    draft = _as_dict(payload.get("communication_draft") or payload.get("communication_draft_response"))
    if draft.get("schema_version") == "communication_draft.v1":
        return {
            "schema_version": "communication_draft_state.v1",
            "latest_draft": draft,
            "communication_draft": _as_dict(draft.get("communication_draft")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_environment_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("environment_state"))
    if direct:
        direct.setdefault("schema_version", "environment_state.v1")
        return direct
    adjustment = _as_dict(payload.get("environment_adjustment") or payload.get("environment_adjustment_response"))
    if adjustment.get("schema_version") == "environment_adjustment.v1":
        return {
            "schema_version": "environment_state.v1",
            "latest_adjustment": adjustment,
            "environment_adjustment": _as_dict(adjustment.get("environment_adjustment")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_pnei_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("pnei_state"))
    if direct:
        direct.setdefault("schema_version", "pnei_state.v1")
        return direct
    ctx = _as_dict(payload.get("pnei_context") or payload.get("pnei_context_response"))
    if ctx.get("schema_version") == "pnei_context.v1":
        return {
            "schema_version": "pnei_state.v1",
            "latest_context": ctx,
            "pnei_context": _as_dict(ctx.get("pnei_context")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_endocrine_context_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("endocrine_context_state"))
    if direct:
        direct.setdefault("schema_version", "endocrine_context_state.v1")
        return direct
    ctx = _as_dict(payload.get("endocrine_context") or payload.get("endocrine_context_response"))
    if ctx.get("schema_version") == "endocrine_context.v1":
        return {
            "schema_version": "endocrine_context_state.v1",
            "latest_context": ctx,
            "endocrine_context": _as_dict(ctx.get("endocrine_context")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_training_safety_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("training_safety_state"))
    if direct:
        direct.setdefault("schema_version", "training_safety_state.v1")
        return direct
    safety = _as_dict(payload.get("training_safety") or payload.get("training_safety_response"))
    if safety.get("schema_version") == "training_safety.v1":
        return {
            "schema_version": "training_safety_state.v1",
            "latest_safety": safety,
            "training_safety": _as_dict(safety.get("training_safety")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_constraints_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("constraints_state"))
    if direct:
        direct.setdefault("schema_version", "constraints_state.v1")
        return direct
    adaptation = _as_dict(payload.get("constraints_adaptation") or payload.get("constraints_response"))
    if adaptation.get("schema_version") == "constraints_adaptation.v1":
        return {
            "schema_version": "constraints_state.v1",
            "latest_adaptation": adaptation,
            "adaptation": _as_dict(adaptation.get("adaptation")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_equipment_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("equipment_state"))
    if direct and direct.get("schema_version"):
        direct.setdefault("schema_version", "equipment_state.v1")
        return direct
    review = _as_dict(payload.get("equipment_comfort_review") or payload.get("equipment_comfort_response"))
    if review.get("schema_version") == "equipment_comfort_review.v1":
        return {
            "schema_version": "equipment_state.v1",
            "latest_review": review,
            "equipment_comfort_review": _as_dict(review.get("equipment_comfort_review")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    if direct:
        return {"schema_version": "equipment_state.v1", **direct, "updated_at": payload.get("updated_at") or _now_iso()}
    return {}


def _extract_female_athlete_context_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("female_athlete_context_state"))
    if direct:
        direct.setdefault("schema_version", "female_athlete_context_state.v1")
        return direct
    ctx = _as_dict(payload.get("female_athlete_context") or payload.get("female_athlete_context_response"))
    if ctx.get("schema_version") == "female_athlete_context.v1":
        return {
            "schema_version": "female_athlete_context_state.v1",
            "latest_context": ctx,
            "female_athlete_context": _as_dict(ctx.get("female_athlete_context")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_daily_brief_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("daily_brief_state") or payload.get("coach_daily_brief_state"))
    if direct:
        direct.setdefault("schema_version", "daily_brief_state.v1")
        return direct
    brief = _as_dict(payload.get("coach_daily_brief") or payload.get("daily_brief_response"))
    if brief.get("schema_version") == "coach_daily_brief.v1":
        return {
            "schema_version": "daily_brief_state.v1",
            "latest_brief": brief,
            "coach_daily_brief": _as_dict(brief.get("coach_daily_brief")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _extract_session_decision_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    direct = _as_dict(payload.get("session_decision_state"))
    if direct:
        direct.setdefault("schema_version", "session_decision_state.v1")
        return direct
    decision = _as_dict(payload.get("session_decision") or payload.get("session_decision_response"))
    if decision.get("schema_version") == "coach_session_decision.v1":
        return {
            "schema_version": "session_decision_state.v1",
            "latest_decision": decision,
            "session_decision": _as_dict(decision.get("session_decision")),
            "updated_at": payload.get("updated_at") or _now_iso(),
        }
    return {}


def _confidence_from_sections(payload: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = _as_dict(payload.get("metabolic_snapshot"))
    sensor_quality = _as_dict(payload.get("sensor_quality"))
    load_state = _as_dict(payload.get("load_state"))
    base = 0.45
    if snapshot:
        base += 0.20
    if _as_dict(payload.get("rolling_power_curve")):
        base += 0.15
    if sensor_quality:
        base += 0.10
    if load_state:
        base += 0.05
    return {
        "overall": round(max(0.05, min(0.95, base)), 2),
        "metabolic": snapshot.get("confidence_score") or snapshot.get("confidence") or (0.6 if snapshot else 0.0),
        "load": load_state.get("confidence_score") or (0.4 if load_state else 0.0),
        "sensor": sensor_quality.get("confidence_score") or (0.5 if sensor_quality else 0.0),
    }


def build_twin_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build the canonical state blob from existing endpoint payloads.

    Accepted keys are deliberately broad so callers can pass current API
    responses without reshaping them: `anchor`, `measured_anchor`,
    `snapshot`, `metabolic_snapshot`, `curve`, `rolling_power_curve`, etc.
    """
    payload = _as_dict(payload)
    now = payload.get("updated_at") or payload.get("created_at") or _now_iso()
    athlete_profile = _as_dict(payload.get("athlete_profile") or payload.get("athlete") or {})
    metabolic_snapshot = _as_dict(payload.get("metabolic_snapshot") or payload.get("snapshot") or {})
    measured_anchor = _as_dict(payload.get("measured_anchor") or payload.get("anchor") or {})
    rolling_power_curve = _as_dict(payload.get("rolling_power_curve") or payload.get("curve") or {})
    state: Dict[str, Any] = {
        "schema_version": TWIN_STATE_SCHEMA_VERSION,
        "athlete_id": str(payload.get("athlete_id") or athlete_profile.get("athlete_id") or "unknown"),
        "created_at": payload.get("created_at") or now,
        "updated_at": now,
        "athlete_profile": athlete_profile,
        "measured_anchor": measured_anchor,
        "metabolic_snapshot": metabolic_snapshot,
        "metabolic_metrics": _extract_metabolic_metrics(metabolic_snapshot),
        "metabolic_curves": _as_dict(payload.get("metabolic_curves") or payload.get("curves_report")),
        "lactate_state": _extract_lactate_state(payload),
        "strength_state": _extract_strength_state(payload),
        "nutrition_performance_state": _extract_nutrition_performance_state(payload),
        "checkin_state": _extract_checkin_state(payload),
        "decision_safety_state": _extract_decision_safety_state(payload),
        "coach_attention_state": _extract_coach_attention_state(payload),
        "adherence_state": _extract_adherence_state(payload),
        "testing_plan_state": _extract_testing_plan_state(payload),
        "race_execution_state": _extract_race_execution_state(payload),
        "periodization_state": _extract_periodization_state(payload),
        "communication_draft_state": _extract_communication_draft_state(payload),
        "environment_state": _extract_environment_state(payload),
        "pnei_state": _extract_pnei_state(payload),
        "endocrine_context_state": _extract_endocrine_context_state(payload),
        "training_safety_state": _extract_training_safety_state(payload),
        "constraints_state": _extract_constraints_state(payload),
        "equipment_state": _extract_equipment_state(payload),
        "female_athlete_context_state": _extract_female_athlete_context_state(payload),
        "daily_brief_state": _extract_daily_brief_state(payload),
        "session_decision_state": _extract_session_decision_state(payload),
        "rolling_power_curve": rolling_power_curve,
        "load_state": _as_dict(payload.get("load_state")),
        "readiness_state": _as_dict(payload.get("readiness_state")),
        "sensor_quality": _as_dict(payload.get("sensor_quality")),
        "power_source_state": _as_dict(payload.get("power_source_state")),
        "workout_calendar_state": _as_dict(payload.get("workout_calendar_state") or payload.get("calendar") or {}),
        "last_compliance_results": _as_list(payload.get("last_compliance_results")),
        "team_calibration_state": _as_dict(payload.get("team_calibration_state") or payload.get("team_calibration") or {}),
        "state_confidence": {},
        "scope_declarations": {
            "non_cycling_load": "manual_injection_supported_v1",
            "female_physiology": "optional_modifier_supported_v1_not_mechanistic_cycle_model",
        },
        "warnings": _as_list(payload.get("warnings")),
        "event_log": _as_list(payload.get("event_log")),
    }
    if not state["event_log"]:
        state["event_log"] = [{"type": "state_created", "at": now, "source": payload.get("source", "api")}]
    state["state_confidence"] = _as_dict(payload.get("state_confidence")) or _confidence_from_sections(state)
    return validate_twin_state(state)


def validate_twin_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and JSON-clean a TwinState; raises ValueError if invalid."""
    state = _json_clean(deepcopy(state))
    if not isinstance(state, dict):
        raise ValueError("TwinState must be a JSON object")
    missing = sorted(_REQUIRED_TOP_LEVEL - set(state.keys()))
    if missing:
        raise ValueError(f"TwinState missing required keys: {', '.join(missing)}")
    if state.get("schema_version") != TWIN_STATE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported TwinState schema_version: {state.get('schema_version')}")
    if not isinstance(state.get("warnings"), list):
        raise ValueError("TwinState.warnings must be an array")
    if not isinstance(state.get("event_log"), list):
        raise ValueError("TwinState.event_log must be an array")
    return state
