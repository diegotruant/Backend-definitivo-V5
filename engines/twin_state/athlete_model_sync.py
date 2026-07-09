"""Apply versioned athlete model to TwinState after ingest."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from engines.persistence.metabolic_profile_store import MetabolicProfileStore
from engines.persistence.mmp_aggregate_store import MmpAggregateStore
from engines.persistence.mmp_unification import apply_canonical_curve_to_twin_state
from engines.persistence.threshold_store import ThresholdStore
from engines.physiology.athlete_profile_bridge import resolve_active_athlete_model
from engines.twin_state.metabolic_curves_sync import sync_twin_from_versioned_profile
from engines.twin_state.models import validate_twin_state


def sync_twin_athlete_model(
    state: Dict[str, Any],
    *,
    athlete_id: str,
    mmp_store: Optional[MmpAggregateStore] = None,
    profile_store: Optional[MetabolicProfileStore] = None,
    threshold_store: Optional[ThresholdStore] = None,
    legacy_rolling_curve: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Refresh twin metabolic snapshot, curves, thresholds and canonical MMP from stores.

    Per-ride metabolic snapshots are ignored when a versioned athlete profile exists.
    """
    state = deepcopy(state)
    state["athlete_id"] = athlete_id or state.get("athlete_id")

    profile = profile_store.load_current_profile_view(athlete_id) if profile_store else None
    if not profile and profile_store:
        profile = profile_store.load_latest_active_profile(athlete_id)

    thresholds = threshold_store.load_current_thresholds_view(athlete_id) if threshold_store else None
    if not thresholds and threshold_store:
        thresholds = threshold_store.load_latest_active_thresholds(athlete_id)

    model = resolve_active_athlete_model(metabolic_profile=profile, thresholds=thresholds)

    if profile and model["metabolic_snapshot"].get("status") == "success":
        state = sync_twin_from_versioned_profile(state, profile, force=True)
    else:
        state["athlete_model_status"] = "metabolic_profile_not_available"

    patch = model.get("athlete_profile_patch") or {}
    if patch:
        athlete_profile = dict(state.get("athlete_profile") or {})
        athlete_profile.update(patch)
        state["athlete_profile"] = athlete_profile

    anchors = model.get("zone_anchors") or {}
    if anchors.get("status") == "success":
        state["zone_anchors"] = anchors

    aggregate = mmp_store.load_aggregate_record(athlete_id) if mmp_store else None
    state = apply_canonical_curve_to_twin_state(
        state,
        aggregate_record=aggregate,
        legacy_rolling_curve=legacy_rolling_curve or state.get("rolling_power_curve"),
    )

    state["athlete_model"] = {
        "metabolic_profile_version": (profile or {}).get("profile_version"),
        "threshold_version": (thresholds or {}).get("threshold_version"),
        "mmp_source": (state.get("mmp_curve_meta") or {}).get("source"),
        "zone_anchors_status": anchors.get("status"),
    }
    return validate_twin_state(state)
