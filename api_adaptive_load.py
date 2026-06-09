"""Standalone FastAPI app exposing the adaptive load endpoint.

This keeps the first integration isolated from api_app.py while reusing the
same parser, context helper pattern, workout summary orchestrator, and new
adaptive_load engine.

Run locally:
    uvicorn api_adaptive_load:app --reload
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from engines.adaptive_load.models import AthleteLoadProfile, DailyStatus
from engines.adaptive_load.orchestrator import build_adaptive_load_report
from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import parse_fit_file_enhanced
from engines.io.workout_summary import build_workout_summary

app = FastAPI(
    title=os.getenv("DIGITAL_TWIN_ADAPTIVE_LOAD_API_TITLE", "Adaptive Load API"),
    version=os.getenv("DIGITAL_TWIN_API_VERSION", "1.0.0"),
)


def _nan_to_none(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _nan_to_none(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_nan_to_none(v) for v in obj]
    if isinstance(obj, float):
        return None if (np.isnan(obj) or np.isinf(obj)) else obj
    return obj


def _json(payload: Any) -> JSONResponse:
    return JSONResponse(content=_nan_to_none(payload))


def _ctx(gender: str, training_years: float, discipline: str) -> AthleteContext:
    return AthleteContext(
        gender=gender or "MALE",
        training_years=training_years if training_years is not None else 10,
        discipline=discipline or "ENDURANCE",
    )


def _parse_optional_object(raw: Optional[str], field_name: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {exc}") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a JSON object.")
    return value


def _parse_optional_list(raw: Optional[str], field_name: str) -> Optional[List[Dict[str, Any]]]:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {exc}") from exc
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a JSON array.")
    return [item for item in value if isinstance(item, dict)]


async def _parse_fit_upload(file: UploadFile):
    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".fit", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        return parse_fit_file_enhanced(tmp.name)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "adaptive-load-api", "version": "1.0.0"}


@app.post("/ride/adaptive-load")
async def ride_adaptive_load(
    weight_kg: float = Form(...),
    ftp: Optional[float] = Form(None),
    hr_max: Optional[float] = Form(None),
    hr_rest: Optional[float] = Form(None),
    lthr: Optional[float] = Form(None),
    gender: str = Form("MALE"),
    training_years: float = Form(10),
    discipline: str = Form("ENDURANCE"),
    metabolic_snapshot_json: Optional[str] = Form(None),
    daily_status_json: Optional[str] = Form(None),
    history_json: Optional[str] = Form(None),
    file: UploadFile = File(...),
) -> JSONResponse:
    """Analyze one FIT and return adaptive session load + recommendation.

    The endpoint is stateless. The caller persists history and sends it back as
    `history_json` on the next call.
    """
    try:
        stream = await _parse_fit_upload(file)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Cannot parse {file.filename}: {exc}") from exc

    metabolic_snapshot = _parse_optional_object(metabolic_snapshot_json, "metabolic_snapshot_json")
    daily_status_raw = _parse_optional_object(daily_status_json, "daily_status_json")
    history = _parse_optional_list(history_json, "history_json")

    ctx = _ctx(gender, training_years, discipline)
    summary = build_workout_summary(
        stream,
        weight_kg=weight_kg,
        ftp=ftp,
        lthr=lthr,
        context=ctx,
        metabolic_snapshot=metabolic_snapshot,
    )
    report = build_adaptive_load_report(
        stream=stream,
        workout_summary=summary,
        athlete_profile=AthleteLoadProfile(
            weight_kg=weight_kg,
            ftp=ftp,
            hr_max=hr_max,
            hr_rest=hr_rest,
            lthr=lthr,
        ),
        daily_status=DailyStatus.from_dict(daily_status_raw),
        history=history,
    )
    return _json(report)
