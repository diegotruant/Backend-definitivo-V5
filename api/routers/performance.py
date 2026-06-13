from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile

from api.deps import get_performance_service
from api.helpers import json_response, load_activity_stream
from api.schemas import PowerSourceNormalizationRequest
from api.services.performance_service import PerformanceService

router = APIRouter(tags=["performance"])


@router.post("/performance/neuromuscular-profile")
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


@router.post("/power-source/normalize")
def power_source_normalize(
    req: PowerSourceNormalizationRequest,
    service: PerformanceService = Depends(get_performance_service),
):
    return json_response(service.normalize_power_sources(req))
