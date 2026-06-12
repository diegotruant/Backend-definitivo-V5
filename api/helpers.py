"""Shared helpers for the HTTP API layer."""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np

from engines.core.athlete_context import AthleteContext
from engines.core.security import (
    MAX_POWER_SAMPLES,
    MAX_UPLOAD_BYTES,
    PayloadTooLarge,
    enforce_upload_size,
    safe_error_detail,
)
from engines.io.fit_parser import FitFileError, parse_fit_file_enhanced, parse_fit_records_enhanced

try:
    from fastapi import HTTPException, UploadFile
    from fastapi.responses import JSONResponse
except ImportError:  # pragma: no cover
    raise ImportError("FastAPI is required for the API layer: pip install fastapi uvicorn")

from api.schemas import AthleteParams

logger = logging.getLogger("digital_twin.api")


def nan_to_none(obj: Any) -> Any:
    """Recursively replace NaN/Inf with None so the JSON is valid."""
    if isinstance(obj, dict):
        return {k: nan_to_none(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [nan_to_none(v) for v in obj]
    if isinstance(obj, float):
        return None if (np.isnan(obj) or np.isinf(obj)) else obj
    return obj


def json_response(payload: Any) -> JSONResponse:
    return JSONResponse(content=nan_to_none(payload))


async def parse_upload(file: UploadFile) -> Dict[str, Any]:
    """Read an uploaded FIT into the {file_id, power, laps} dict the engines use."""
    data = await file.read()
    try:
        enforce_upload_size(len(data))
    except PayloadTooLarge as e:
        logger.warning("Rejected oversized upload %r: %s", file.filename, e)
        raise HTTPException(status_code=413, detail=safe_error_detail("FILE_TOO_LARGE")) from e
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
        "laps": None,
        "_stream": stream,
    }


def athlete_context(gender: str, training_years: float, discipline: str) -> AthleteContext:
    return AthleteContext(
        gender=gender or "MALE",
        training_years=training_years if training_years is not None else 10,
        discipline=discipline or "ENDURANCE",
    )


def athlete_context_from_params(athlete: AthleteParams) -> AthleteContext:
    return athlete_context(athlete.gender, athlete.training_years, athlete.discipline)


def parse_metabolic_snapshot(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        snap = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid metabolic_snapshot_json: {e}")
    if not isinstance(snap, dict):
        raise HTTPException(status_code=400, detail="metabolic_snapshot_json must be a JSON object.")
    return snap


def stream_from_power(power: List[float], *, start: Optional[datetime] = None):
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


async def load_activity_stream(
    file: Optional[UploadFile],
    power_json: Optional[str],
) -> Any:
    if file is not None:
        parsed = await parse_upload(file)
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
                detail={
                    "error": "POWER_JSON_TOO_LONG",
                    "message": f"power_json exceeds {MAX_POWER_SAMPLES} samples.",
                },
            )
        return stream_from_power([float(p) for p in power])
    raise HTTPException(status_code=400, detail="Provide either a FIT file or power_json.")


def parse_iso_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} must be ISO date (YYYY-MM-DD).")


def coerce_stored_curve(stored: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not stored:
        return None
    if all(str(k).lstrip("-").isdigit() for k in stored.keys()):
        return {int(k): v for k, v in stored.items()}
    return stored
