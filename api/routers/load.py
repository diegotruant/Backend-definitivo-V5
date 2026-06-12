from __future__ import annotations

from fastapi import APIRouter

from api.helpers import json_response
from api.schemas import ManualLoadRequest
from engines.load.manual_load import calculate_manual_load

router = APIRouter(tags=["load"])


@router.post("/load/manual")
def manual_load(req: ManualLoadRequest):
    return json_response(calculate_manual_load(
        duration_min=req.duration_min,
        rpe=req.rpe,
        modality=req.modality,
        muscle_damage_factor=req.muscle_damage_factor,
        notes=req.notes,
    ))
