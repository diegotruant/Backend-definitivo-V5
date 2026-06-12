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
