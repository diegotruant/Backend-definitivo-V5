from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from api.deps import get_ride_service
from api.helpers import (
    coerce_stored_curve,
    json_response,
    load_activity_stream,
    logger,
    parse_iso_date,
    parse_metabolic_snapshot,
    parse_upload,
)
from api.schemas import AthleteParams, UpdateProfileRequest
from api.services.ride_service import RideService
from engines.core.security import safe_error_detail

router = APIRouter(prefix="/ride", tags=["ride"])


@router.post("/ingest")
async def ingest_ride(
    file: UploadFile = File(...),
    ride_date: str = Form(...),
    weight_kg: float = Form(70.0),
    stored_curve_json: Optional[str] = Form(None),
    service: RideService = Depends(get_ride_service),
):
    try:
        parsed = await parse_upload(file)
    except HTTPException:
        raise
    except Exception as exc:
        logger.info("Cannot parse ride upload %r: %s", file.filename, exc)
        raise HTTPException(status_code=422, detail=safe_error_detail("FIT_PARSE_FAILED"))
    ride_day = parse_iso_date(ride_date, "ride_date")
    stored = json.loads(stored_curve_json) if stored_curve_json else None
    return json_response(
        service.ingest(
            power=parsed["power"],
            ride_date=ride_day,
            file_id=parsed["file_id"],
            weight_kg=weight_kg,
            stored_curve=coerce_stored_curve(stored),
        )
    )


@router.post("/update-profile")
def update_profile(
    req: UpdateProfileRequest,
    service: RideService = Depends(get_ride_service),
):
    return json_response(service.update_profile(req))


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
    service: RideService = Depends(get_ride_service),
):
    stream = await load_activity_stream(file, power_json)
    athlete = AthleteParams(
        weight_kg=weight_kg,
        gender=gender,
        training_years=training_years,
        discipline=discipline,
    )
    return json_response(
        service.build_summary(
            stream,
            weight_kg=weight_kg,
            ftp=ftp,
            lthr=lthr,
            athlete=athlete,
            metabolic_snapshot=parse_metabolic_snapshot(metabolic_snapshot_json),
            hrv_step_seconds=hrv_step_seconds,
            hrv_max_windows=hrv_max_windows,
        )
    )


@router.post("/durability")
async def ride_durability(
    weight_kg: float = Form(...),
    metabolic_snapshot_json: str = Form(...),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    service: RideService = Depends(get_ride_service),
):
    stream = await load_activity_stream(file, power_json)
    snap = parse_metabolic_snapshot(metabolic_snapshot_json)
    return json_response(
        service.compute_durability(stream, weight_kg=weight_kg, metabolic_snapshot=snap or {})
    )
