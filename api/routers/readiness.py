from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_readiness_service
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.schemas import LoadRiskRequest, LoadStateUpdateRequest, ReadinessTodayRequest
from api.services.readiness_service import ReadinessService

router = APIRouter(tags=["readiness"])


@router.post("/readiness/today", summary="Daily readiness score", operation_id="readinessToday", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def readiness_today(req: ReadinessTodayRequest, service: ReadinessService = Depends(get_readiness_service)):
    return json_response(service.today(req))


@router.post("/load/state/update", summary="Update load state", operation_id="loadStateUpdate", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def load_state_update(req: LoadStateUpdateRequest, service: ReadinessService = Depends(get_readiness_service)):
    return json_response(service.update_load_state(req))


@router.post("/load/risk", summary="Check load risk", operation_id="loadRisk", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def load_risk(req: LoadRiskRequest, service: ReadinessService = Depends(get_readiness_service)):
    return json_response(service.load_risk(req))
