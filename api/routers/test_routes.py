from __future__ import annotations

from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile

from api.helpers import (
    athlete_context,
    json_response,
    logger,
    parse_iso_date,
    parse_upload,
)
from api.schemas import ConfirmRequest, InPersonTestRequest
from engines.core.athlete_context import AthleteContext
from engines.core.security import MAX_UPLOAD_FILES, safe_error_detail
from engines.io.profile_anchor_flow import build_anchor_from_proposal
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.effort_extractor import extract_test_proposal
from engines.performance.test_protocols import run_test as run_in_person_test

router = APIRouter(prefix="/test", tags=["test"])


@router.post("/propose")
async def propose_test(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=413, detail=safe_error_detail("TOO_MANY_FILES"))
    parsed = []
    for f in files:
        try:
            d = await parse_upload(f)
            d.pop("_stream", None)
            parsed.append(d)
        except HTTPException:
            raise
        except Exception as e:
            logger.info("Cannot parse uploaded file %r: %s", f.filename, e)
            raise HTTPException(status_code=422, detail=safe_error_detail("FIT_PARSE_FAILED"))
    proposal = extract_test_proposal(parsed)
    return json_response(proposal.to_dict())


@router.post("/confirm")
def confirm_test(req: ConfirmRequest):
    ctx = athlete_context(req.athlete.gender, req.athlete.training_years, req.athlete.discipline)
    measured_on = parse_iso_date(req.measured_on, "measured_on")
    result = build_anchor_from_proposal(
        req.proposal,
        weight_kg=req.athlete.weight_kg,
        measured_on=measured_on,
        context=ctx,
        active_muscle_mass_kg=req.athlete.active_muscle_mass_kg,
    )
    return json_response(result.to_dict())


@router.post("/in-person")
def in_person_test(req: InPersonTestRequest):
    envelope = req.model_dump()
    athlete = envelope.get("athlete") or {}
    weight = float(athlete.get("weight_kg") or 70.0)
    ctx = AthleteContext(
        gender=str(athlete.get("sex") or athlete.get("gender") or "MALE"),
        training_years=float(athlete.get("training_years") or 10),
        discipline=str(athlete.get("discipline") or "ENDURANCE"),
    )
    profiler = MetabolicProfiler(weight=weight, context=ctx)
    result = run_in_person_test(envelope, profiler=profiler)
    return json_response(result)
