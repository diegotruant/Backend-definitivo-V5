"""Application service for versioned athlete training thresholds."""

from __future__ import annotations

from typing import Any, Dict, Optional

from engines.performance.mmp_aggregate import MMP_STATUS_PUBLISHED
from engines.persistence.mmp_aggregate_store import MmpAggregateStore
from engines.persistence.threshold_store import ThresholdStore
from engines.physiology.athlete_profile_bridge import build_zone_anchors_from_model


class ThresholdService:
    def get_current_thresholds(
        self,
        athlete_id: str,
        *,
        threshold_store: ThresholdStore,
        mmp_store: Optional[MmpAggregateStore] = None,
    ) -> Dict[str, Any]:
        view = threshold_store.load_current_thresholds_view(athlete_id)
        if not view:
            view = threshold_store.load_latest_active_thresholds(athlete_id)

        if view and view.get("ftp_w") is not None:
            return {
                "status": "available",
                "athlete_id": athlete_id,
                "threshold_version": view.get("threshold_version"),
                "ftp_w": view.get("ftp_w"),
                "lthr_bpm": view.get("lthr_bpm"),
                "cp_w": view.get("cp_w"),
                "w_prime_j": view.get("w_prime_j"),
                "source_type": view.get("source_type"),
                "calculated_at": view.get("calculated_at"),
                "valid_from_date": view.get("valid_from_date"),
            }

        mmp_status = "collecting"
        if mmp_store is not None:
            aggregate = mmp_store.load_aggregate_record(athlete_id)
            if aggregate:
                mmp_status = str(aggregate.get("mmp_status") or "collecting")

        return {
            "status": "not_available",
            "athlete_id": athlete_id,
            "reason": "MMP not published yet" if mmp_status != MMP_STATUS_PUBLISHED else "No active thresholds",
            "mmp_status": mmp_status,
            "message": "Soglie atleta non disponibili finché la MMP non è published.",
        }

    def get_zone_anchors(
        self,
        athlete_id: str,
        *,
        profile_store,
        threshold_store: ThresholdStore,
    ) -> Dict[str, Any]:
        from engines.persistence.metabolic_profile_store import MetabolicProfileStore

        profile = None
        if isinstance(profile_store, MetabolicProfileStore):
            profile = profile_store.load_current_profile_view(athlete_id) or profile_store.load_latest_active_profile(athlete_id)
        thresholds = threshold_store.load_current_thresholds_view(athlete_id) or threshold_store.load_latest_active_thresholds(athlete_id)
        anchors = build_zone_anchors_from_model(profile, thresholds)
        if anchors.get("status") == "success":
            return {"status": "available", "athlete_id": athlete_id, **anchors}
        return {
            "status": "not_available",
            "athlete_id": athlete_id,
            "reason": anchors.get("reason") or "NO_ACTIVE_MODEL",
            "message": "Ancore zona non disponibili senza profilo metabolico o soglie attive.",
        }
