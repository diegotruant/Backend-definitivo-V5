from __future__ import annotations

from typing import Any, Dict

from api.engine_schemas import FatmaxCompareRequest, FatmaxLabRequest, FatmaxReportRequest
from api.services.engine_context import athlete_context_from_params, mmp_dict, profiler_from_athlete
from api.services.profile_extended_service import ProfileExtendedService
from engines.metabolic.fatmax_engine import (
    GasExchangePoint,
    build_lab_fatmax_report,
    build_model_fatmax_report,
    compare_fatmax_reports,
)


def fatmax_report(req: FatmaxReportRequest) -> Dict[str, Any]:
    """Build a model-estimated FATmax report from MMP or a supplied snapshot."""
    profiler = profiler_from_athlete(req.athlete)
    snapshot = req.metabolic_snapshot
    if snapshot is None:
        snapshot = profiler.generate_metabolic_snapshot(
            mmp_dict(req.mmp),
            expected_eta=req.expected_eta,
            measured_lacap=req.measured_lacap,
            effective_cadence_rpm=req.effective_cadence_rpm,
            clean_mmp_first=req.clean_mmp_first,
        )
    ctx = athlete_context_from_params(req.athlete)
    return build_model_fatmax_report(
        snapshot,
        athlete_weight_kg=req.athlete.weight_kg,
        gender=ctx.effective_gender(),
        training_years=ctx.effective_training_years(),
        discipline=ctx.effective_discipline(),
        recent_training_status=req.recent_training_status,
        environment_context=req.environment_context,
        nutrition_context=req.nutrition_context,
        previous_report=req.previous_report,
        threshold_fraction=req.threshold_fraction,
    )


def fatmax_lab(req: FatmaxLabRequest) -> Dict[str, Any]:
    """Build a measured FATmax report from VO2/VCO2 test steps."""
    points = [
        GasExchangePoint(
            power_w=row.power_w,
            vo2_l_min=row.vo2_l_min,
            vco2_l_min=row.vco2_l_min,
            rer=row.rer,
            heart_rate_bpm=row.heart_rate_bpm,
        )
        for row in req.points
    ]
    return build_lab_fatmax_report(
        points,
        athlete_weight_kg=req.athlete.weight_kg if req.athlete else None,
        mlss_power_w=req.mlss_power_w,
        map_power_w=req.map_power_w,
        threshold_fraction=req.threshold_fraction,
    )


def fatmax_compare(req: FatmaxCompareRequest) -> Dict[str, Any]:
    """Compare two FATmax reports and expose curve translation semantics."""
    return {
        "status": "success",
        "schema_version": "fatmax_shift.v1",
        "shift": compare_fatmax_reports(req.previous_report, req.current_report).to_dict(),
    }


def _profile_fatmax_report(self: ProfileExtendedService, req: FatmaxReportRequest) -> Dict[str, Any]:
    return fatmax_report(req)


def _profile_fatmax_lab(self: ProfileExtendedService, req: FatmaxLabRequest) -> Dict[str, Any]:
    return fatmax_lab(req)


def _profile_fatmax_compare(self: ProfileExtendedService, req: FatmaxCompareRequest) -> Dict[str, Any]:
    return fatmax_compare(req)


ProfileExtendedService.fatmax_report = _profile_fatmax_report  # type: ignore[attr-defined]
ProfileExtendedService.fatmax_lab = _profile_fatmax_lab  # type: ignore[attr-defined]
ProfileExtendedService.fatmax_compare = _profile_fatmax_compare  # type: ignore[attr-defined]
