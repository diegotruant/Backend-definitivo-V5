"""Security hardening regression tests.

Each test pins one of the fixes applied in the V5.1 security pass so a future
refactor cannot silently remove a guardrail.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api_app
from engines.core import security


client = TestClient(api_app.app)


def test_upload_size_limit_is_enforced():
    with pytest.raises(security.PayloadTooLarge):
        security.enforce_upload_size(security.MAX_UPLOAD_BYTES + 1)
    # At-limit is allowed.
    security.enforce_upload_size(security.MAX_UPLOAD_BYTES)


def test_json_depth_guard_rejects_pathological_nesting():
    obj: object = "leaf"
    for _ in range(security.MAX_JSON_DEPTH + 5):
        obj = {"x": obj}
    with pytest.raises(security.PayloadTooDeep):
        security.assert_json_depth(obj)
    # A shallow object passes.
    security.assert_json_depth({"a": [1, 2, {"b": 3}]})


def test_safe_error_detail_never_leaks_exception_text():
    detail = security.safe_error_detail("INVALID_FIT_FILE", ValueError("/secret/internal/path.fit boom"))
    assert "secret" not in str(detail)
    assert detail["error"] == "INVALID_FIT_FILE"
    assert "message" in detail


def test_projection_rejects_out_of_range_max_days():
    payload = {
        "twin_state": {"athlete_id": "a1"},
        "calendar_plan": [],
        "max_days": 10_000_000,
    }
    resp = client.post("/twin/state/project", json=payload)
    # Pydantic bound (le=MAX_PROJECTION_DAYS) returns 422 before any compute.
    assert resp.status_code == 422


def test_projection_rejects_deeply_nested_twin_state():
    deep: object = {"v": 1}
    for _ in range(security.MAX_JSON_DEPTH + 10):
        deep = {"x": deep}
    payload = {"twin_state": deep, "calendar_plan": [], "max_days": 30}
    resp = client.post("/twin/state/project", json=payload)
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "PAYLOAD_TOO_DEEP"


def test_gpx_parser_is_hardened_against_xxe():
    from engines.performance import race_prediction_engine as rpe

    # If defusedxml is installed the parser is hardened; assert the flag and
    # that a billion-laughs style entity declaration does not expand.
    billion_laughs = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE lolz [<!ENTITY lol "lol">'
        '<!ENTITY lol2 "&lol;&lol;&lol;">]>'
        "<gpx><trkpt lat=\"0\" lon=\"0\"><ele>&lol2;</ele></trkpt></gpx>"
    )
    if rpe._XML_HARDENED:
        with pytest.raises(Exception):
            rpe.parse_gpx_course(billion_laughs)
    else:  # pragma: no cover
        pytest.skip("defusedxml not installed; hardening falls back to stdlib")


def test_health_still_works():
    resp = client.get("/health")
    assert resp.status_code == 200
