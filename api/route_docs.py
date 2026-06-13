"""Shared OpenAPI route metadata."""

from __future__ import annotations

from typing import Any, Dict

from api.responses import EnginePayload, ErrorResponse, HealthResponse, RideIngestResponse, WorkoutPrescribeResponse

JSON_OBJECT: Dict[str, Any] = {
    "description": "Engine JSON payload — see docs/FRONTEND_DEVELOPER_GUIDE.md",
    "content": {"application/json": {"schema": EnginePayload.model_json_schema()}},
}

RIDE_INGEST_OK: Dict[str, Any] = {
    "description": "Updated rolling power curve",
    "content": {"application/json": {"schema": RideIngestResponse.model_json_schema()}},
}

WORKOUT_PRESCRIBE_OK: Dict[str, Any] = {
    "description": "Materialised workout prescription",
    "content": {"application/json": {"schema": WorkoutPrescribeResponse.model_json_schema()}},
}

HEALTH_OK: Dict[str, Any] = {
    "description": "Service healthy",
    "content": {"application/json": {"schema": HealthResponse.model_json_schema()}},
}

ERRORS: Dict[int, Dict[str, Any]] = {
    400: {
        "description": "Invalid input",
        "content": {"application/json": {"schema": ErrorResponse.model_json_schema()}},
    },
    413: {
        "description": "Payload too large",
        "content": {"application/json": {"schema": ErrorResponse.model_json_schema()}},
    },
    422: {
        "description": "Unprocessable FIT or activity",
        "content": {"application/json": {"schema": ErrorResponse.model_json_schema()}},
    },
}
