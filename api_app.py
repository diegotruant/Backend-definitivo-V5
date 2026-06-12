"""
API layer (FastAPI) for the Digital Twin backend.
==================================================

A thin HTTP wrapper over the calculation engines. It does NOT contain any
physiology: every number comes from the engines. Its only jobs are to receive
uploads, route them to the right engine, serialise the result to JSON, and
keep the contract the frontend expects.

Endpoints map 1:1 onto the two product flows documented in the frontend guide:

  Flow A — profile creation (the test)
    POST /test/propose          N FIT files -> ProfileProposal (review)
    POST /test/confirm          confirmed proposal -> MeasuredProfile anchor

  Flow B — monitoring (rides)
    POST /ride/ingest           1 FIT file -> updated power curve
    POST /ride/update-profile   ride MMP + anchor -> updated snapshot

  Read models
    POST /profile/snapshot      MMP -> full metabolic snapshot
    POST /ride/summary          1 FIT (or power JSON) -> workout_summary
    POST /ride/durability       FIT + metabolic snapshot -> mader_durability
    POST /test/in-person        tablet JSON envelope -> test_protocols

  GET  /health

This file is intentionally storage-agnostic: it returns serialisable state
(curves, profiles) for the caller to persist in whatever DB they choose, and
accepts that state back on the next call. No global session state.

Run:  uvicorn api_app:app --reload
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np

try:
    from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
    from fastapi.responses import JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "FastAPI is required for the API layer: pip install fastapi uvicorn"
    ) from e

import logging

from engines.core.security import (
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_FILES,
    MAX_POWER_SAMPLES,
    MAX_PROJECTION_DAYS,
    MAX_CALENDAR_EVENTS,
    PayloadTooLarge,
    PayloadTooDeep,
    assert_json_depth,
    enforce_upload_size,
    safe_error_detail,
)

logger = logging.getLogger("digital_twin.api")

from engines.io.fit_parser import parse_fit_file_enhanced, parse_fit_records_enhanced, FitFileError
from engines.io.workout_summary import build_workout_summary
from engines.performance.mader_durability import compute_session_durability
from engines.performance.mmp_aggregator import update_power_curve
from engines.performance.test_protocols import run_test as run_in_person_test
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.metabolic.team_learning_engine import TeamCalibrationModel, ValidationEvent
from engines.core.athlete_context import AthleteContext
from engines.core.athlete_physiological_prior import MeasuredProfile
from engines.performance.effort_extractor import extract_test_proposal
from engines.io.profile_anchor_flow import build_anchor_from_proposal, update_profile_from_ride
from engines.workouts.models import WorkoutValidationError, validate_workout_payload, materialize_workout
from engines.workouts.feasibility_engine import analyze_workout_feasibility
from engines.workouts.compliance_engine import compare_workout_to_activity
from engines.workouts.calendar_engine import validate_status_transition
from engines.twin_state.models import build_twin_state, validate_twin_state
from engines.twin_state.state_update_engine import update_twin_state_from_ride, update_twin_state_from_workout_result
from engines.projection.season_projection_engine import project_season_from_plan
from engines.performance.neuromuscular_profile import analyze_neuromuscular_profile
from engines.io.power_source_normalizer import analyze_power_source_offsets
from engines.load.manual_load import calculate_manual_load

app = FastAPI(
    title=os.getenv("DIGITAL_TWIN_API_TITLE", "Digital Twin Fisiologico API"),
    version=os.getenv("DIGITAL_TWIN_API_VERSION", "5.1.0"),
)


# CORS: explicit allowlist only. Default is closed; the product layer sets
# DIGITAL_TWIN_CORS_ORIGINS (comma-separated) for the deployed frontend.
_cors_origins = [
    o.strip()
    for o in os.getenv("DIGITAL_TWIN_CORS_ORIGINS", "").split(",")
    if o.strip()
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def _limit_request_body(request: "Request", call_next):
    """Reject oversized requests early using the declared Content-Length.

    This is a cheap first gate; per-file size is still enforced after read in
    _parse_upload (Content-Length can be spoofed or absent on chunked uploads).
    """
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > MAX_UPLOAD_BYTES * (MAX_UPLOAD_FILES + 1):
                return JSONResponse(
                    status_code=413,
                    content=safe_error_detail("FILE_TOO_LARGE"),
                )
        except ValueError:
            pass
    return await call_next(request)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _nan_to_none(obj: Any) -> Any:
    """Recursively replace NaN/Inf with None so the JSON is valid."""
    if isinstance(obj, dict):
        return {k: _nan_to_none(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_nan_to_none(v) for v in obj]
    if isinstance(obj, float):
        return None if (np.isnan(obj) or np.isinf(obj)) else obj
    return obj


def _json(payload: Any) -> JSONResponse:
    return JSONResponse(content=_nan_to_none(payload))


async def _parse_upload(file: UploadFile) -> Dict[str, Any]:
    """Read an uploaded FIT into the {file_id, power, laps} dict the engines use."""
    data = await file.read()
    try:
        enforce_upload_size(len(data))
    except PayloadTooLarge as e:
        logger.warning("Rejected oversized upload %r: %s", file.filename, e)
        raise HTTPException(status_code=413, detail=safe_error_detail("FILE_TOO_LARGE")) from e
    # parse_fit_file_enhanced expects a path; write to a temp file.
    with tempfile.NamedTemporaryFile(suffix=".fit", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            stream = parse_fit_file_enhanced(tmp.name)
        except FitFileError as e:
            logger.info("Invalid FIT upload %r: %s", file.filename, e)
            raise HTTPException(
                status_code=400,
                detail=safe_error_detail("INVALID_FIT_FILE"),
            ) from e
        except RuntimeError as e:
            logger.error("FIT parser unavailable for %r: %s", file.filename, e)
            raise HTTPException(
                status_code=503,
                detail={"error": "FIT_PARSER_UNAVAILABLE", "message": "Parser temporarily unavailable."},
            ) from e
    return {
        "file_id": file.filename or "upload.fit",
        "power": stream.power.tolist(),
        "laps": None,  # lap extraction can be added when the parser exposes it
        "_stream": stream,  # kept for ride ingest; not serialised
    }


def _ctx(gender: str, training_years: float, discipline: str) -> AthleteContext:
    return AthleteContext(
        gender=gender or "MALE",
        training_years=training_years if training_years is not None else 10,
        discipline=discipline or "ENDURANCE",
    )


def _ctx_from_athlete(athlete: "AthleteParams") -> AthleteContext:
    return _ctx(athlete.gender, athlete.training_years, athlete.discipline)


def _parse_metabolic_snapshot(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        snap = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid metabolic_snapshot_json: {e}")
    if not isinstance(snap, dict):
        raise HTTPException(status_code=400, detail="metabolic_snapshot_json must be a JSON object.")
    return snap


def _stream_from_power(power: List[float], *, start: Optional[datetime] = None):
    """Build an ActivityStream-like object from a 1 Hz power list (tests / JSON API)."""
    base = start or datetime(2026, 1, 1, 8, 0, 0)
    records = [
        {
            "timestamp": base + timedelta(seconds=i),
            "power": int(max(0, float(p))),
            "heart_rate": int(140 + (i % 120) * 0.05),
        }
        for i, p in enumerate(power)
    ]
    return parse_fit_records_enhanced(records, session_dict={"sport": "cycling", "start_time": base})


async def _load_activity_stream(
    file: Optional[UploadFile],
    power_json: Optional[str],
) -> Any:
    if file is not None:
        parsed = await _parse_upload(file)
        return parsed["_stream"]
    if power_json:
        try:
            power = json.loads(power_json)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=safe_error_detail("INVALID_JSON")) from e
        if not isinstance(power, list) or not power:
            raise HTTPException(status_code=400, detail="power_json must be a non-empty JSON array.")
        if len(power) > MAX_POWER_SAMPLES:
            raise HTTPException(
                status_code=413,
                detail={"error": "POWER_JSON_TOO_LONG", "message": f"power_json exceeds {MAX_POWER_SAMPLES} samples."},
            )
        return _stream_from_power([float(p) for p in power])
    raise HTTPException(status_code=400, detail="Provide either a FIT file or power_json.")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class AthleteParams(BaseModel):
    weight_kg: float = Field(..., gt=30, lt=200)
    gender: str = "MALE"
    training_years: float = 10
    discipline: str = "ENDURANCE"
    active_muscle_mass_kg: Optional[float] = None


class ConfirmRequest(BaseModel):
    proposal: Dict[str, Any]              # the ProfileProposal.to_dict() the coach confirmed
    athlete: AthleteParams
    measured_on: str                      # ISO date


class UpdateProfileRequest(BaseModel):
    anchor: Dict[str, Any]                # MeasuredProfile fields
    ride_mmp: Dict[str, float]            # {duration_s: power_w}
    athlete: AthleteParams
    as_of: str
    load_factor: float = 1.0


class SnapshotRequest(BaseModel):
    mmp: Dict[str, float]
    athlete: AthleteParams


class RideUpdateCurveRequest(BaseModel):
    # ride power is uploaded as a file; this carries the persisted curve + meta
    stored_curve: Optional[Dict[str, Any]] = None
    ride_date: str
    weight_kg: float = 70.0




class WorkoutValidateRequest(BaseModel):
    """Validate a machine-readable workout template or coach draft."""
    workout: Dict[str, Any]


class WorkoutPrescribeRequest(BaseModel):
    """Resolve a workout template/draft into athlete-specific targets."""
    workout: Dict[str, Any]
    athlete_profile: Dict[str, Any] = Field(default_factory=dict)


class WorkoutFeasibilityRequest(BaseModel):
    """Pre-assignment workout feasibility based on CP/W′ and context."""
    workout: Dict[str, Any]
    athlete_profile: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)


class CalendarTransitionRequest(BaseModel):
    current_status: str
    desired_status: str


class TeamCalibrationUpdateRequest(BaseModel):
    """Stateless team-learning update: previous model + new validation events."""
    team_id: str
    calibration_model: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = Field(default_factory=list)


class TeamCalibrationApplyRequest(BaseModel):
    """Apply a persisted team calibration model to one estimate or snapshot."""
    calibration_model: Dict[str, Any]
    parameter: Optional[str] = None
    predicted_value: Optional[float] = None
    snapshot: Optional[Dict[str, Any]] = None
    athlete_id: Optional[str] = None
    phenotype: Optional[str] = None
    data_depth_score: float = 1.0

class InPersonTestRequest(BaseModel):
    """Tablet envelope — see CONTRATTO_JSON_test.md."""
    test_type: str
    timestamp: Optional[str] = None
    athlete: Dict[str, Any] = Field(default_factory=dict)
    device: Optional[Dict[str, Any]] = None
    test_data: Dict[str, Any] = Field(default_factory=dict)


class TwinStateBuildRequest(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict)


class TwinStateUpdateRideRequest(BaseModel):
    twin_state: Dict[str, Any]
    ride_summary: Optional[Dict[str, Any]] = None
    ingest_result: Optional[Dict[str, Any]] = None
    power_source_report: Optional[Dict[str, Any]] = None
    ride_id: Optional[str] = None


class TwinStateUpdateWorkoutRequest(BaseModel):
    twin_state: Dict[str, Any]
    compliance_result: Dict[str, Any]
    assignment_id: Optional[str] = None


class SeasonProjectionRequest(BaseModel):
    twin_state: Dict[str, Any]
    calendar_plan: List[Dict[str, Any]] = Field(default_factory=list, max_length=MAX_CALENDAR_EVENTS)
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    max_days: int = Field(default=365, ge=1, le=MAX_PROJECTION_DAYS)


class PowerSourceNormalizationRequest(BaseModel):
    activities: List[Dict[str, Any]] = Field(default_factory=list)
    baseline_source_id: Optional[str] = None
    warning_threshold_pct: float = 3.0
    severe_threshold_pct: float = 6.0


class ManualLoadRequest(BaseModel):
    duration_min: float = Field(..., ge=0, le=600)
    rpe: float = Field(..., ge=0, le=10)
    modality: str = "other"
    muscle_damage_factor: Optional[float] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "digital-twin-api", "version": app.version}


# ---------------------------------------------------------------------------
# Flow A — profile creation
# ---------------------------------------------------------------------------
@app.post("/test/propose")
async def propose_test(files: List[UploadFile] = File(...)) -> JSONResponse:
    """
    Accept N FIT files, return a ProfileProposal for coach review.
    The backend proposes; it never auto-commits. The frontend must show this
    for confirmation before calling /test/confirm.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=413, detail=safe_error_detail("TOO_MANY_FILES"))
    parsed = []
    for f in files:
        try:
            d = await _parse_upload(f)
            d.pop("_stream", None)
            parsed.append(d)
        except HTTPException:
            raise
        except Exception as e:
            logger.info("Cannot parse uploaded file %r: %s", f.filename, e)
            raise HTTPException(status_code=422, detail=safe_error_detail("FIT_PARSE_FAILED"))
    proposal = extract_test_proposal(parsed)
    return _json(proposal.to_dict())


@app.post("/test/confirm")
def confirm_test(req: ConfirmRequest) -> JSONResponse:
    """
    Build the measured-profile anchor from a coach-confirmed proposal.
    Returns the anchor (to persist) plus what could/could not be measured.
    """
    ctx = _ctx(req.athlete.gender, req.athlete.training_years, req.athlete.discipline)
    try:
        measured_on = date.fromisoformat(req.measured_on)
    except ValueError:
        raise HTTPException(status_code=400, detail="measured_on must be ISO date (YYYY-MM-DD).")
    result = build_anchor_from_proposal(
        req.proposal,
        weight_kg=req.athlete.weight_kg,
        measured_on=measured_on,
        context=ctx,
        active_muscle_mass_kg=req.athlete.active_muscle_mass_kg,
    )
    return _json(result.to_dict())


# ---------------------------------------------------------------------------
# Flow B — monitoring
# ---------------------------------------------------------------------------
@app.post("/ride/ingest")
async def ingest_ride(
    file: UploadFile = File(...),
    ride_date: str = Form(...),
    weight_kg: float = Form(70.0),
    stored_curve_json: Optional[str] = Form(None),
) -> JSONResponse:
    """
    Ingest one ride FIT, update the rolling power curve, return the new curve
    (to persist) and the MMP. Heavy parsing: run as an async job in production.
    """
    import json
    try:
        d = await _parse_upload(file)
    except HTTPException:
        raise
    except Exception as e:
        logger.info("Cannot parse ride upload %r: %s", file.filename, e)
        raise HTTPException(status_code=422, detail=safe_error_detail("FIT_PARSE_FAILED"))
    try:
        rd = date.fromisoformat(ride_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="ride_date must be ISO date.")
    stored = json.loads(stored_curve_json) if stored_curve_json else None
    # curve dict keys may have been stringified by JSON; coerce back to int.
    if stored:
        stored = {int(k): v for k, v in stored.items()} if all(
            str(k).lstrip("-").isdigit() for k in stored.keys()
        ) else stored
    r = update_power_curve(
        d["power"], rd, stored_curve=stored, ride_id=d["file_id"], weight_kg=weight_kg
    )
    return _json({
        "curve": r.curve,                       # persist this
        "mmp_for_profiler": r.mmp_for_profiler,
        "improvements": len(r.improvements) if r.improvements else 0,
        "ride_usable": r.ride_usable,
        "profile_should_refresh": r.profile_should_refresh,
        "notes": r.notes,
    })


@app.post("/ride/update-profile")
def update_profile(req: UpdateProfileRequest) -> JSONResponse:
    """
    Update the metabolic profile from a ride's MMP, using the stored anchor as
    the prior. Holds the anchor for non-maximal rides (status anchor_held).
    """
    ctx = _ctx(req.athlete.gender, req.athlete.training_years, req.athlete.discipline)
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
        anchor, ride_mmp,
        weight_kg=req.athlete.weight_kg,
        as_of=req.as_of,
        load_factor=req.load_factor,
        context=ctx,
    )
    return _json(out)


# ---------------------------------------------------------------------------
# Read model — full snapshot from an MMP
# ---------------------------------------------------------------------------
@app.post("/profile/snapshot")
def snapshot(req: SnapshotRequest) -> JSONResponse:
    """Full metabolic snapshot from an MMP (the dashboard read model)."""
    ctx = _ctx_from_athlete(req.athlete)
    profiler = MetabolicProfiler(weight=req.athlete.weight_kg, context=ctx)
    mmp = {int(k): float(v) for k, v in req.mmp.items()}
    snap = profiler.generate_metabolic_snapshot(mmp)
    return _json(snap)


# ---------------------------------------------------------------------------
# Activity analysis — summary & mechanistic durability
# ---------------------------------------------------------------------------
@app.post("/ride/summary")
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
) -> JSONResponse:
    """
    Full per-activity report (workout_summary orchestrator).

    Accepts either a FIT upload or a JSON power array (`power_json`, 1 Hz).
    Pass `metabolic_snapshot_json` to enable mader_durability and cardiac
    cross-validation sections.
    """
    stream = await _load_activity_stream(file, power_json)
    snap = _parse_metabolic_snapshot(metabolic_snapshot_json)
    ctx = _ctx(gender, training_years, discipline)
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
    return _json(summary)


@app.post("/ride/durability")
async def ride_durability(
    weight_kg: float = Form(...),
    metabolic_snapshot_json: str = Form(...),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
) -> JSONResponse:
    """
    Mader mechanistic durability: CP residua + sustainable power targets.

    Requires a valid metabolic snapshot (from /profile/snapshot or persisted DB).
    """
    stream = await _load_activity_stream(file, power_json)
    snap = _parse_metabolic_snapshot(metabolic_snapshot_json)
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
    return _json(result)


@app.post("/test/in-person")
def in_person_test(req: InPersonTestRequest) -> JSONResponse:
    """
    Run a tablet in-person test envelope (Mader, CP, Wingate, …).

    Schema: CONTRATTO_JSON_test.md. The frontend sends the full envelope;
    the backend dispatches to test_protocols / lactate_validation_engine.
    """
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
    return _json(result)




# ---------------------------------------------------------------------------
# Workout library / prescription / feasibility / compliance
# ---------------------------------------------------------------------------
@app.post("/workouts/validate")
def validate_workout(req: WorkoutValidateRequest) -> JSONResponse:
    """Validate a workout draft/template before it is saved in the library."""
    try:
        return _json(validate_workout_payload(req.workout))
    except WorkoutValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/workouts/prescribe")
def prescribe_workout(req: WorkoutPrescribeRequest) -> JSONResponse:
    """Materialise percentage-based targets into athlete-specific watts/bpm."""
    try:
        prescription = materialize_workout(req.workout, req.athlete_profile)
    except WorkoutValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _json({
        "status": "success",
        "prescription": prescription,
        "athlete_profile_used": {
            "cp_w": req.athlete_profile.get("cp_w") or req.athlete_profile.get("critical_power_w"),
            "ftp_w": req.athlete_profile.get("ftp_w") or req.athlete_profile.get("ftp"),
            "weight_kg": req.athlete_profile.get("weight_kg"),
        },
    })


@app.post("/workouts/feasibility")
def workout_feasibility(req: WorkoutFeasibilityRequest) -> JSONResponse:
    """Preview whether an athlete can complete a planned workout before assignment."""
    try:
        out = analyze_workout_feasibility(req.workout, req.athlete_profile, req.context)
    except WorkoutValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _json(out)


@app.post("/workouts/compare")
async def workout_compare(
    workout_json: str = Form(...),
    athlete_profile_json: Optional[str] = Form(None),
    tolerance_policy_json: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
) -> JSONResponse:
    """Compare an assigned workout against the performed FIT/power stream."""
    try:
        workout = json.loads(workout_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid workout_json: {e}")
    try:
        athlete_profile = json.loads(athlete_profile_json) if athlete_profile_json else {}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid athlete_profile_json: {e}")
    try:
        tolerance_policy = json.loads(tolerance_policy_json) if tolerance_policy_json else {}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid tolerance_policy_json: {e}")

    stream = await _load_activity_stream(file, power_json)
    try:
        out = compare_workout_to_activity(workout, stream, athlete_profile, tolerance_policy)
    except WorkoutValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _json(out)


@app.post("/workouts/calendar/transition")
def workout_calendar_transition(req: CalendarTransitionRequest) -> JSONResponse:
    """Validate assignment status transitions for DB-backed calendar flows."""
    return _json(validate_status_transition(req.current_status, req.desired_status))


# ---------------------------------------------------------------------------
# Canonical TwinState / projection / additional backend engines
# ---------------------------------------------------------------------------
@app.post("/twin/state/build")
def twin_state_build(req: TwinStateBuildRequest) -> JSONResponse:
    """Build a canonical, versioned TwinState blob for frontend/DB persistence."""
    try:
        return _json(build_twin_state(req.payload))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/twin/state/update-from-ride")
def twin_state_update_from_ride(req: TwinStateUpdateRideRequest) -> JSONResponse:
    """Update TwinState after ride ingest/summary without requiring server state."""
    try:
        return _json(update_twin_state_from_ride(
            req.twin_state,
            ride_summary=req.ride_summary,
            ingest_result=req.ingest_result,
            power_source_report=req.power_source_report,
            ride_id=req.ride_id,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/twin/state/update-from-workout-result")
def twin_state_update_from_workout(req: TwinStateUpdateWorkoutRequest) -> JSONResponse:
    """Append workout compliance result to TwinState."""
    try:
        return _json(update_twin_state_from_workout_result(
            req.twin_state,
            compliance_result=req.compliance_result,
            assignment_id=req.assignment_id,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/twin/state/project")
def twin_state_project(req: SeasonProjectionRequest) -> JSONResponse:
    """Seasonal what-if projection from current TwinState and planned calendar."""
    try:
        assert_json_depth(req.twin_state)
        assert_json_depth(req.calendar_plan)
        return _json(project_season_from_plan(
            req.twin_state,
            req.calendar_plan,
            start_date=req.start_date,
            target_date=req.target_date,
            max_days=req.max_days,
        ))
    except PayloadTooDeep as e:
        raise HTTPException(status_code=400, detail=safe_error_detail("PAYLOAD_TOO_DEEP")) from e
    except (ValueError, WorkoutValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/projection/season")
def projection_season(req: SeasonProjectionRequest) -> JSONResponse:
    """Alias for /twin/state/project."""
    return twin_state_project(req)


@app.post("/performance/neuromuscular-profile")
async def neuromuscular_profile(
    weight_kg: float = Form(70.0),
    sprint_threshold_w: Optional[float] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
) -> JSONResponse:
    """Pmax, cadence-at-peak and repeat sprint profile from FIT or power array."""
    stream = await _load_activity_stream(file, power_json)
    return _json(analyze_neuromuscular_profile(
        stream,
        weight_kg=weight_kg,
        sprint_threshold_w=sprint_threshold_w,
    ))


@app.post("/power-source/normalize")
def power_source_normalize(req: PowerSourceNormalizationRequest) -> JSONResponse:
    """Detect systematic offsets between indoor/outdoor power sources."""
    return _json(analyze_power_source_offsets(
        req.activities,
        baseline_source_id=req.baseline_source_id,
        warning_threshold_pct=req.warning_threshold_pct,
        severe_threshold_pct=req.severe_threshold_pct,
    ))


@app.post("/load/manual")
def manual_load(req: ManualLoadRequest) -> JSONResponse:
    """Inject non-cycling fatigue/load using RPE × duration approximation."""
    return _json(calculate_manual_load(
        duration_min=req.duration_min,
        rpe=req.rpe,
        modality=req.modality,
        muscle_damage_factor=req.muscle_damage_factor,
        notes=req.notes,
    ))


# ---------------------------------------------------------------------------
# Team learning — audited residual calibration
# ---------------------------------------------------------------------------
@app.post("/team/calibration/update")
def update_team_calibration(req: TeamCalibrationUpdateRequest) -> JSONResponse:
    """
    Add validated Mader/lactate/lab events to the team calibration model.

    The caller should pass predictions that were generated BEFORE the test was
    known. The returned model is serialisable and should be persisted by the
    client/database, then sent back on the next update/apply call.
    """
    try:
        if req.calibration_model:
            model = TeamCalibrationModel.from_dict(req.calibration_model)
            if model.team_id != req.team_id:
                raise HTTPException(status_code=400, detail="team_id does not match calibration_model.team_id")
        else:
            model = TeamCalibrationModel(team_id=req.team_id)
        for raw in req.events:
            model.add_event(ValidationEvent.from_dict({**raw, "team_id": raw.get("team_id", req.team_id)}))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _json(model.to_dict())


@app.post("/team/calibration/apply")
def apply_team_calibration(req: TeamCalibrationApplyRequest) -> JSONResponse:
    """
    Apply the learned team/phenotype/athlete correction to a single estimate
    or to a full metabolic snapshot. Returns the corrected value plus audit.
    """
    try:
        model = TeamCalibrationModel.from_dict(req.calibration_model)
        if req.snapshot is not None:
            return _json(model.calibrate_snapshot(
                req.snapshot,
                athlete_id=req.athlete_id,
                phenotype=req.phenotype,
                data_depth_score=req.data_depth_score,
            ))
        if req.parameter is None or req.predicted_value is None:
            raise HTTPException(
                status_code=400,
                detail="Provide either snapshot or both parameter and predicted_value.",
            )
        return _json(model.correction_for(
            req.parameter,
            req.predicted_value,
            athlete_id=req.athlete_id,
            phenotype=req.phenotype,
            data_depth_score=req.data_depth_score,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# ---------------------------------------------------------------------------
# Entry point note (for the developer)
# ---------------------------------------------------------------------------
# Production hardening left to the integrator:
#   * Auth (the engines are stateless; put auth at this layer).
#   * Async job queue for /test/propose and /ride/ingest (parsing is slow).
#   * Persistence: store `curve` and `anchor` per athlete; this layer is
#     deliberately stateless and round-trips them through the client.
#   * The Bayesian profiler is NOT wired here: ride updates use the reliable
#     deterministic fit (see profile_anchor_flow for the rationale).
