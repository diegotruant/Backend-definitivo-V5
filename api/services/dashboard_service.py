"""Aggregated athlete dashboard snapshot for coach home views."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.performance.training_variability_engine import calculate_acwr, calculate_monotony_strain
from engines.readiness.readiness_engine import compute_load_risk, compute_readiness_today


class DashboardService:
    def athlete_snapshot(
        self,
        *,
        twin_state: Optional[Dict[str, Any]] = None,
        load_state: Optional[Dict[str, Any]] = None,
        hrv_status: Optional[Dict[str, Any]] = None,
        sleep_status: Optional[Dict[str, Any]] = None,
        subjective: Optional[Dict[str, Any]] = None,
        daily_tss: Optional[List[float]] = None,
        last_ride_summary: Optional[Dict[str, Any]] = None,
        include_chart_hints: bool = True,
    ) -> Dict[str, Any]:
        """Orchestrate readiness, load, twin highlights for a coach dashboard tile."""
        load = load_state or (twin_state or {}).get("load_state") or {}
        readiness = compute_readiness_today(
            load_state=load,
            hrv_status=hrv_status,
            sleep_status=sleep_status,
            subjective=subjective,
        )
        load_risk = compute_load_risk(load)

        acwr = None
        atl = load.get("acute_load") or load.get("atl")
        ctl = load.get("chronic_load") or load.get("ctl")
        if atl is not None and ctl is not None:
            acwr = calculate_acwr(float(atl), float(ctl))

        monotony = calculate_monotony_strain(daily_tss or []) if daily_tss else None

        twin_highlights: Dict[str, Any] = {}
        if twin_state:
            profile = twin_state.get("athlete_profile") or {}
            athlete_model = twin_state.get("athlete_model") or {}
            zone_anchors = twin_state.get("zone_anchors") or {}
            metabolic = twin_state.get("metabolic_metrics") or twin_state.get("metabolic_snapshot") or {}
            if metabolic.get("source") == "athlete_metabolic_profile_versions":
                metabolic = {**metabolic, "is_athlete_level": True}
            twin_highlights = {
                "cp_w": zone_anchors.get("cp_w") or metabolic.get("cp_w") or metabolic.get("critical_power_w") or profile.get("cp_w"),
                "ftp_w": zone_anchors.get("ftp_w") or profile.get("ftp_w") or metabolic.get("ftp_w"),
                "vo2max_ml_kg_min": metabolic.get("vo2max_ml_kg_min") or metabolic.get("estimated_vo2max"),
                "metabolic_profile_version": athlete_model.get("metabolic_profile_version"),
                "threshold_version": athlete_model.get("threshold_version"),
                "mmp_source": athlete_model.get("mmp_source"),
                "updated_at": twin_state.get("updated_at"),
            }

        chart_hints: List[Dict[str, str]] = []
        if include_chart_hints:
            chart_hints = [
                {"chart_type": "readiness_trend", "category": "readiness"},
                {"chart_type": "training_load", "category": "load"},
                {"chart_type": "acwr_trend", "category": "load"},
                {"chart_type": "pmc_forecast", "category": "load"},
            ]
            if daily_tss:
                chart_hints.append({"chart_type": "monotony_strain", "category": "load"})
            if twin_state and twin_state.get("metabolic_curves"):
                chart_hints.append({"chart_type": "vo2_demand", "category": "metabolic"})

        return {
            "status": "success",
            "schema_version": "dashboard_snapshot.v1",
            "readiness": readiness,
            "load_risk": load_risk,
            "acwr": acwr,
            "monotony_strain": monotony,
            "twin_highlights": twin_highlights,
            "last_ride_summary": last_ride_summary,
            "chart_hints": chart_hints,
        }
