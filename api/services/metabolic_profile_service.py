"""Application service for versioned athlete metabolic profiles."""

from __future__ import annotations

from typing import Any, Dict, Optional

from engines.performance.mmp_aggregate import MMP_STATUS_PUBLISHED
from engines.persistence.metabolic_profile_store import MetabolicProfileStore
from engines.persistence.mmp_aggregate_store import MmpAggregateStore


class MetabolicProfileService:
    def get_current_profile(
        self,
        athlete_id: str,
        *,
        profile_store: MetabolicProfileStore,
        mmp_store: Optional[MmpAggregateStore] = None,
    ) -> Dict[str, Any]:
        view = profile_store.load_current_profile_view(athlete_id)
        if not view:
            active = profile_store.load_latest_active_profile(athlete_id)
            view = active

        if view and view.get("vo2max_ml_kg_min") is not None:
            return {
                "status": "available",
                "athlete_id": athlete_id,
                "profile_version": view.get("profile_version"),
                "profile_status": view.get("profile_status"),
                "confidence_score": view.get("confidence_score"),
                "confidence_tier": view.get("confidence_tier"),
                "vo2max_ml_kg_min": view.get("vo2max_ml_kg_min"),
                "vlamax_mmol_l_s": view.get("vlamax_mmol_l_s"),
                "mlss_power_w": view.get("mlss_power_w"),
                "fatmax_power_w": view.get("fatmax_power_w"),
                "map_power_w": view.get("map_power_w"),
                "apr_w": view.get("apr_w"),
                "phenotype_type": view.get("phenotype_type"),
                "phenotype_description": view.get("phenotype_description"),
                "calculated_at": view.get("calculated_at"),
                "valid_from_date": view.get("valid_from_date"),
                "n_activities_included": view.get("n_activities_included"),
                "source_coverage_score": view.get("source_coverage_score"),
            }

        mmp_status = "collecting"
        if mmp_store is not None:
            aggregate = mmp_store.load_aggregate_record(athlete_id)
            if aggregate:
                mmp_status = str(aggregate.get("mmp_status") or "collecting")

        reason = "MMP not published yet" if mmp_status != MMP_STATUS_PUBLISHED else "No active metabolic profile"
        return {
            "status": "not_available",
            "athlete_id": athlete_id,
            "reason": reason,
            "mmp_status": mmp_status,
            "message": "Dati insufficienti per generare un profilo metabolico attendibile.",
        }
