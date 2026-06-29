"""Coach support services — strength, fueling, checkin, safety, attention."""

from __future__ import annotations

from typing import Any, Dict, Optional

from api.coach_schemas import (
    CoachAdherenceRequest,
    CoachAttentionRequest,
    CoachCheckinRequest,
    CoachCommunicationDraftRequest,
    CoachDecisionSafetyRequest,
    CoachEnvironmentAdjustmentRequest,
    CoachPeriodizationRequest,
    CoachRaceExecutionRequest,
    CoachRosterAttentionRequest,
    CoachTestingPlanRequest,
)
from api.nutrition_schemas import PerformanceFuelingRequest
from api.strength_schemas import StrengthPrescriptionRequest
from engines.coach.adherence_engine import evaluate_adherence
from engines.coach.attention_engine import evaluate_athlete_attention, evaluate_roster_attention
from engines.coach.checkin_engine import process_checkin
from engines.coach.decision_safety_engine import evaluate_decision_safety
from engines.coach.communication_draft_engine import build_communication_draft
from engines.coach.environment_adjustment_engine import build_environment_adjustment
from engines.coach.periodization_engine import review_periodization
from engines.coach.race_execution_engine import build_race_execution_plan
from engines.coach.testing_scheduler_engine import build_testing_plan
from engines.nutrition.performance_fueling_engine import build_performance_fueling_targets
from engines.strength.strength_prescription_engine import prescribe_strength


def _athlete_id(req: Any) -> Optional[str]:
    if getattr(req, "athlete_id", None):
        return req.athlete_id
    athlete = getattr(req, "athlete", None)
    if athlete is not None and getattr(athlete, "athlete_id", None):
        return athlete.athlete_id
    return None


def _checkin_dict(checkin: Any) -> Optional[Dict[str, Any]]:
    if checkin is None:
        return None
    if hasattr(checkin, "model_dump"):
        return checkin.model_dump(exclude_none=True)
    return dict(checkin)


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

    def checkin(self, req: CoachCheckinRequest) -> Dict[str, Any]:
        data = _checkin_dict(req.checkin) or {}
        return process_checkin(
            athlete_id=_athlete_id(req),
            recent_checkins=req.recent_checkins,
            **data,
        )

    def decision_safety(self, req: CoachDecisionSafetyRequest) -> Dict[str, Any]:
        return evaluate_decision_safety(
            athlete_id=_athlete_id(req),
            twin_state=req.twin_state,
            load_state=req.load_state,
            readiness_state=req.readiness_state,
            last_compliance=req.last_compliance,
            injury_flags=req.injury_flags,
            checkin=_checkin_dict(req.checkin),
            recent_checkins=req.recent_checkins,
            upcoming_key_session=req.upcoming_key_session,
        )

    def attention(self, req: CoachAttentionRequest) -> Dict[str, Any]:
        return evaluate_athlete_attention(
            athlete_id=req.athlete_id,
            twin_state=req.twin_state,
            load_state=req.load_state,
            readiness_state=req.readiness_state,
            checkin=_checkin_dict(req.checkin),
            last_compliance=req.last_compliance,
            upcoming_key_session=req.upcoming_key_session,
            recent_checkins=req.recent_checkins,
        )

    def roster_attention(self, req: CoachRosterAttentionRequest) -> Dict[str, Any]:
        roster = []
        for entry in req.roster:
            roster.append({
                "athlete_id": entry.athlete_id,
                "twin_state": entry.twin_state,
                "load_state": entry.load_state,
                "readiness_state": entry.readiness_state,
                "checkin": _checkin_dict(entry.checkin),
                "last_compliance": entry.last_compliance,
                "upcoming_key_session": entry.upcoming_key_session,
                "recent_checkins": entry.recent_checkins,
            })
        return evaluate_roster_attention(roster)

    def adherence(self, req: CoachAdherenceRequest) -> Dict[str, Any]:
        twin = req.twin_state or {}
        return evaluate_adherence(
            athlete_id=_athlete_id(req),
            planned_workout=req.planned_workout,
            performed_compliance=req.performed_compliance,
            athlete_profile=(req.athlete.model_dump(exclude_none=True) if req.athlete else None)
            or twin.get("athlete_profile"),
            compliance_history=req.compliance_history or twin.get("last_compliance_results"),
            readiness_state=req.readiness_state or twin.get("readiness_state"),
            checkin=_checkin_dict(req.checkin),
        )

    def testing_plan(self, req: CoachTestingPlanRequest) -> Dict[str, Any]:
        twin = req.twin_state or {}
        return build_testing_plan(
            athlete_id=_athlete_id(req),
            metabolic_snapshot=req.metabolic_snapshot or twin.get("metabolic_snapshot"),
            lactate_state=req.lactate_state or twin.get("lactate_state"),
            twin_state=twin,
            season_phase=req.season_phase,
            days_since_last_lactate_test=req.days_since_last_lactate_test,
        )

    def race_execution(self, req: CoachRaceExecutionRequest) -> Dict[str, Any]:
        twin = req.twin_state or {}
        return build_race_execution_plan(
            athlete_id=_athlete_id(req),
            target_event=req.target_event,
            metabolic_snapshot=req.metabolic_snapshot or twin.get("metabolic_snapshot"),
            metabolic_curves=req.metabolic_curves or twin.get("metabolic_curves"),
            twin_state=twin,
            race_simulation=req.race_simulation,
            duration_h=req.duration_h,
        )

    def periodization(self, req: CoachPeriodizationRequest) -> Dict[str, Any]:
        twin = req.twin_state or {}
        return review_periodization(
            athlete_id=_athlete_id(req),
            season_plan=req.season_plan or None,
            start_date=req.start_date,
            target_date=req.target_date,
            weekly_hours=req.weekly_hours,
            goal=req.goal,
            season_phase=req.season_phase,
            strength_prescription=req.strength_prescription or twin.get("strength_state"),
            upcoming_bike_sessions=req.upcoming_bike_sessions,
            load_state=req.load_state or twin.get("load_state"),
            twin_state=twin,
        )

    def communication_draft(self, req: CoachCommunicationDraftRequest) -> Dict[str, Any]:
        twin = req.twin_state or {}
        profile = (req.athlete.model_dump(exclude_none=True) if req.athlete else None) or twin.get("athlete_profile")
        return build_communication_draft(
            athlete_id=_athlete_id(req),
            athlete_profile=profile,
            twin_state=twin,
            decision_safety=req.decision_safety,
            attention=req.attention,
            adherence_report=req.adherence_report,
            checkin=_checkin_dict(req.checkin),
            tone=req.tone,
            channel=req.channel,
        )

    def environment_adjustment(self, req: CoachEnvironmentAdjustmentRequest) -> Dict[str, Any]:
        twin = req.twin_state or {}
        return build_environment_adjustment(
            athlete_id=_athlete_id(req),
            environment_context=req.environment_context,
            metabolic_snapshot=req.metabolic_snapshot or twin.get("metabolic_snapshot"),
            session_context=req.session_context,
            thermal_state=req.thermal_state,
            twin_state=twin,
        )
