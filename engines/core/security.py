"""Centralized security limits and input-hardening helpers.

This module exists so the HTTP boundary (api_app.py) and the ingestion engines
share one source of truth for resource limits and untrusted-input handling.
Values are overridable via environment variables so the product layer (white-
label WT integration or multi-tenant SaaS) can tune them without code changes.

It intentionally contains no physiology — only guardrails.
"""

from __future__ import annotations

import os
from typing import Any, Optional


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# --- Resource limits (all overridable via env) ------------------------------
# Single uploaded file (FIT/GPX) hard cap. 40 MB covers very long multi-hour
# rides at 1 Hz with cycling-dynamics fields; well below anything that should
# reach an analytics endpoint.
MAX_UPLOAD_BYTES: int = _env_int("MAX_UPLOAD_BYTES", 40 * 1024 * 1024)

# Max number of files accepted by multi-file endpoints (e.g. /test/propose).
MAX_UPLOAD_FILES: int = _env_int("MAX_UPLOAD_FILES", 25)

# Max raw bytes for a GPX course string before XML parsing.
MAX_GPX_BYTES: int = _env_int("MAX_GPX_BYTES", 20 * 1024 * 1024)

# Max length of an inline power_json array (seconds of 1 Hz data).
MAX_POWER_SAMPLES: int = _env_int("MAX_POWER_SAMPLES", 200_000)

# Season-projection bounds.
MAX_PROJECTION_DAYS: int = _env_int("MAX_PROJECTION_DAYS", 400)
MAX_CALENDAR_EVENTS: int = _env_int("MAX_CALENDAR_EVENTS", 1000)

# Max nesting depth allowed in attacker-supplied JSON (twin_state, calendar).
MAX_JSON_DEPTH: int = _env_int("MAX_JSON_DEPTH", 64)


class PayloadTooLarge(ValueError):
    """Raised when an input exceeds a configured resource limit."""


class PayloadTooDeep(ValueError):
    """Raised when nested JSON exceeds MAX_JSON_DEPTH."""


def enforce_upload_size(num_bytes: int, *, limit: Optional[int] = None) -> None:
    """Raise PayloadTooLarge if an upload exceeds the byte limit."""
    cap = limit if limit is not None else MAX_UPLOAD_BYTES
    if num_bytes > cap:
        raise PayloadTooLarge(
            f"Uploaded file is {num_bytes} bytes; limit is {cap} bytes."
        )


def assert_json_depth(obj: Any, *, limit: Optional[int] = None, _depth: int = 0) -> None:
    """Walk a decoded JSON object and reject pathological nesting.

    Protects recursive helpers (NaN sanitisation, twin-state validation) from
    stack-exhaustion via deeply nested attacker JSON.
    """
    cap = limit if limit is not None else MAX_JSON_DEPTH
    if _depth > cap:
        raise PayloadTooDeep(f"JSON nesting exceeds maximum depth of {cap}.")
    if isinstance(obj, dict):
        for value in obj.values():
            assert_json_depth(value, limit=cap, _depth=_depth + 1)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            assert_json_depth(value, limit=cap, _depth=_depth + 1)


def safe_error_detail(code: str, exc: Optional[BaseException] = None) -> dict:
    """Build a client-safe error body.

    The full exception is meant to be logged server-side by the caller; the
    structure returned here carries a stable machine code and a generic message
    so internal paths, types and stack details never leak to clients.
    """
    return {"error": code, "message": _GENERIC_MESSAGES.get(code, "Request could not be processed.")}


_GENERIC_MESSAGES = {
    "INVALID_FIT_FILE": "The uploaded file is not a readable FIT file.",
    "FIT_PARSE_FAILED": "The uploaded file could not be parsed.",
    "FILE_TOO_LARGE": "The uploaded file exceeds the allowed size.",
    "TOO_MANY_FILES": "Too many files were uploaded in one request.",
    "INVALID_JSON": "A JSON field in the request was malformed.",
    "PAYLOAD_TOO_DEEP": "A JSON field was nested too deeply.",
    "RATE_LIMITED": "Too many requests in a short time window. Please retry later.",
    "UNAUTHORIZED": "Missing or invalid authentication credentials.",
    "FORBIDDEN": "You are not allowed to access this resource.",
    "INVALID_REQUEST": "The request was invalid.",
}
