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
    GET  /health

This file is intentionally storage-agnostic: it returns serialisable state
(curves, profiles) for the caller to persist in whatever DB they choose, and
accepts that state back on the next call. No global session state.

Run:  uvicorn api_app:app --reload
"""

from __future__ import annotations

import os
import tempfile
from datetime import date
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

from engines.io.fit_parser import parse_fit_file_enhanced
from engines.performance.mmp_aggregator import update_power_curve
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.core.athlete_context import AthleteContext
from engines.core.athlete_physiological_prior import MeasuredProfile
from test_effort_extractor import extract_test_proposal
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
        stream = parse_fit_file_enhanced(tmp.name)
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
    ctx = _ctx(req.athlete.gender, req.athlete.training_years, req.athlete.discipline)
    profiler = MetabolicProfiler(weight=req.athlete.weight_kg, context=ctx)
    mmp = {int(k): float(v) for k, v in req.mmp.items()}
    snap = profiler.generate_metabolic_snapshot(mmp)
    return _json(snap)


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
