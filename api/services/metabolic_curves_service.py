from __future__ import annotations

from typing import Any, Dict

from api.metabolic_curve_schemas import MetabolicCurvesRequest
from api.services.engine_context import athlete_context_from_params, mmp_dict, profiler_from_athlete
from engines.metabolic.metabolic_coach_curves import build_metabolic_curves_report


def build_metabolic_curves(req: MetabolicCurvesRequest) -> Dict[str, Any]:
    """Build coach-facing metabolic curves for DB/frontend rendering."""
    snapshot = req.metabolic_snapshot
    if snapshot is None:
        if not req.mmp:
            return {
                "status": "insufficient_data",
                "schema_version": "metabolic_curves.v1",
                "measurement_tier": "INSUFFICIENT_DATA",
                "reason": "metabolic_snapshot_or_mmp_required",
                "curves": {},
                "available_curves": [],
                "missing_curves": [
                    {"curve": "all", "reason": "Provide metabolic_snapshot or MMP plus athlete data."}
                ],
                "confidence_score": 0.0,
            }
        profiler = profiler_from_athlete(req.athlete)
        snapshot = profiler.generate_metabolic_snapshot(
            mmp_dict(req.mmp),
            expected_eta=req.expected_eta,
            measured_lacap=req.measured_lacap,
            effective_cadence_rpm=req.effective_cadence_rpm,
            clean_mmp_first=req.clean_mmp_first,
        )
        if snapshot.get("status") != "success":
            return {
                "status": "insufficient_data",
                "schema_version": "metabolic_curves.v1",
                "measurement_tier": "INSUFFICIENT_DATA",
                "reason": "metabolic_snapshot_generation_failed",
                "source_snapshot": snapshot,
                "curves": {},
                "available_curves": [],
                "missing_curves": [
                    {"curve": "all", "reason": "Metabolic snapshot could not be built from supplied MMP."}
                ],
                "confidence_score": 0.0,
            }

    ctx = athlete_context_from_params(req.athlete)
    lactate_steps = [step.model_dump() for step in req.lactate_steps] if req.lactate_steps else None
    return build_metabolic_curves_report(
        snapshot,
        weight_kg=req.athlete.weight_kg,
        gender=ctx.effective_gender(),
        training_years=ctx.effective_training_years(),
        discipline=ctx.effective_discipline(),
        eta=req.expected_eta,
        power_points=req.power_points,
        lactate_steps=lactate_steps,
        durations_s=req.durations_s,
        include_curves=req.include_curves,
    )
