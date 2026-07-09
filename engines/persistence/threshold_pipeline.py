"""Sync versioned athlete thresholds after metabolic profile / MMP update."""

from __future__ import annotations

from typing import Any, Dict, Optional

from engines.performance.mmp_aggregate import MMP_STATUS_PUBLISHED
from engines.physiology.threshold_calculator import (
    estimate_thresholds_from_mmp,
    should_create_new_threshold_version,
)
from engines.persistence.mmp_aggregate_store import MmpAggregateStore
from engines.persistence.metabolic_profile_store import MetabolicProfileStore
from engines.persistence.threshold_store import ThresholdStore


def sync_thresholds_after_profile(
    mmp_store: MmpAggregateStore,
    threshold_store: ThresholdStore,
    profile_store: MetabolicProfileStore,
    *,
    athlete_id: str,
    coach_ftp_w: Optional[float] = None,
    coach_lthr_bpm: Optional[float] = None,
) -> Dict[str, Any]:
    """Create threshold version when published MMP + profile support stable FTP/CP."""
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
        }

    mmp_curve = aggregate.get("mmp_curve_json") or mmp_store.load_aggregate_curve(athlete_id)
    active_profile = profile_store.load_latest_active_profile(athlete_id)

    new_thresholds = estimate_thresholds_from_mmp(
        mmp_curve,
        metabolic_profile=active_profile,
        coach_ftp_w=coach_ftp_w,
        coach_lthr_bpm=coach_lthr_bpm,
        mmp_status=mmp_status,
    )
    if new_thresholds.get("status") != "success":
        return {
            "status": "skipped",
            "reason": new_thresholds.get("reason") or "THRESHOLD_CALC_FAILED",
            "athlete_id": athlete_id,
            "details": new_thresholds,
        }

    latest = threshold_store.load_latest_active_thresholds(athlete_id)
    should_create, creation_reason = should_create_new_threshold_version(latest, new_thresholds)
    if not should_create:
        return {
            "status": "skipped",
            "reason": creation_reason,
            "athlete_id": athlete_id,
            "active_threshold_version": (latest or {}).get("threshold_version"),
        }

    threshold_store.deactivate_previous_thresholds(athlete_id)
    threshold_version = threshold_store.get_next_threshold_version(athlete_id)
    saved = threshold_store.save_threshold_version(
        athlete_id=athlete_id,
        threshold_version=threshold_version,
        thresholds=new_thresholds,
        source_mmp=aggregate,
        metabolic_profile_version=(active_profile or {}).get("profile_version"),
        is_active=True,
        creation_reason=creation_reason,
    )
    current = threshold_store.update_athlete_current_thresholds(
        athlete_id=athlete_id,
        active_threshold_id=str(saved["id"]),
        threshold_version=threshold_version,
        ftp_w=new_thresholds.get("ftp_w"),
        lthr_bpm=new_thresholds.get("lthr_bpm"),
        cp_w=new_thresholds.get("cp_w"),
    )

    return {
        "status": "success",
        "athlete_id": athlete_id,
        "threshold_version": threshold_version,
        "creation_reason": creation_reason,
        "ftp_w": new_thresholds.get("ftp_w"),
        "cp_w": new_thresholds.get("cp_w"),
        "saved_threshold_id": saved.get("id"),
        "current_thresholds": current,
    }
