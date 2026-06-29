"""Activity stream loading from FIT uploads or JSON power arrays."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from typing import Any, List, Optional

from engines.core.security import MAX_POWER_SAMPLES, safe_error_detail
from engines.io.fit_parser import parse_fit_records_enhanced

from api.upload import parse_upload

try:
    from fastapi import HTTPException, UploadFile
except ImportError:  # pragma: no cover
    raise ImportError("FastAPI is required for the API layer: pip install fastapi uvicorn")


def _sanitize_power_sample(value: Any) -> int:
    try:
        sample = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(sample):
        return 0
    return int(max(0.0, sample))


def stream_from_power(
    power: List[float],
    *,
    start: Optional[datetime] = None,
    heart_rate: Optional[List[float]] = None,
) -> Any:
    """Build an ActivityStream-like object from a 1 Hz power list (tests / JSON API).

    Heart rate is never synthesized. Pass ``heart_rate`` explicitly when the client
    has a real HR stream; otherwise HR remains unavailable in the resulting stream.
    """
    base = start or datetime(2026, 1, 1, 8, 0, 0)
    records = []
    measured_signals = ["power"]
    synthetic_signals: list[str] = []
    for i, p in enumerate(power):
        rec: dict[str, Any] = {
            "timestamp": base + timedelta(seconds=i),
            "power": _sanitize_power_sample(p),
        }
        if heart_rate is not None and i < len(heart_rate):
            rec["heart_rate"] = int(max(0, float(heart_rate[i])))
        records.append(rec)
    if heart_rate is not None:
        measured_signals.append("heart_rate")

    stream = parse_fit_records_enhanced(records, session_dict={"sport": "cycling", "start_time": base})
    stream.data_provenance = {
        "source": "power_json",
        "synthetic_signals": synthetic_signals,
        "measured_signals": measured_signals,
    }
    return stream


async def load_activity_stream(
    file: Optional[UploadFile],
    power_json: Optional[str],
    hr_json: Optional[str] = None,
) -> Any:
    if file is not None:
        parsed = await parse_upload(file)
        return parsed["_stream"]
    if power_json:
        try:
            power = json.loads(power_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=safe_error_detail("INVALID_JSON")) from exc
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
        hr_values: Optional[List[float]] = None
        if hr_json:
            try:
                parsed_hr = json.loads(hr_json)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail=safe_error_detail("INVALID_JSON")) from exc
            if not isinstance(parsed_hr, list) or not parsed_hr:
                raise HTTPException(status_code=400, detail="hr_json must be a non-empty JSON array.")
            if len(parsed_hr) > MAX_POWER_SAMPLES:
                raise HTTPException(
                    status_code=413,
                    detail={
                        "error": "HR_JSON_TOO_LONG",
                        "message": f"hr_json exceeds {MAX_POWER_SAMPLES} samples.",
                    },
                )
            hr_values = [float(v) for v in parsed_hr]
        return stream_from_power([_sanitize_power_sample(p) for p in power], heart_rate=hr_values)
    raise HTTPException(status_code=400, detail="Provide either a FIT file or power_json.")
