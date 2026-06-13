"""Application-level errors mapped to HTTP responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(slots=True)
class ServiceError(Exception):
    """Domain error raised by the service layer."""

    message: str
    status_code: int = 400
    code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        return self.message


def workout_validation_error(exc: Exception) -> ServiceError:
    return ServiceError(message=str(exc), status_code=400, code="WORKOUT_VALIDATION")


def invalid_json_field(field_name: str, exc: Exception) -> ServiceError:
    return ServiceError(
        message=f"Invalid {field_name}: {exc}",
        status_code=400,
        code="INVALID_JSON",
    )
