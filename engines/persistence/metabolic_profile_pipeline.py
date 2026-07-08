"""Sync versioned athlete metabolic profile after MMP aggregate update."""

from __future__ import annotations

from typing import Any, Dict, List

from engines.performance.mmp_aggregate import MMP_DURATION_FAMILIES, MMP_STATUS_PUBLISHED
from engines.physiology.metabolic_profile_calculator import (
    calculate_metabolic_profile_from_mmp,
    should_create_new_profile_version,
)
from engines.persistence.metabolic_profile_store import MetabolicProfileStore
from engines.persistence.mmp_aggregate_store import MmpAggregateStore


def _missing_families(mmp_curve: List[Dict[str, Any]]) -> List[str]:
    durations = {int(p["duration_s"]) for p in mmp_curve if isinstance(p, dict)}
    missing = []
    for family, family_durations in MMP_DURATION_FAMILIES.items():
        if not any(d in durations for d in family_durations):
            missing.append(family)
    return missing


def _covered_families(mmp_curve: List[Dict[str, Any]]) -> Dict[str, bool]:
    durations = {int(p["duration_s"]) for p in mmp_curve if isinstance(p, dict)}
    return {
        family: any(d in durations for d in family_durations)
        for family, family_durations in MMP_DURATION_FAMILIES.items()
    }


def sync_metabolic_profile_after_mmp(
    mmp_store: MmpAggregateStore,
    profile_store: MetabolicProfileStore,
    *,
    athlete_id: str,
    athlete_data: Dict[str, Any],
    changed_mmp_points: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Create a new athlete metabolic profile version when aggregate MMP is published
    and material parameter changes exceed thresholds.
    """
    aggregate = mmp_store.load_aggregate_record(athlete_id)
    if not aggregate:
        return {"status": "skipped", "reason": "NO_MMP_AGGREGATE", "athlete_id": athlete_id}

    mmp_status = str(aggregate.get("mmp_status") or "")
    if mmp_status != MMP_STATUS_PUBLISHED:
        return {
            "status": "skipped",
            "reason": "MMP_NOT_PUBLISHED",
            "athlete_id": athlete_id,
            "mmp_status": mmp_status,
            "message": "Metabolic profile is not calculated until MMP status is published.",
        }

    mmp_curve = aggregate.get("mmp_curve_json") or mmp_store.load_aggregate_curve(athlete_id)
    readiness = {
        "mmp_status": mmp_status,
        "coverage_score": aggregate.get("coverage_score"),
        "confidence_tier": aggregate.get("confidence_tier"),
        "n_activities_included": aggregate.get("n_activities_included"),
        "n_key_durations_covered": aggregate.get("n_key_durations_covered"),
    }

    source_mmp = {
        **aggregate,
        "mmp_curve_json": mmp_curve,
        "duration_families_covered": _covered_families(mmp_curve),
        "missing_duration_families": _missing_families(mmp_curve),
    }

    new_profile = calculate_metabolic_profile_from_mmp(mmp_curve, athlete_data, readiness)
    if new_profile.get("status") != "success":
        return {
            "status": "skipped",
            "reason": new_profile.get("reason") or "PROFILE_CALC_FAILED",
            "athlete_id": athlete_id,
            "details": new_profile,
        }

    latest_profile = profile_store.load_latest_active_profile(athlete_id)
    should_create, creation_reason = should_create_new_profile_version(
        latest_profile,
        new_profile,
        changed_mmp_points,
    )
    if not should_create:
        return {
            "status": "skipped",
            "reason": creation_reason,
            "athlete_id": athlete_id,
            "mmp_status": mmp_status,
            "active_profile_version": (latest_profile or {}).get("profile_version"),
        }

    profile_store.deactivate_previous_profiles(athlete_id)
    profile_version = profile_store.get_next_profile_version(athlete_id)
    saved = profile_store.save_metabolic_profile_version(
        athlete_id=athlete_id,
        profile_version=profile_version,
        profile=new_profile,
        source_mmp=source_mmp,
        is_active=True,
        creation_reason=creation_reason,
    )
    current = profile_store.update_athlete_current_profile(
        athlete_id=athlete_id,
        active_profile_id=str(saved["id"]),
        profile_version=profile_version,
        profile_status=str(new_profile.get("profile_status")),
        confidence_score=float(new_profile.get("confidence_score") or 0),
        confidence_tier=str(new_profile.get("confidence_tier")),
    )

    return {
        "status": "success",
        "athlete_id": athlete_id,
        "profile_version": profile_version,
        "creation_reason": creation_reason,
        "profile_status": new_profile.get("profile_status"),
        "confidence_score": new_profile.get("confidence_score"),
        "confidence_tier": new_profile.get("confidence_tier"),
        "saved_profile_id": saved.get("id"),
        "current_profile": current,
        "warnings": new_profile.get("warnings") or [],
    }
