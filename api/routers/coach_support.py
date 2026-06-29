"""Coach decision-support endpoints (strength, fueling)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

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
