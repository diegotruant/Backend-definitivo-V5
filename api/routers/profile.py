from __future__ import annotations

from fastapi import APIRouter

from api.helpers import athlete_context_from_params, json_response
from api.schemas import SnapshotRequest
from engines.metabolic.metabolic_profiler import MetabolicProfiler

router = APIRouter(prefix="/profile", tags=["profile"])


@router.post("/snapshot")
def snapshot(req: SnapshotRequest):
    ctx = athlete_context_from_params(req.athlete)
    profiler = MetabolicProfiler(weight=req.athlete.weight_kg, context=ctx)
    mmp = {int(k): float(v) for k, v in req.mmp.items()}
    snap = profiler.generate_metabolic_snapshot(mmp)
    return json_response(snap)
