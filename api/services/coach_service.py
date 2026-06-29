"""Coach support services — strength, fueling, checkin, safety, attention."""

from __future__ import annotations

from typing import Any, Dict, Optional

from api.coach_schemas import (
    CoachAttentionRequest,
    CoachCheckinRequest,
    CoachDecisionSafetyRequest,
    CoachRosterAttentionRequest,
)
from api.nutrition_schemas import PerformanceFuelingRequest
from api.strength_schemas import StrengthPrescriptionRequest
from engines.coach.attention_engine import evaluate_athlete_attention, evaluate_roster_attention
from engines.coach.checkin_engine import process_checkin
from engines.coach.decision_safety_engine import evaluate_decision_safety
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
