"""Smoke tests for extended engine API coverage."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api_app import app

client = TestClient(app)

ATHLETE = {"weight_kg": 70, "gender": "MALE", "training_years": 10, "discipline": "ENDURANCE"}
MMP = {"5": 900, "60": 400, "300": 320, "1200": 280}


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/profile/snapshot/bayesian", {"mmp": MMP, "athlete": ATHLETE, "n_samples": 500, "n_warmup": 100, "seed": 42}),
        ("/profile/w-prime/tau", {"tau_model": "skiba_default"}),
        ("/profile/mmp-quality", {"mmp": MMP}),
        ("/lab/lactate/thresholds", {"steps": [{"power_w": 200, "lactate_mmol": 2.0}, {"power_w": 250, "lactate_mmol": 4.0}]}),
        ("/lab/vlapeak/observed", {"lactate_pre_mmol": 1.2, "lactate_post_mmol": 8.0, "duration_s": 30}),
        ("/load/acwr", {"acute_load": 400, "chronic_load": 350}),
        ("/load/monotony-strain", {"daily_tss": [50, 60, 55, 70, 45]}),
        ("/explainability/vo2max-confidence", {"mmp_curve": MMP, "efforts_count": 12}),
        ("/meta/chart-config", {"chart_type": "mmp", "payload": {"mmp": {"60": 400, "300": 320}}}),
        ("/ride/analytics/w-prime/balance", {"power": [300, 350, 400, 200, 150], "cp": 280, "w_prime": 20000}),
        ("/ride/analytics/durability/index", {"power": [250] * 7200}),
        ("/integrations/activity/normalize", {"activity": {"source": "strava", "duration_s": 3600}}),
    ],
)
def test_extended_engine_endpoints_return_json(path: str, payload: dict) -> None:
    response = client.post(path, json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)


def test_meta_engine_tiers() -> None:
    response = client.get("/meta/engine-tiers")
    assert response.status_code == 200
    body = response.json()
    assert "tiers" in body
    assert "engines" in body


def test_twin_state_validate_minimal() -> None:
    build = client.post(
        "/twin/state/build",
        json={
            "payload": {
                "athlete_id": "api_smoke",
                "weight_kg": 70,
                "ftp_w": 250,
                "cp_w": 270,
                "w_prime_j": 20000,
            }
        },
    )
    assert build.status_code == 200, build.text
    state = build.json()
    validate = client.post("/twin/state/validate", json={"twin_state": state})
    assert validate.status_code == 200
    assert validate.json()["athlete_id"] == "api_smoke"


def test_ride_analytics_power_json() -> None:
    power = [200 + (i % 60) for i in range(600)]
    response = client.post(
        "/ride/analytics/power",
        data={"weight_kg": "70", "ftp": "250", "power_json": json.dumps(power)},
    )
    assert response.status_code == 200, response.text
    assert response.json().get("status") == "success"
