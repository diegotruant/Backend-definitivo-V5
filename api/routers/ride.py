from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from api.deps import get_metabolic_profile_store, get_mmp_aggregate_store, get_ride_service
from api.helpers import (
    coerce_stored_curve,
    json_response,
    load_activity_stream,
    logger,
    parse_iso_date,
    parse_metabolic_snapshot,
    parse_upload,
)
from api.responses import EnginePayload, RideIngestResponse
from api.route_docs import ERRORS, JSON_OBJECT, RIDE_INGEST_OK
from api.schemas import AthleteParams, UpdateProfileRequest
from api.services.ride_service import RideService
from engines.core.security import safe_error_detail

router = APIRouter(prefix="/ride", tags=["ride"])


@router.post(
    "/parse",
    summary="Full FIT parse report",
    description=(
        "Parse a FIT file and return the canonical extraction contract: available signals, "
        "time-series streams, quality flags, laps and provenance metadata."
    ),
    operation_id="rideParse",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413], 422: ERRORS[422]},
)
async def parse_ride(
    file: UploadFile = File(..., description="Ride FIT file."),
    service: RideService = Depends(get_ride_service),
):
    try:
        parsed = await parse_upload(file)
    except HTTPException:
        raise
    except Exception as exc:
        logger.info("Cannot parse ride upload %r: %s", file.filename, exc)
        raise HTTPException(status_code=422, detail=safe_error_detail("FIT_PARSE_FAILED"))
    return json_response(service.build_parse_report(parsed))


@router.post(
    "/ingest",
    summary="Ingest ride FIT and update power curve",
    description="Parse one ride FIT, merge into the rolling MMP curve and return persistable state.",
    operation_id="rideIngest",
    response_model=RideIngestResponse,
    responses={200: RIDE_INGEST_OK, 400: ERRORS[400], 422: ERRORS[422]},
)
async def ingest_ride(
    file: UploadFile = File(..., description="Ride FIT file."),
    ride_date: str = Form(..., description="ISO date YYYY-MM-DD."),
    weight_kg: float = Form(70.0, description="Athlete weight in kg."),
    stored_curve_json: Optional[str] = Form(
        None,
        description="Previously persisted curve JSON (optional).",
    ),
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
            stream=parsed["_stream"],
            ride_date=ride_day,
            file_id=parsed["file_id"],
            weight_kg=weight_kg,
            stored_curve=coerce_stored_curve(stored),
            file_hash=parsed.get("file_hash"),
        )
    )


@router.post(
    "/ingest-with-mmp-aggregate",
    summary="Ingest FIT, build bundle, sync athlete MMP aggregate",
    description=(
        "Worker-oriented pipeline: parse FIT, build full activity bundle, update rolling "
        "curve ingest, extract per-activity MMP points, merge athlete aggregate in Supabase, "
        "and return exposure status (collecting / provisional / published)."
    ),
    operation_id="rideIngestWithMmpAggregate",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400], 422: ERRORS[422]},
)
async def ingest_ride_with_mmp_aggregate(
    file: UploadFile = File(..., description="Ride FIT file."),
    ride_date: str = Form(..., description="ISO date YYYY-MM-DD."),
    athlete_id: str = Form(..., description="Athlete UUID in Supabase."),
    activity_id: str = Form(..., description="Activity UUID for this ingest."),
    activity_file_id: str = Form(..., description="uploaded_files.id for the FIT."),
    weight_kg: float = Form(70.0, description="Athlete weight in kg."),
    stored_curve_json: Optional[str] = Form(
        None,
        description="Previously persisted twin rolling_power_curve JSON (optional).",
    ),
    ftp: Optional[float] = Form(None),
    lthr: Optional[float] = Form(None),
    gender: str = Form("MALE"),
    training_years: float = Form(10),
    discipline: str = Form("ENDURANCE"),
    metabolic_snapshot_json: Optional[str] = Form(None),
    hrv_step_seconds: Optional[float] = Form(None),
    hrv_max_windows: int = Form(500),
    service: RideService = Depends(get_ride_service),
    mmp_store=Depends(get_mmp_aggregate_store),
    profile_store=Depends(get_metabolic_profile_store),
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
    athlete = AthleteParams(
        weight_kg=weight_kg,
        gender=gender,
        training_years=training_years,
        discipline=discipline,
    )
    return json_response(
        service.process_fit_ingest_with_mmp_aggregate(
            stream=parsed["_stream"],
            ride_date=ride_day,
            file_id=parsed["file_id"],
            file_hash=parsed.get("file_hash"),
            weight_kg=weight_kg,
            stored_curve=coerce_stored_curve(stored),
            athlete_id=athlete_id,
            activity_id=activity_id,
            activity_file_id=activity_file_id,
            ftp=ftp,
            lthr=lthr,
            athlete=athlete,
            metabolic_snapshot=parse_metabolic_snapshot(metabolic_snapshot_json),
            hrv_step_seconds=hrv_step_seconds,
            hrv_max_windows=hrv_max_windows,
            mmp_store=mmp_store,
            profile_store=profile_store,
        )
    )


@router.post(
    "/update-profile",
    summary="Update profile from ride MMP",
    description="Bayesian-style profile update using stored anchor and ride MMP.",
    operation_id="rideUpdateProfile",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def update_profile(
    req: UpdateProfileRequest,
    service: RideService = Depends(get_ride_service),
):
    return json_response(service.update_profile(req))


@router.post(
    "/summary",
    summary="Full activity workout summary",
    description="Orchestrated per-activity report (power, zones, cardiac, HRV, mader_durability).",
    operation_id="rideSummary",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]},
)
async def ride_summary(
    weight_kg: float = Form(..., description="Athlete weight kg."),
    ftp: Optional[float] = Form(None, description="Optional FTP override for zones."),
    lthr: Optional[float] = Form(None, description="Optional LTHR override."),
    gender: str = Form("MALE"),
    training_years: float = Form(10),
    discipline: str = Form("ENDURANCE"),
    metabolic_snapshot_json: Optional[str] = Form(
        None,
        description="Successful /profile/snapshot JSON to unlock durability sections.",
    ),
    hrv_step_seconds: Optional[float] = Form(None),
    hrv_max_windows: int = Form(500),
    file: Optional[UploadFile] = File(None, description="Ride FIT file."),
    power_json: Optional[str] = Form(None, description="Alternative: 1 Hz power JSON array."),
    hr_json: Optional[str] = Form(None, description="Optional 1 Hz heart-rate JSON array."),
    service: RideService = Depends(get_ride_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
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


@router.post(
    "/full-bundle",
    summary="Full post-parse activity bundle",
    description=(
        "Parse or load one ride and run the full post-parse contract: parse report, "
        "workout summary, activity intelligence, charts, data quality and engine manifest."
    ),
    operation_id="rideFullBundle",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413], 422: ERRORS[422]},
)
async def ride_full_bundle(
    weight_kg: float = Form(..., description="Athlete weight kg."),
    ftp: Optional[float] = Form(None, description="Optional FTP override for zones."),
    lthr: Optional[float] = Form(None, description="Optional LTHR override."),
    gender: str = Form("MALE"),
    training_years: float = Form(10),
    discipline: str = Form("ENDURANCE"),
    metabolic_snapshot_json: Optional[str] = Form(
        None,
        description="Successful /profile/snapshot JSON to unlock durability sections.",
    ),
    hrv_step_seconds: Optional[float] = Form(None),
    hrv_max_windows: int = Form(500),
    file: Optional[UploadFile] = File(None, description="Ride FIT file."),
    power_json: Optional[str] = Form(None, description="Alternative: 1 Hz power JSON array."),
    hr_json: Optional[str] = Form(None, description="Optional 1 Hz heart-rate JSON array."),
    service: RideService = Depends(get_ride_service),
):
    file_id = "activity.fit"
    file_hash: Optional[str] = None
    if file is not None:
        try:
            parsed = await parse_upload(file)
        except HTTPException:
            raise
        except Exception as exc:
            logger.info("Cannot parse ride upload %r: %s", file.filename, exc)
            raise HTTPException(status_code=422, detail=safe_error_detail("FIT_PARSE_FAILED"))
        stream = parsed["_stream"]
        file_id = str(parsed.get("file_id") or file.filename or file_id)
        file_hash = parsed.get("file_hash")
    else:
        stream = await load_activity_stream(None, power_json, hr_json)
        file_id = "activity.json"
    athlete = AthleteParams(
        weight_kg=weight_kg,
        gender=gender,
        training_years=training_years,
        discipline=discipline,
    )
    return json_response(
        service.build_full_bundle(
            stream,
            weight_kg=weight_kg,
            ftp=ftp,
            lthr=lthr,
            athlete=athlete,
            metabolic_snapshot=parse_metabolic_snapshot(metabolic_snapshot_json),
            hrv_step_seconds=hrv_step_seconds,
            hrv_max_windows=hrv_max_windows,
            file_id=file_id,
            file_hash=file_hash,
        )
    )


@router.post(
    "/durability",
    summary="Mader session durability",
    description="Mechanistic CP residual curve and sustainable power targets for the ride.",
    operation_id="rideDurability",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400], 422: ERRORS[422]},
)
async def ride_durability(
    weight_kg: float = Form(...),
    metabolic_snapshot_json: str = Form(..., description="Required successful metabolic snapshot."),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideService = Depends(get_ride_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    snap = parse_metabolic_snapshot(metabolic_snapshot_json)
    return json_response(
        service.compute_durability(stream, weight_kg=weight_kg, metabolic_snapshot=snap or {})
    )


@router.post(
    "/intelligence",
    summary="Activity intelligence envelope",
    description="Best efforts, zones, intervals, chart series and data-quality report from FIT or power_json.",
    operation_id="rideIntelligence",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]},
)
async def ride_intelligence(
    weight_kg: float = Form(70.0),
    ftp: Optional[float] = Form(None),
    cp: Optional[float] = Form(None),
    lthr: Optional[float] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideService = Depends(get_ride_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    return json_response(service.build_intelligence(stream, weight_kg=weight_kg, ftp=ftp, cp=cp, lthr=lthr))


@router.post(
    "/data-quality",
    summary="Activity data-quality report",
    description="Signal coverage, dropouts, quality flags and sensor availability.",
    operation_id="rideDataQuality",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]},
)
async def ride_data_quality(
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideService = Depends(get_ride_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    return json_response(service.build_data_quality(stream))
