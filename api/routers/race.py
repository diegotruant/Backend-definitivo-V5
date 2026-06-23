"""Race course analysis and simulation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_race_service
from api.engine_schemas import RaceGpxAnalyzeRequest, RaceGpxSimulateRequest
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.services.race_service import RaceService

router = APIRouter(prefix="/race", tags=["race"])


@router.post("/gpx/analyze", operation_id="raceGpxAnalyze", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def analyze_gpx(req: RaceGpxAnalyzeRequest, service: RaceService = Depends(get_race_service)):
    return json_response(service.analyze_gpx(req))


@router.post("/gpx/simulate", operation_id="raceGpxSimulate", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def simulate_gpx(req: RaceGpxSimulateRequest, service: RaceService = Depends(get_race_service)):
    return json_response(service.simulate_gpx(req))
