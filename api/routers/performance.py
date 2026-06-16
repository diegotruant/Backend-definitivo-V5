from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile

from api.deps import get_performance_service
from api.helpers import json_response, load_activity_stream
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.schemas import AbilityProfileRequest, BreakthroughRequest, PowerSourceNormalizationRequest
from api.services.performance_service import PerformanceService

router = APIRouter(tags=["performance"])


@router.post(
    "/performance/neuromuscular-profile",
    summary="Neuromuscular sprint profile",
    description="Pmax, cadence-at-peak, repeat-sprint profile from FIT or power stream.",
    operation_id="performanceNeuromuscularProfile",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]},
)
async def neuromuscular_profile(
    weight_kg: float = Form(70.0),
    sprint_threshold_w: Optional[float] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    service: PerformanceService = Depends(get_performance_service),
):
    stream = await load_activity_stream(file, power_json)
    return json_response(
        service.neuromuscular_profile(
            stream,
            weight_kg=weight_kg,
            sprint_threshold_w=sprint_threshold_w,
        )
    )


@router.post(
    "/power-source/normalize",
    summary="Detect power source offsets",
    description="Compare indoor trainer vs outdoor PM systematic offsets.",
    operation_id="powerSourceNormalize",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def power_source_normalize(
    req: PowerSourceNormalizationRequest,
    service: PerformanceService = Depends(get_performance_service),
):
    return json_response(service.normalize_power_sources(req))


@router.post(
    "/performance/ability-profile",
    summary="Ability profile levels",
    description="Zone-specific performance levels from power curve, durability and compliance history.",
    operation_id="performanceAbilityProfile",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def ability_profile(
    req: AbilityProfileRequest,
    service: PerformanceService = Depends(get_performance_service),
):
    return json_response(service.ability_profile(req))


@router.post(
    "/performance/breakthroughs",
    summary="Detect performance breakthroughs",
    description="Compare a new activity power curve against the persisted baseline curve.",
    operation_id="performanceBreakthroughs",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def breakthroughs(
    req: BreakthroughRequest,
    service: PerformanceService = Depends(get_performance_service),
):
    return json_response(service.breakthroughs(req))
