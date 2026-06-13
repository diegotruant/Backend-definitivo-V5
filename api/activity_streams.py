"""Activity stream loading from FIT uploads or JSON power arrays."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, List, Optional

from engines.core.security import MAX_POWER_SAMPLES, safe_error_detail
from engines.io.fit_parser import parse_fit_records_enhanced

from api.upload import parse_upload

try:
    from fastapi import HTTPException, UploadFile
except ImportError:  # pragma: no cover
    raise ImportError("FastAPI is required for the API layer: pip install fastapi uvicorn")


def stream_from_power(power: List[float], *, start: Optional[datetime] = None) -> Any:
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
        return stream_from_power([float(p) for p in power])
    raise HTTPException(status_code=400, detail="Provide either a FIT file or power_json.")
