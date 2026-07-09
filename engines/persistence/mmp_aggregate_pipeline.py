"""Orchestrate athlete-level MMP aggregation after activity bundle processing."""

from __future__ import annotations

from typing import Any, Dict, Optional

from engines.performance.mmp_aggregate import (
    evaluate_mmp_readiness,
    extract_mmp_points,
    merge_mmp_curves,
    public_mmp_curve,
)
from engines.persistence.mmp_aggregate_store import MmpAggregateStore
from engines.persistence.metabolic_profile_pipeline import sync_metabolic_profile_after_mmp
from engines.persistence.metabolic_profile_store import MetabolicProfileStore
from engines.persistence.threshold_pipeline import sync_thresholds_after_profile
from engines.persistence.threshold_store import ThresholdStore


def sync_athlete_mmp_after_bundle(
    store: MmpAggregateStore,
    *,
    athlete_id: str,
    activity_id: str,
    activity_file_id: str,
    activity_date: str,
    bundle: Dict[str, Any],
    athlete_data: Optional[Dict[str, Any]] = None,
    profile_store: Optional[MetabolicProfileStore] = None,
    threshold_store: Optional[ThresholdStore] = None,
    coach_ftp_w: Optional[float] = None,
    coach_lthr_bpm: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Post-bundle MMP pipeline for worker / ingest orchestration.

    1. Extract per-activity MMP points from bundle
    2. Persist ``activity_mmp_points``
    3. Merge with existing athlete aggregate
    4. Evaluate readiness / exposure status
    5. Upsert ``athlete_mmp_aggregate``
    """
    new_points = extract_mmp_points(
        bundle,
        activity_id=activity_id,
        activity_file_id=activity_file_id,
        activity_date=activity_date,
    )
    if not new_points:
        return {
            "status": "skipped",
            "reason": "NO_MMP_POINTS",
            "athlete_id": athlete_id,
            "activity_id": activity_id,
        }

    store.insert_activity_mmp_points(
        athlete_id=athlete_id,
        activity_id=activity_id,
        activity_file_id=activity_file_id,
        activity_date=activity_date,
        points=new_points,
    )

    existing_curve = store.load_aggregate_curve(athlete_id)
    merged_curve, improvements = merge_mmp_curves(existing_curve, new_points)
    n_activities = store.count_distinct_activities(athlete_id)
    readiness = evaluate_mmp_readiness(merged_curve, n_activities)

    aggregate_record = store.upsert_aggregate(
        athlete_id=athlete_id,
        mmp_curve_json=merged_curve,
        coverage_score=float(readiness["coverage_score"]),
        confidence_tier=str(readiness["confidence_tier"]),
        mmp_status=str(readiness["mmp_status"]),
        n_activities_included=n_activities,
        n_key_durations_covered=int(readiness["n_key_durations_covered"]),
    )

    metabolic_profile_result = (
        sync_metabolic_profile_after_mmp(
            store,
            profile_store,
            athlete_id=athlete_id,
            athlete_data=athlete_data or {},
            changed_mmp_points=improvements,
        )
        if profile_store is not None
        else {
            "status": "skipped",
            "reason": "PROFILE_STORE_NOT_PROVIDED",
        }
    )

    threshold_result = (
        sync_thresholds_after_profile(
            store,
            threshold_store,
            profile_store,
            athlete_id=athlete_id,
            coach_ftp_w=coach_ftp_w,
            coach_lthr_bpm=coach_lthr_bpm,
        )
        if threshold_store is not None and profile_store is not None
        else {
            "status": "skipped",
            "reason": "THRESHOLD_OR_PROFILE_STORE_NOT_PROVIDED",
        }
    )

    return {
        "status": "success",
        "athlete_id": athlete_id,
        "activity_id": activity_id,
        "activity_file_id": activity_file_id,
        "n_activity_points_saved": len(new_points),
        "n_improvements": len(improvements),
        "improvements": improvements,
        "coverage_score": readiness["coverage_score"],
        "confidence_tier": readiness["confidence_tier"],
        "mmp_status": readiness["mmp_status"],
        "expose_to_frontend": readiness["expose_to_frontend"],
        "missing_durations": readiness["missing_durations"],
        "covered_key_durations": readiness["covered_key_durations"],
        "n_activities_included": n_activities,
        "mmp_curve": public_mmp_curve(merged_curve, readiness),
        "aggregate": aggregate_record,
        "metabolic_profile": metabolic_profile_result,
        "thresholds": threshold_result,
        "notes": [
            "Per-activity metabolic profile is not promoted to stable athlete profile.",
            "MMP hidden from frontend while status is collecting.",
            "Athlete metabolic profile is created only when MMP status is published.",
            "FTP/LTHR thresholds are versioned from published MMP unless coach override is supplied.",
        ],
    }
