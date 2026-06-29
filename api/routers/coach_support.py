"""Coach decision-support endpoints (strength, fueling)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

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
from api.deps import get_coach_service
from api.helpers import json_response
from api.nutrition_schemas import PerformanceFuelingRequest
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.services.coach_service import CoachService
from api.strength_schemas import StrengthPrescriptionRequest

router = APIRouter(prefix="/coach", tags=["coach"])


@router.post(
    "/strength/prescription",
    operation_id="coachStrengthPrescription",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
    summary="Physiology-first strength prescription",
    description=(
        "Generate strength blocks, interference rules and expected adaptations from "
        "TwinState physiology — not a generic gym template."
    ),
)
def strength_prescription(
    req: StrengthPrescriptionRequest,
    service: CoachService = Depends(get_coach_service),
):
    return json_response(service.strength_prescription(req))


@router.post(
    "/nutrition/performance-targets",
    operation_id="coachNutritionPerformanceTargets",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
    summary="Performance fueling availability targets",
    description=(
        "Return carbohydrate availability, recovery priorities and red flags. "
        "Not a diet or meal plan."
    ),
)
def nutrition_performance_targets(
    req: PerformanceFuelingRequest,
    service: CoachService = Depends(get_coach_service),
):
    return json_response(service.performance_fueling_targets(req))


@router.post(
    "/checkin",
    operation_id="coachCheckin",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
    summary="Athlete subjective check-in",
    description="Collect subjective signals and flag when human coach review is recommended.",
)
def coach_checkin(
    req: CoachCheckinRequest,
    service: CoachService = Depends(get_coach_service),
):
    return json_response(service.checkin(req))


@router.post(
    "/decision-safety",
    operation_id="coachDecisionSafety",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
    summary="Unified prescription and intensity safety gate",
)
def coach_decision_safety(
    req: CoachDecisionSafetyRequest,
    service: CoachService = Depends(get_coach_service),
):
    return json_response(service.decision_safety(req))


@router.post(
    "/attention",
    operation_id="coachAttention",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
    summary="Coach attention priority for one athlete",
)
def coach_attention(
    req: CoachAttentionRequest,
    service: CoachService = Depends(get_coach_service),
):
    return json_response(service.attention(req))


@router.post(
    "/attention/roster",
    operation_id="coachRosterAttention",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
    summary="Rank roster by coach attention priority",
)
def coach_roster_attention(
    req: CoachRosterAttentionRequest,
    service: CoachService = Depends(get_coach_service),
):
    return json_response(service.roster_attention(req))


@router.post(
    "/adherence",
    operation_id="coachAdherence",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
    summary="Planned vs performed adherence analysis",
)
def coach_adherence(
    req: CoachAdherenceRequest,
    service: CoachService = Depends(get_coach_service),
):
    return json_response(service.adherence(req))


@router.post(
    "/testing-plan",
    operation_id="coachTestingPlan",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
    summary="Recommend priority calibration tests",
)
def coach_testing_plan(
    req: CoachTestingPlanRequest,
    service: CoachService = Depends(get_coach_service),
):
    return json_response(service.testing_plan(req))


@router.post(
    "/race-execution",
    operation_id="coachRaceExecution",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
    summary="Race pacing, fueling and failure-mode plan",
)
def coach_race_execution(
    req: CoachRaceExecutionRequest,
    service: CoachService = Depends(get_coach_service),
):
    return json_response(service.race_execution(req))


@router.post(
    "/periodization",
    operation_id="coachPeriodization",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
    summary="Macro plan coherence and conflict review",
)
def coach_periodization(
    req: CoachPeriodizationRequest,
    service: CoachService = Depends(get_coach_service),
):
    return json_response(service.periodization(req))


@router.post(
    "/communication-draft",
    operation_id="coachCommunicationDraft",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
    summary="Supportive coach message draft for human review",
    description="Generates editable message text — not autonomous coaching or diagnosis.",
)
def coach_communication_draft(
    req: CoachCommunicationDraftRequest,
    service: CoachService = Depends(get_coach_service),
):
    return json_response(service.communication_draft(req))


@router.post(
    "/environment-adjustment",
    operation_id="coachEnvironmentAdjustment",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
    summary="Heat, humidity and altitude session adjustments",
)
def coach_environment_adjustment(
    req: CoachEnvironmentAdjustmentRequest,
    service: CoachService = Depends(get_coach_service),
):
    return json_response(service.environment_adjustment(req))
