"""Extended training-load analytics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_load_extended_service
from api.engine_schemas import (
    AcwrRequest,
    AdaptiveRecommendationRequest,
    AdaptiveTrendRequest,
    MonotonyStrainRequest,
)
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.services.load_extended_service import LoadExtendedService

router = APIRouter(tags=["load"])


@router.post("/load/acwr", operation_id="loadAcwr", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def acwr(req: AcwrRequest, service: LoadExtendedService = Depends(get_load_extended_service)):
    return json_response(service.acwr(req))


@router.post("/load/monotony-strain", operation_id="loadMonotonyStrain", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def monotony_strain(req: MonotonyStrainRequest, service: LoadExtendedService = Depends(get_load_extended_service)):
    return json_response(service.monotony_strain(req))


@router.post("/load/adaptive/trend", operation_id="loadAdaptiveTrend", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def adaptive_trend(req: AdaptiveTrendRequest, service: LoadExtendedService = Depends(get_load_extended_service)):
    return json_response(service.adaptive_trend(req.history))


@router.post("/load/adaptive/recommendation", operation_id="loadAdaptiveRecommendation", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def adaptive_recommendation(req: AdaptiveRecommendationRequest, service: LoadExtendedService = Depends(get_load_extended_service)):
    return json_response(service.adaptive_recommendation(req.report))
