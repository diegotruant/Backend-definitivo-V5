"""Sync coach-facing metabolic curves into TwinState.

Profile-stable curves (VO2 demand, substrate oxidation, energy contribution)
belong on ``twin_state.metabolic_curves``. Measured lactate curves belong on
``twin_state.lactate_state`` (and are mirrored under metabolic_curves.curves.lactate).

Session-scoped curves (fuel demand, W′ balance, durability) stay on activity payloads.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence

from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_coach_curves import (
    build_lactate_curve,
    build_metabolic_curves_report,
)

from .models import TWIN_STATE_SCHEMA_VERSION, _extract_lactate_state, _extract_metabolic_metrics, validate_twin_state

PROFILE_CURVE_IDS: tuple[str, ...] = (
    "vo2_demand",
    "substrate_oxidation",
    "energy_contribution_by_duration",
)

METABOLIC_CURVES_SCHEMA_VERSION = "metabolic_curves.v1"
LACTATE_STATE_SCHEMA_VERSION = "lactate_state.v1"


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _athlete_context_from_state(state: Dict[str, Any]) -> AthleteContext:
    profile = _as_dict(state.get("athlete_profile"))
    return AthleteContext(
        gender=str(profile.get("gender") or profile.get("sex") or "MALE"),
        training_years=float(profile.get("training_years") or 10),
        discipline=str(profile.get("discipline") or "ENDURANCE"),
        body_fat_pct=profile.get("body_fat_pct"),
    )


def _weight_kg_from_state(state: Dict[str, Any]) -> Optional[float]:
    profile = _as_dict(state.get("athlete_profile"))
    for key in ("weight_kg", "weight"):
        try:
            if profile.get(key) is not None:
                value = float(profile[key])
                if value > 0:
                    return value
        except (TypeError, ValueError):
            continue
    return None


def _snapshot_ready(snapshot: Dict[str, Any]) -> bool:
    return snapshot.get("status") == "success" and bool(snapshot.get("estimated_vo2max"))


def _profile_curves_complete(report: Dict[str, Any]) -> bool:
    available = set(report.get("available_curves") or [])
    return all(curve_id in available for curve_id in PROFILE_CURVE_IDS)


def build_profile_metabolic_curves_report(
    metabolic_snapshot: Dict[str, Any],
    *,
    weight_kg: Optional[float],
    gender: Optional[str] = None,
    training_years: Optional[float] = None,
    discipline: Optional[str] = None,
    eta: Optional[float] = None,
    power_points: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Build profile-stable metabolic curves for TwinState persistence."""
    if not _snapshot_ready(metabolic_snapshot):
        return {
            "status": "insufficient_data",
            "schema_version": METABOLIC_CURVES_SCHEMA_VERSION,
            "measurement_tier": "INSUFFICIENT_DATA",
            "reason": "metabolic_snapshot_not_ready",
            "confidence_score": 0.0,
            "curves": {},
            "available_curves": [],
            "missing_curves": [{"curve": name, "reason": "metabolic_snapshot_not_ready"} for name in PROFILE_CURVE_IDS],
        }
    return build_metabolic_curves_report(
        metabolic_snapshot,
        weight_kg=weight_kg,
        gender=gender,
        training_years=training_years,
        discipline=discipline,
        eta=eta,
        power_points=power_points,
        include_curves=list(PROFILE_CURVE_IDS),
    )


def sync_profile_metabolic_curves(
    state: Dict[str, Any],
    *,
    force: bool = False,
    metabolic_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach or refresh ``metabolic_curves`` on a TwinState dict."""
    state = deepcopy(state)
    snapshot = _as_dict(metabolic_snapshot or state.get("metabolic_snapshot"))
    if metabolic_snapshot is not None:
        state["metabolic_snapshot"] = snapshot
        state["metabolic_metrics"] = _extract_metabolic_metrics(snapshot)

    existing = _as_dict(state.get("metabolic_curves"))
    if not force and existing.get("schema_version") == METABOLIC_CURVES_SCHEMA_VERSION and _profile_curves_complete(existing):
        return validate_twin_state(state)

    weight_kg = _weight_kg_from_state(state)
    ctx = _athlete_context_from_state(state)
    ctx_used = _as_dict(snapshot.get("context_used"))
    report = build_profile_metabolic_curves_report(
        snapshot,
        weight_kg=weight_kg,
        gender=ctx.effective_gender(),
        training_years=ctx.effective_training_years(),
        discipline=ctx.effective_discipline(),
        eta=ctx_used.get("resolved_eta"),
    )
    state["metabolic_curves"] = report
    return validate_twin_state(state)


def sync_lactate_state_from_steps(
    state: Dict[str, Any],
    lactate_steps: Sequence[Dict[str, Any]],
    *,
    merge_into_metabolic_curves: bool = True,
) -> Dict[str, Any]:
    """Serialize measured lactate steps into ``lactate_state`` (and optional curves bundle)."""
    state = deepcopy(state)
    lactate_curve = build_lactate_curve(list(lactate_steps))
    payload = {
        "lactate_curve": lactate_curve,
        "updated_at": state.get("updated_at"),
    }
    lactate_state = _extract_lactate_state(payload)
    if lactate_state:
        state["lactate_state"] = lactate_state

    if merge_into_metabolic_curves and lactate_curve.get("points"):
        curves_report = _as_dict(state.get("metabolic_curves"))
        if curves_report.get("schema_version") != METABOLIC_CURVES_SCHEMA_VERSION:
            curves_report = {
                "status": "success",
                "schema_version": METABOLIC_CURVES_SCHEMA_VERSION,
                "measurement_tier": "MIXED",
                "curves": {},
                "available_curves": [],
                "missing_curves": [],
                "confidence_score": 0.0,
            }
        curves = _as_dict(curves_report.get("curves"))
        curves["lactate"] = lactate_curve
        curves_report["curves"] = curves
        available = list(curves_report.get("available_curves") or [])
        if "lactate" not in available and lactate_curve.get("measurement_tier") != "INSUFFICIENT_DATA":
            available.append("lactate")
        curves_report["available_curves"] = available
        curves_report["status"] = "success" if available else curves_report.get("status", "insufficient_data")
        state["metabolic_curves"] = curves_report

    return validate_twin_state(state)


def sync_twin_after_profile_refresh(
    state: Dict[str, Any],
    metabolic_snapshot: Dict[str, Any],
    *,
    lactate_steps: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Worker hook: profile snapshot changed → refresh curves (+ optional lactate)."""
    state = sync_profile_metabolic_curves(state, force=True, metabolic_snapshot=metabolic_snapshot)
    if lactate_steps:
        state = sync_lactate_state_from_steps(state, lactate_steps)
    return state


def build_lactate_persistence_bundle(
    lactate_steps: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return DB-ready lactate fragments without a full TwinState."""
    lactate_curve = build_lactate_curve(list(lactate_steps))
    lactate_state = _extract_lactate_state({"lactate_curve": lactate_curve})
    return {
        "schema_version": LACTATE_STATE_SCHEMA_VERSION,
        "lactate_curve": lactate_curve,
        "lactate_state": lactate_state,
        "db_contract": {
            "store_on": "twin_states.twin_state.lactate_state",
            "mirror_curve_on": "twin_states.twin_state.metabolic_curves.curves.lactate",
        },
    }


def ingest_worker_hook_points() -> Dict[str, str]:
    """Documented orchestration anchors for S3 → VPS ingest workers."""
    return {
        "after_twin_build": "engines.twin_state.metabolic_curves_sync.sync_profile_metabolic_curves",
        "after_profile_refresh": "engines.twin_state.metabolic_curves_sync.sync_twin_after_profile_refresh",
        "after_lactate_test": "engines.twin_state.metabolic_curves_sync.sync_lactate_state_from_steps",
        "after_ride_update": "engines.twin_state.state_update_engine.update_twin_state_from_ride",
        "after_bundle_mmp_aggregate": "engines.persistence.mmp_aggregate_pipeline.sync_athlete_mmp_after_bundle",
        "after_bundle_metabolic_profile": "engines.persistence.metabolic_profile_pipeline.sync_metabolic_profile_after_mmp",
        "mmp_aggregate_store": "engines.persistence.mmp_aggregate_store.mmp_store_from_env",
        "metabolic_profile_store": "engines.persistence.metabolic_profile_store.metabolic_profile_store_from_env",
        "twin_schema": TWIN_STATE_SCHEMA_VERSION,
        "curves_schema": METABOLIC_CURVES_SCHEMA_VERSION,
        "lactate_schema": LACTATE_STATE_SCHEMA_VERSION,
    }
