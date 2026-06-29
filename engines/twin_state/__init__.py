"""Canonical digital-twin state package."""

from .models import TWIN_STATE_SCHEMA_VERSION, build_twin_state, validate_twin_state
from .metabolic_curves_sync import (
    LACTATE_STATE_SCHEMA_VERSION,
    METABOLIC_CURVES_SCHEMA_VERSION,
    PROFILE_CURVE_IDS,
    build_lactate_persistence_bundle,
    build_profile_metabolic_curves_report,
    ingest_worker_hook_points,
    sync_lactate_state_from_steps,
    sync_profile_metabolic_curves,
    sync_twin_after_profile_refresh,
)
from .state_update_engine import update_twin_state_from_ride, update_twin_state_from_workout_result

__all__ = [
    "TWIN_STATE_SCHEMA_VERSION",
    "METABOLIC_CURVES_SCHEMA_VERSION",
    "LACTATE_STATE_SCHEMA_VERSION",
    "PROFILE_CURVE_IDS",
    "build_twin_state",
    "validate_twin_state",
    "build_lactate_persistence_bundle",
    "build_profile_metabolic_curves_report",
    "ingest_worker_hook_points",
    "sync_lactate_state_from_steps",
    "sync_profile_metabolic_curves",
    "sync_twin_after_profile_refresh",
    "update_twin_state_from_ride",
    "update_twin_state_from_workout_result",
]
