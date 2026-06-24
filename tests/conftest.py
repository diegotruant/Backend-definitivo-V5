"""Shared pytest fixtures and strict assertion helpers for the test suite.

Policy: tests must fail when behaviour regresses. Avoid xfail masking,
bare ``pass`` in except blocks, and tautological assertions (e.g. ``>= 0``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pytest

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_JSON = ROOT / "openapi" / "openapi.json"


def load_openapi_path_count() -> int:
    spec = json.loads(OPENAPI_JSON.read_text(encoding="utf-8"))
    return len(spec.get("paths", {}))


EXPECTED_OPENAPI_PATH_COUNT = load_openapi_path_count()

FORBIDDEN_ENGINE_STATUSES = frozenset({"error", "failed", "internal_error"})


def assert_engine_response(
    body: Any,
    *,
    allowed_statuses: Iterable[str] | None = None,
) -> str:
    """Assert an engine/API JSON body exposes a meaningful status — not a silent failure."""
    assert isinstance(body, dict), f"expected dict response, got {type(body)}"
    status = body.get("status")
    assert status is not None, f"response missing status field: {body}"
    status_str = str(status)
    if allowed_statuses is not None:
        allowed = frozenset(allowed_statuses)
        assert status_str in allowed, f"status {status_str!r} not in {sorted(allowed)}: {body}"
    else:
        assert status_str not in FORBIDDEN_ENGINE_STATUSES, f"forbidden engine status: {body}"
    return status_str


def assert_http_json(
    response: Any,
    *,
    allowed_statuses: Iterable[str] | None = None,
    required_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Strict HTTP JSON check.

    - Always requires HTTP 200 and a non-empty dict body.
    - If ``status`` is present, it must be meaningful (not ``error``/``failed``).
    - ``allowed_statuses`` applies only when a status field exists.
  """
    assert response.status_code == 200, getattr(response, "text", response)
    body = response.json()
    assert isinstance(body, dict), f"expected JSON object, got {type(body)}"
    assert body, f"empty JSON object: {body}"
    status = body.get("status")
    if status is not None:
        assert_engine_response(body, allowed_statuses=allowed_statuses)
    if required_keys is not None:
        missing = [key for key in required_keys if key not in body]
        assert not missing, f"missing keys {missing} in {body}"
    return body


def assert_http_ok(response: Any, *, required_keys: Iterable[str] | None = None) -> dict[str, Any]:
    """Alias for routes that may omit engine ``status`` but must still return JSON."""
    return assert_http_json(response, required_keys=required_keys)


def assert_http_engine_json(response: Any, *, allowed_statuses: Iterable[str] | None = None) -> dict[str, Any]:
    """Engine routes that must expose a ``status`` field."""
    body = assert_http_json(response, allowed_statuses=allowed_statuses)
    assert "status" in body, f"engine route missing status field: {body}"
    return body


@pytest.fixture(scope="session")
def openapi_path_count() -> int:
    return EXPECTED_OPENAPI_PATH_COUNT


@pytest.fixture
def simple_power_workout() -> dict[str, Any]:
    return {
        "workout_id": "hardening_simple",
        "title": "Hardening simple intervals",
        "steps": [
            {"step_id": "warmup", "type": "warmup", "duration_s": 60, "target_w": 150},
            {"step_id": "work_1", "type": "work", "duration_s": 90, "target_w": 320, "is_key_step": True},
            {"step_id": "recovery", "type": "recovery", "duration_s": 60, "target_w": 120},
            {"step_id": "work_2", "type": "work", "duration_s": 90, "target_w": 320, "is_key_step": True},
        ],
    }
