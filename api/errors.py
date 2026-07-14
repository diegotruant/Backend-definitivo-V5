"""Application-level errors mapped to stable HTTP responses.

``ServiceError`` remains the central application error. Request-boundary
subclasses temporarily retain ``HTTPException`` compatibility so existing
routers and direct unit tests keep working during the staged migration, while
all public response formatting stays centralized in ``api.app``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from fastapi import HTTPException

from engines.core.security import safe_error_detail


@dataclass(slots=True)
class ServiceError(Exception):
    """Base application/domain error handled at the HTTP boundary."""

    message: str
    status_code: int = 400
    code: Optional[str] = None
    details: Optional[Any] = None

    def __str__(self) -> str:
        return self.message


class RequestParsingError(ServiceError, HTTPException):
    """Invalid or incomplete client input detected before engine execution."""


class UploadDomainError(ServiceError, HTTPException):
    """Uploaded activity/test data cannot be accepted or parsed."""


def workout_validation_error(exc: Exception) -> ServiceError:
    return ServiceError(message=str(exc), status_code=400, code="WORKOUT_VALIDATION")


def invalid_json_field(field_name: str, exc: Exception) -> RequestParsingError:
    """Detailed JSON error retained for existing form-field contracts."""

    return RequestParsingError(
        message=f"Invalid {field_name}: {exc}",
        status_code=400,
        code="INVALID_JSON",
    )


def malformed_json_request() -> RequestParsingError:
    return RequestParsingError(
        message="A JSON field in the request was malformed.",
        status_code=400,
        code="INVALID_JSON",
        details=safe_error_detail("INVALID_JSON"),
    )


def json_object_required(field_name: str) -> RequestParsingError:
    return RequestParsingError(
        message=f"{field_name} must be a JSON object.",
        status_code=400,
        code="JSON_OBJECT_REQUIRED",
    )


def non_empty_json_array_required(field_name: str) -> RequestParsingError:
    return RequestParsingError(
        message=f"{field_name} must be a non-empty JSON array.",
        status_code=400,
        code="NON_EMPTY_JSON_ARRAY_REQUIRED",
    )


def invalid_iso_date_error(field_name: str) -> RequestParsingError:
    return RequestParsingError(
        message=f"{field_name} must be ISO date (YYYY-MM-DD).",
        status_code=400,
        code="INVALID_ISO_DATE",
    )


def activity_series_too_long(field_name: str, max_samples: int) -> RequestParsingError:
    code = "POWER_JSON_TOO_LONG" if field_name == "power_json" else "HR_JSON_TOO_LONG"
    message = f"{field_name} exceeds {max_samples} samples."
    return RequestParsingError(
        message=message,
        status_code=413,
        code=code,
        details={"error": code, "message": message},
    )


def missing_activity_input() -> RequestParsingError:
    return RequestParsingError(
        message="Provide either a FIT file or power_json.",
        status_code=400,
        code="MISSING_ACTIVITY_INPUT",
    )


def no_files_uploaded() -> RequestParsingError:
    return RequestParsingError(
        message="No files uploaded.",
        status_code=400,
        code="NO_FILES_UPLOADED",
    )


def too_many_files_uploaded() -> RequestParsingError:
    return RequestParsingError(
        message="Too many files were uploaded in one request.",
        status_code=413,
        code="TOO_MANY_FILES",
        details=safe_error_detail("TOO_MANY_FILES"),
    )


def upload_too_large() -> UploadDomainError:
    return UploadDomainError(
        message="The uploaded file exceeds the allowed size.",
        status_code=413,
        code="FILE_TOO_LARGE",
        details=safe_error_detail("FILE_TOO_LARGE"),
    )


def invalid_fit_file() -> UploadDomainError:
    return UploadDomainError(
        message="The uploaded file is not a readable FIT file.",
        status_code=400,
        code="INVALID_FIT_FILE",
        details=safe_error_detail("INVALID_FIT_FILE"),
    )


def fit_parser_unavailable() -> UploadDomainError:
    return UploadDomainError(
        message="Parser temporarily unavailable.",
        status_code=503,
        code="FIT_PARSER_UNAVAILABLE",
        details={
            "error": "FIT_PARSER_UNAVAILABLE",
            "message": "Parser temporarily unavailable.",
        },
    )
