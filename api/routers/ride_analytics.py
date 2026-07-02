"""Extended ride analytics endpoints (zones, W', durability, cardiac, HRV, routing)."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile

from api.deps import get_ride_analytics_service
from api.engine_schemas import (
    AdaptiveLoadRequest,
    CompareSegmentsRequest,
    CriticalPowerFitRequest,
    DurabilityIndexRequest,
    DurabilityPrescriptionRequest,
    EffortsAnalyzeRequest,
    HourlyDecayRequest,
    MetabolicFlexibilityRequest,
    PowerSeriesRequest,
    ResilienceRequest,
    SessionClassifyRequest,
    ThermalAcclimationRequest,
    TteSustainabilityRequest,
    WPrimeBalanceRequest,
    ZonesAnalyzeRequest,
)
from api.helpers import json_response, load_activity_stream, parse_metabolic_snapshot
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.schemas import AthleteParams
from api.services.ride_analytics_service import RideAnalyticsService

router = APIRouter(prefix="/ride/analytics", tags=["ride"])


@router.post("/zones", operation_id="rideAnalyticsZones", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def zones(
    weight_kg: float = Form(70.0),
    ftp: Optional[float] = Form(None),
    lthr: Optional[float] = Form(None),
    vt1_w: Optional[float] = Form(None),
    vt2_w: Optional[float] = Form(None),
    vt1_bpm: Optional[float] = Form(None),
    vt2_bpm: Optional[float] = Form(None),
    gender: str = Form("MALE"),
    training_years: float = Form(10),
    discipline: str = Form("ENDURANCE"),
    metabolic_snapshot_json: Optional[str] = Form(
        None,
        description="Successful /profile/snapshot JSON — enables MLSS-based metabolic zones alongside Coggan.",
    ),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    req = ZonesAnalyzeRequest(
        athlete=AthleteParams(weight_kg=weight_kg, gender=gender, training_years=training_years, discipline=discipline),
        ftp=ftp,
        lthr=lthr,
        vt1_w=vt1_w,
        vt2_w=vt2_w,
        vt1_bpm=vt1_bpm,
        vt2_bpm=vt2_bpm,
        metabolic_snapshot=parse_metabolic_snapshot(metabolic_snapshot_json),
    )
    return json_response(service.zones(stream, req))


@router.post("/statistics", operation_id="rideAnalyticsStatistics", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def statistics(
    weight_kg: float = Form(70.0),
    ftp: Optional[float] = Form(None),
    lthr: Optional[float] = Form(None),
    cp: Optional[float] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    return json_response(service.statistics(stream, weight_kg=weight_kg, ftp=ftp, lthr=lthr, cp=cp))


@router.post("/power", operation_id="rideAnalyticsPower", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def power_analyze(
    weight_kg: float = Form(70.0),
    ftp: Optional[float] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    return json_response(service.power_analyze(stream, weight_kg=weight_kg, ftp=ftp))


@router.post("/critical-power/fit", operation_id="rideAnalyticsCriticalPowerFit", response_model=EnginePayload, responses={200: JSON_OBJECT})
def critical_power_fit(req: CriticalPowerFitRequest, service: RideAnalyticsService = Depends(get_ride_analytics_service)):
    return json_response(service.critical_power_fit(req.mmp_curve))


@router.post("/w-prime/balance", operation_id="rideAnalyticsWPrimeBalance", response_model=EnginePayload, responses={200: JSON_OBJECT})
def w_prime_balance(req: WPrimeBalanceRequest, service: RideAnalyticsService = Depends(get_ride_analytics_service)):
    return json_response(service.w_prime_balance(req))


@router.post("/durability/index", operation_id="rideAnalyticsDurabilityIndex", response_model=EnginePayload, responses={200: JSON_OBJECT})
def durability_index(req: DurabilityIndexRequest, service: RideAnalyticsService = Depends(get_ride_analytics_service)):
    return json_response(service.durability_index(req))


@router.post("/durability/np-drift", operation_id="rideAnalyticsNpDrift", response_model=EnginePayload, responses={200: JSON_OBJECT})
def np_drift(req: PowerSeriesRequest, service: RideAnalyticsService = Depends(get_ride_analytics_service)):
    return json_response(service.np_drift(req.power))


@router.post("/durability/tte-sustainability", operation_id="rideAnalyticsTteSustainability", response_model=EnginePayload, responses={200: JSON_OBJECT})
def tte_sustainability(req: TteSustainabilityRequest, service: RideAnalyticsService = Depends(get_ride_analytics_service)):
    return json_response(service.tte_sustainability(req.power, cp=req.cp))


@router.post("/durability/hourly-decay", operation_id="rideAnalyticsHourlyDecay", response_model=EnginePayload, responses={200: JSON_OBJECT})
def hourly_decay(req: HourlyDecayRequest, service: RideAnalyticsService = Depends(get_ride_analytics_service)):
    return json_response(service.hourly_decay_curve(req.power, ftp=req.ftp))


@router.post("/durability/prescription", operation_id="rideAnalyticsDurabilityPrescription", response_model=EnginePayload, responses={200: JSON_OBJECT})
def durability_prescription(req: DurabilityPrescriptionRequest, service: RideAnalyticsService = Depends(get_ride_analytics_service)):
    return json_response(service.durability_prescription(req.durability_index))


@router.post("/cardiac", operation_id="rideAnalyticsCardiac", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def cardiac(
    weight_kg: float = Form(70.0),
    gender: str = Form("MALE"),
    training_years: float = Form(10),
    discipline: str = Form("ENDURANCE"),
    metabolic_snapshot_json: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    athlete = AthleteParams(weight_kg=weight_kg, gender=gender, training_years=training_years, discipline=discipline)
    return json_response(service.cardiac(stream, athlete=athlete, metabolic_snapshot=parse_metabolic_snapshot(metabolic_snapshot_json)))


@router.post("/hrv", operation_id="rideAnalyticsHrv", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def hrv(
    window_seconds: int = Form(120),
    step_seconds: float = Form(10.0),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    return json_response(service.hrv_analyze(stream, window_seconds=window_seconds, step_seconds=step_seconds))


@router.post("/thermal/session", operation_id="rideAnalyticsThermalSession", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def thermal_session(
    ftp: Optional[float] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    return json_response(service.thermal_session(stream, ftp=ftp))


@router.post("/thermal/acclimation", operation_id="rideAnalyticsThermalAcclimation", response_model=EnginePayload, responses={200: JSON_OBJECT})
def thermal_acclimation(req: ThermalAcclimationRequest, service: RideAnalyticsService = Depends(get_ride_analytics_service)):
    return json_response(service.thermal_acclimation(req.sessions))


@router.post("/pedaling-balance", operation_id="rideAnalyticsPedalingBalance", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def pedaling_balance(
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    return json_response(service.pedaling_balance(stream))


@router.post("/efforts", operation_id="rideAnalyticsEfforts", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def efforts(
    weight_kg: float = Form(70.0),
    gender: str = Form("MALE"),
    training_years: float = Form(10),
    discipline: str = Form("ENDURANCE"),
    ftp: Optional[float] = Form(None),
    cp_w: Optional[float] = Form(None),
    w_prime_j: Optional[float] = Form(None),
    metabolic_snapshot_json: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    req = EffortsAnalyzeRequest(
        athlete=AthleteParams(weight_kg=weight_kg, gender=gender, training_years=training_years, discipline=discipline),
        metabolic_snapshot=parse_metabolic_snapshot(metabolic_snapshot_json),
        ftp=ftp,
        cp_w=cp_w,
        w_prime_j=w_prime_j,
    )
    return json_response(service.efforts(stream, req))


@router.post("/session/classify", operation_id="rideAnalyticsSessionClassify", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def session_classify(
    weight_kg: float = Form(70.0),
    ftp: Optional[float] = Form(None),
    gender: str = Form("MALE"),
    training_years: float = Form(10),
    discipline: str = Form("ENDURANCE"),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    req = SessionClassifyRequest(
        athlete=AthleteParams(weight_kg=weight_kg, gender=gender, training_years=training_years, discipline=discipline),
        ftp=ftp,
    )
    return json_response(service.classify_session_ride(stream, req))


@router.post("/session/protocol-completeness", operation_id="rideAnalyticsProtocolCompleteness", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def protocol_completeness(
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    return json_response(service.protocol_completeness(stream))


@router.post("/session/route-decide", operation_id="rideAnalyticsSessionRouteDecide", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def session_route_decide(
    ftp: Optional[float] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    return json_response(service.session_route_decide(stream, ftp=ftp))


@router.post("/session/route-run", operation_id="rideAnalyticsSessionRouteRun", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def session_route_run(
    weight_kg: float = Form(70.0),
    ftp: Optional[float] = Form(None),
    gender: str = Form("MALE"),
    training_years: float = Form(10),
    discipline: str = Form("ENDURANCE"),
    metabolic_snapshot_json: Optional[str] = Form(None),
    hrv_step_seconds: Optional[float] = Form(None),
    hrv_max_windows: int = Form(500),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    athlete = AthleteParams(weight_kg=weight_kg, gender=gender, training_years=training_years, discipline=discipline)
    return json_response(
        service.session_route_run(
            stream,
            athlete=athlete,
            ftp=ftp,
            metabolic_snapshot=parse_metabolic_snapshot(metabolic_snapshot_json),
            hrv_step_seconds=10.0 if hrv_step_seconds is None else hrv_step_seconds,
            hrv_max_windows=hrv_max_windows,
        )
    )


@router.post("/resilience", operation_id="rideAnalyticsResilience", response_model=EnginePayload, responses={200: JSON_OBJECT})
def resilience(req: ResilienceRequest, service: RideAnalyticsService = Depends(get_ride_analytics_service)):
    return json_response(service.resilience(mader_durability=req.mader_durability))


@router.post("/metabolic-flexibility", operation_id="rideAnalyticsMetabolicFlexibility", response_model=EnginePayload, responses={200: JSON_OBJECT})
def metabolic_flexibility(req: MetabolicFlexibilityRequest, service: RideAnalyticsService = Depends(get_ride_analytics_service)):
    return json_response(service.metabolic_flexibility(req.snapshot))


@router.post("/segments/climbs", operation_id="rideAnalyticsClimbSegments", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def climb_segments(
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    return json_response(service.climb_segments(stream))


@router.post("/segments/compare", operation_id="rideAnalyticsCompareSegments", response_model=EnginePayload, responses={200: JSON_OBJECT})
def compare_segments(req: CompareSegmentsRequest, service: RideAnalyticsService = Depends(get_ride_analytics_service)):
    return json_response(service.compare_segments(req.history, req.new_segments))


@router.post("/adaptive-load", operation_id="rideAnalyticsAdaptiveLoad", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]})
async def adaptive_load(
    weight_kg: float = Form(70.0),
    ftp: Optional[float] = Form(None),
    gender: str = Form("MALE"),
    training_years: float = Form(10),
    discipline: str = Form("ENDURANCE"),
    workout_summary_json: Optional[str] = Form(None),
    daily_status_json: Optional[str] = Form(None),
    history_json: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    hr_json: Optional[str] = Form(None),
    service: RideAnalyticsService = Depends(get_ride_analytics_service),
):
    stream = await load_activity_stream(file, power_json, hr_json)
    req = AdaptiveLoadRequest(
        athlete=AthleteParams(weight_kg=weight_kg, gender=gender, training_years=training_years, discipline=discipline),
        workout_summary=json.loads(workout_summary_json) if workout_summary_json else {},
        ftp=ftp,
        daily_status=json.loads(daily_status_json) if daily_status_json else None,
        history=json.loads(history_json) if history_json else None,
    )
    return json_response(service.adaptive_load(stream, req))
