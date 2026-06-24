"""Explainability and confidence narrative endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_explainability_service
from api.engine_schemas import (
    DurabilityNarrativeRequest,
    ExplainabilityAcwrNarrativeRequest,
    ExplainabilityDurabilityConfidenceRequest,
    ExplainabilityMetricNarrativeRequest,
    ExplainabilityVo2ConfidenceRequest,
    ExplainabilityWorkoutSummaryRequest,
)
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.services.explainability_service import ExplainabilityService

router = APIRouter(prefix="/explainability", tags=["explainability"])


@router.post("/vo2max-confidence", operation_id="explainabilityVo2Confidence", response_model=EnginePayload, responses={200: JSON_OBJECT})
def vo2max_confidence(req: ExplainabilityVo2ConfidenceRequest, service: ExplainabilityService = Depends(get_explainability_service)):
    return json_response(service.vo2max_confidence(req))


@router.post("/durability-confidence", operation_id="explainabilityDurabilityConfidence", response_model=EnginePayload, responses={200: JSON_OBJECT})
def durability_confidence(req: ExplainabilityDurabilityConfidenceRequest, service: ExplainabilityService = Depends(get_explainability_service)):
    return json_response(service.durability_confidence(req))


@router.post("/metric-narrative", operation_id="explainabilityMetricNarrative", response_model=EnginePayload, responses={200: JSON_OBJECT})
def metric_narrative(req: ExplainabilityMetricNarrativeRequest, service: ExplainabilityService = Depends(get_explainability_service)):
    return json_response(service.metric_narrative(req))


@router.post("/durability-narrative", operation_id="explainabilityDurabilityNarrative", response_model=EnginePayload, responses={200: JSON_OBJECT})
def durability_narrative(req: DurabilityNarrativeRequest, service: ExplainabilityService = Depends(get_explainability_service)):
    return json_response(service.durability_narrative(req.payload))


@router.post("/acwr-narrative", operation_id="explainabilityAcwrNarrative", response_model=EnginePayload, responses={200: JSON_OBJECT})
def acwr_narrative(req: ExplainabilityAcwrNarrativeRequest, service: ExplainabilityService = Depends(get_explainability_service)):
    return json_response(service.acwr_narrative(req))


@router.post("/workout-summary-narrative", operation_id="explainabilityWorkoutSummaryNarrative", response_model=EnginePayload, responses={200: JSON_OBJECT})
def workout_summary_narrative(req: ExplainabilityWorkoutSummaryRequest, service: ExplainabilityService = Depends(get_explainability_service)):
    return json_response(service.workout_summary_narrative(req))
