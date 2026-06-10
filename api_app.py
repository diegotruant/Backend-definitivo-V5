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
    from fastapi import FastAPI, UploadFile, File, Form, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "FastAPI is required for the API layer: pip install fastapi uvicorn"
    ) from e

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

app = FastAPI(
    title=os.getenv("DIGITAL_TWIN_API_TITLE", "Digital Twin Fisiologico API"),
    version=os.getenv("DIGITAL_TWIN_API_VERSION", "1.0.0"),
)


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
    # parse_fit_file_enhanced expects a path; write to a temp file.
    with tempfile.NamedTemporaryFile(suffix=".fit", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            stream = parse_fit_file_enhanced(tmp.name)
        except FitFileError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "INVALID_FIT_FILE",
                    "reason": e.reason,
                    "message": str(e),
                    "filename": file.filename,
                },
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
            raise HTTPException(status_code=400, detail=f"Invalid power_json: {e}")
        if not isinstance(power, list) or not power:
            raise HTTPException(status_code=400, detail="power_json must be a non-empty JSON array.")
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


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "digital-twin-api", "version": "1.0.0"}


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
    parsed = []
    for f in files:
        try:
            d = await _parse_upload(f)
            d.pop("_stream", None)
            parsed.append(d)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Cannot parse {f.filename}: {e}")
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
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Cannot parse {file.filename}: {e}")
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
