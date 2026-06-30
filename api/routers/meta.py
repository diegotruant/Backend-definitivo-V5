"""Meta endpoints: engine tiers and chart configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_meta_service
from api.engine_schemas import ChartConfigRequest
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import JSON_OBJECT
from api.services.meta_service import MetaService

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/engine-tiers", operation_id="metaEngineTiers", response_model=EnginePayload, responses={200: JSON_OBJECT})
def engine_tiers(service: MetaService = Depends(get_meta_service)):
    return json_response(service.engine_tiers())


@router.get("/chart-types", operation_id="metaChartTypes", response_model=EnginePayload, responses={200: JSON_OBJECT})
def chart_types(service: MetaService = Depends(get_meta_service)):
    return json_response(service.chart_types())


@router.post("/chart-config", operation_id="metaChartConfig", response_model=EnginePayload, responses={200: JSON_OBJECT})
def chart_config(req: ChartConfigRequest, service: MetaService = Depends(get_meta_service)):
    return json_response(service.chart_config(req))
