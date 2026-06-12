from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.helpers import (
    athlete_context,
    coerce_stored_curve,
    json_response,
    load_activity_stream,
    logger,
    parse_iso_date,
    parse_metabolic_snapshot,
    parse_upload,
)
from api.schemas import UpdateProfileRequest
from engines.core.athlete_physiological_prior import MeasuredProfile
from engines.core.security import safe_error_detail
from engines.io.profile_anchor_flow import update_profile_from_ride
from engines.io.workout_summary import build_workout_summary
from engines.performance.mader_durability import compute_session_durability
from engines.performance.mmp_aggregator import update_power_curve

router = APIRouter(prefix="/ride", tags=["ride"])


@router.post("/ingest")
async def ingest_ride(
    file: UploadFile = File(...),
    ride_date: str = Form(...),
    weight_kg: float = Form(70.0),
    stored_curve_json: Optional[str] = Form(None),
):
    try:
        d = await parse_upload(file)
    except HTTPException:
        raise
    except Exception as e:
        logger.info("Cannot parse ride upload %r: %s", file.filename, e)
        raise HTTPException(status_code=422, detail=safe_error_detail("FIT_PARSE_FAILED"))
    rd = parse_iso_date(ride_date, "ride_date")
    stored = json.loads(stored_curve_json) if stored_curve_json else None
    stored = coerce_stored_curve(stored)
    r = update_power_curve(
        d["power"], rd, stored_curve=stored, ride_id=d["file_id"], weight_kg=weight_kg
    )
    return json_response({
        "curve": r.curve,
        "mmp_for_profiler": r.mmp_for_profiler,
        "improvements": len(r.improvements) if r.improvements else 0,
        "ride_usable": r.ride_usable,
        "profile_should_refresh": r.profile_should_refresh,
        "notes": r.notes,
    })


@router.post("/update-profile")
def update_profile(req: UpdateProfileRequest):
    ctx = athlete_context(req.athlete.gender, req.athlete.training_years, req.athlete.discipline)
    a = req.anchor
    anchor = MeasuredProfile(
        measured_on=a.get("measured_on", req.as_of),
        vo2max=a.get("vo2max"),
        mlss_watts=a.get("mlss_watts"),
        vlamax=a.get("vlamax"),
        source=a.get("source", "field_test"),
    )
    ride_mmp = {int(k): float(v) for k, v in req.ride_mmp.items()}
    out = update_profile_from_ride(
        anchor,
        ride_mmp,
        weight_kg=req.athlete.weight_kg,
        as_of=req.as_of,
        load_factor=req.load_factor,
        context=ctx,
    )
    return json_response(out)


@router.post("/summary")
async def ride_summary(
    weight_kg: float = Form(...),
    ftp: Optional[float] = Form(None),
    lthr: Optional[float] = Form(None),
    gender: str = Form("MALE"),
    training_years: float = Form(10),
    discipline: str = Form("ENDURANCE"),
    metabolic_snapshot_json: Optional[str] = Form(None),
    hrv_step_seconds: Optional[float] = Form(None),
    hrv_max_windows: int = Form(500),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
):
    stream = await load_activity_stream(file, power_json)
    snap = parse_metabolic_snapshot(metabolic_snapshot_json)
    ctx = athlete_context(gender, training_years, discipline)
    summary = build_workout_summary(
        stream,
        weight_kg=weight_kg,
        ftp=ftp,
        lthr=lthr,
        context=ctx,
        metabolic_snapshot=snap,
        hrv_step_seconds=hrv_step_seconds,
        hrv_max_windows=hrv_max_windows,
    )
    return json_response(summary)


@router.post("/durability")
async def ride_durability(
    weight_kg: float = Form(...),
    metabolic_snapshot_json: str = Form(...),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
):
    stream = await load_activity_stream(file, power_json)
    snap = parse_metabolic_snapshot(metabolic_snapshot_json)
    if not snap or snap.get("status") != "success":
        raise HTTPException(
            status_code=400,
            detail="metabolic_snapshot_json must be a successful generate_metabolic_snapshot() payload.",
        )
    if not getattr(stream, "has_power", False):
        raise HTTPException(status_code=422, detail="Activity has no power data.")
    power = [
        float(p or 0.0)
        for p in stream.power[: getattr(stream, "n_samples", len(stream.power))]
    ]
    result = compute_session_durability(power, snap, weight_kg=weight_kg)
    return json_response(result)
