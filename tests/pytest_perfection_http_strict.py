"""Stricter HTTP contract gates — empty/malformed bodies must not fake success."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api_app import app
from tests._hardening_utils import assert_json_safe
from tests.openapi_matrix_support import (
    STRICT_INVALID_JSON_4XX,
    invalid_json_payload,
    nested_invalid_payload,
)

client = TestClient(app)


@pytest.mark.parametrize("operation_id", sorted(STRICT_INVALID_JSON_4XX))
def test_strict_endpoints_reject_malformed_json(operation_id: str) -> None:
    from tests.openapi_matrix_support import iter_operations

    operation = next(op for op in iter_operations() if op.operation_id == operation_id)
    payload = nested_invalid_payload(operation)
    response = client.request(operation.method, operation.path, json=payload)
    assert response.status_code != 500, response.text
    assert 400 <= response.status_code < 500, (
        operation_id,
        response.status_code,
        response.text[:300],
    )
    assert_json_safe(response.json())


def test_workout_export_rejects_empty_workout() -> None:
    response = client.post("/workouts/export", json={})
    assert response.status_code == 422
    assert_json_safe(response.json())


def test_season_plan_requires_dates() -> None:
    response = client.post("/planning/create-season-plan", json={"weekly_hours": 8})
    assert response.status_code == 422
    assert_json_safe(response.json())


def test_ability_profile_requires_athlete_context() -> None:
    response = client.post("/performance/ability-profile", json={})
    assert response.status_code == 422
    assert_json_safe(response.json())


def test_breakthroughs_require_curves() -> None:
    response = client.post("/performance/breakthroughs", json={})
    assert response.status_code == 422
    assert_json_safe(response.json())


def test_chart_config_zones_requires_payload() -> None:
    response = client.post(
        "/meta/chart-config",
        json={"chart_type": "zones", "payload": {}},
    )
    assert response.status_code == 422
    assert_json_safe(response.json())
