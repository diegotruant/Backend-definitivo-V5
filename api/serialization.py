"""JSON-safe HTTP response serialization."""

from __future__ import annotations

from typing import Any

import numpy as np

try:
    from fastapi.responses import JSONResponse
except ImportError:  # pragma: no cover
    raise ImportError("FastAPI is required for the API layer: pip install fastapi uvicorn")


def nan_to_none(obj: Any) -> Any:
    """Recursively replace NaN/Inf with None so the JSON is valid."""
    if isinstance(obj, dict):
        return {k: nan_to_none(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [nan_to_none(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [nan_to_none(v) for v in obj.tolist()]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float):
        return None if (np.isnan(obj) or np.isinf(obj)) else obj
    return obj


def json_response(payload: Any) -> JSONResponse:
    return JSONResponse(content=nan_to_none(payload))
