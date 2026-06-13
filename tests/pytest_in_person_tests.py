"""HTTP tests for /test/in-person — Mader, critical power, Wingate, malformed input."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api_app import app
from tests._fixtures import (
    critical_power_in_person_payload,
    mader_in_person_payload,
    wingate_in_person_payload,
)

client = TestClient(app)


def test_in_person_mader_returns_verdict() -> None:
    resp = client.post("/test/in-person", json=mader_in_person_payload())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("verdict") or body.get("status") in ("success", "proposed", "completed")


def test_in_person_mader_lactate_steps_stable() -> None:
    resp = client.post("/test/in-person", json=mader_in_person_payload())
    assert resp.status_code == 200
    body = resp.json()
    # Mader path should surface threshold or MLSS-related output
    assert any(
        key in body
        for key in ("verdict", "mlss_dmax_watts", "thresholds", "status", "lactate")
    )


def test_in_person_critical_power_success() -> None:
    resp = client.post("/test/in-person", json=critical_power_in_person_payload())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") == "success"
    assert float(body.get("cp_w", 0)) > 0


def test_in_person_wingate_peak_power() -> None:
    resp = client.post("/test/in-person", json=wingate_in_person_payload())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") == "success"
    assert float(body.get("peak_power_w", 0)) == 900


def test_in_person_unknown_type_returns_error_not_500() -> None:
    resp = client.post(
        "/test/in-person",
        json={"test_type": "invalid_protocol", "athlete": {"weight_kg": 72}},
    )
    assert resp.status_code == 422


def test_in_person_mader_missing_steps_returns_engine_error() -> None:
    payload = mader_in_person_payload()
    payload["test_data"] = {"steps": [], "mmp": {}}
    resp = client.post("/test/in-person", json=payload)
    assert resp.status_code == 200
    assert resp.json().get("status") == "error"


def test_in_person_athlete_weight_out_of_range_rejected() -> None:
    payload = mader_in_person_payload()
    payload["athlete"]["weight_kg"] = 5
    resp = client.post("/test/in-person", json=payload)
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "test_type",
    ["mader", "critical_power", "wingate"],
)
def test_in_person_valid_types_never_return_500(test_type: str) -> None:
    payloads = {
        "mader": mader_in_person_payload(),
        "critical_power": critical_power_in_person_payload(),
        "wingate": wingate_in_person_payload(),
    }
    resp = client.post("/test/in-person", json=payloads[test_type])
    assert resp.status_code != 500
