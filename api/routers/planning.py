from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_planning_service
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.schemas import AdaptWeekRequest, CheckLoadRiskRequest, CreateSeasonPlanRequest
from api.services.planning_service import PlanningService

router = APIRouter(prefix="/planning", tags=["planning"])


@router.post("/create-season-plan", summary="Create season plan", operation_id="planningCreateSeasonPlan", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def create_plan(req: CreateSeasonPlanRequest, service: PlanningService = Depends(get_planning_service)):
    return json_response(service.create_season_plan(req))


@router.post("/adapt-week", summary="Adapt week plan", operation_id="planningAdaptWeek", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def adapt_week(req: AdaptWeekRequest, service: PlanningService = Depends(get_planning_service)):
    return json_response(service.adapt_week(req))


@router.post("/check-load-risk", summary="Check planned load risk", operation_id="planningCheckLoadRisk", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def check_risk(req: CheckLoadRiskRequest, service: PlanningService = Depends(get_planning_service)):
    return json_response(service.check_load_risk(req))
