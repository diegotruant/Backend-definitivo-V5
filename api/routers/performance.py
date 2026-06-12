from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from api.helpers import json_response, load_activity_stream
from api.schemas import PowerSourceNormalizationRequest
from engines.io.power_source_normalizer import analyze_power_source_offsets
from engines.performance.neuromuscular_profile import analyze_neuromuscular_profile

router = APIRouter(tags=["performance"])


@router.post("/performance/neuromuscular-profile")
async def neuromuscular_profile(
    weight_kg: float = Form(70.0),
    sprint_threshold_w: Optional[float] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
):
    stream = await load_activity_stream(file, power_json)
    return json_response(analyze_neuromuscular_profile(
        stream,
        weight_kg=weight_kg,
        sprint_threshold_w=sprint_threshold_w,
    ))


@router.post("/power-source/normalize")
def power_source_normalize(req: PowerSourceNormalizationRequest):
    return json_response(analyze_power_source_offsets(
        req.activities,
        baseline_source_id=req.baseline_source_id,
        warning_threshold_pct=req.warning_threshold_pct,
        severe_threshold_pct=req.severe_threshold_pct,
    ))
