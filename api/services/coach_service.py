"""Coach support services — strength prescription and performance fueling."""

from __future__ import annotations

from typing import Any, Dict

from api.nutrition_schemas import PerformanceFuelingRequest
from api.strength_schemas import StrengthPrescriptionRequest
from engines.nutrition.performance_fueling_engine import build_performance_fueling_targets
from engines.strength.strength_prescription_engine import prescribe_strength


class CoachService:
    def strength_prescription(self, req: StrengthPrescriptionRequest) -> Dict[str, Any]:
        return prescribe_strength(
            athlete=req.athlete.model_dump(exclude_none=True),
            twin_state=req.twin_state,
            metabolic_snapshot=req.metabolic_snapshot,
            metabolic_curves=req.metabolic_curves,
            load_state=req.load_state,
            readiness_state=req.readiness_state,
            mmp=req.mmp,
            goal=req.goal,
            season_phase=req.season_phase,
            gym_experience=req.gym_experience,
            equipment=req.equipment,
            days_available=req.days_available,
            injury_flags=req.injury_flags,
            body_mass_strategy=req.body_mass_strategy,
            upcoming_bike_sessions=[s.model_dump(exclude_none=True) for s in req.upcoming_bike_sessions],
        )

    def performance_fueling_targets(self, req: PerformanceFuelingRequest) -> Dict[str, Any]:
        return build_performance_fueling_targets(
            athlete=req.athlete.model_dump(exclude_none=True),
            twin_state=req.twin_state,
            metabolic_snapshot=req.metabolic_snapshot,
            metabolic_curves=req.metabolic_curves,
            load_state=req.load_state,
            readiness_state=req.readiness_state,
            strength_prescription=req.strength_prescription,
            session_context=req.session_context,
            injury_flags=req.injury_flags,
            power_stream=req.power_series,
        )
