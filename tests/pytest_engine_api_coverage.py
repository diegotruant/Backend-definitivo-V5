"""Smoke tests for extended engine API coverage."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api_app import app
from tests.conftest import assert_http_engine_json, assert_http_json, assert_http_ok

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
        ("/meta/chart-config", {"chart_type": "zones", "payload": {"zones_data": {"coggan": {"Z1": 20, "Z2": 50}}}}),
        ("/meta/chart-config", {"chart_type": "hrv", "payload": {"time_seconds": [0, 60, 120], "dfa_alpha1": [0.9, 0.8, 0.7]}}),
        ("/meta/chart-config", {"chart_type": "training_load", "payload": {"dates": ["2026-01-01"], "ctl_values": [50], "atl_values": [45], "tsb_values": [5]}}),
        ("/meta/chart-config", {"chart_type": "detraining", "payload": {"parameters": ["VO2max"], "baseline_values": [65], "current_values": [62], "units": ["ml/kg/min"]}}),
        ("/ride/analytics/durability/np-drift", {"power": [250] * 3600}),
        ("/ride/analytics/durability/tte-sustainability", {"power": [280] * 1200, "cp": 270}),
        ("/ride/analytics/durability/hourly-decay", {"power": [250] * 7200, "ftp": 250}),
        ("/ride/analytics/durability/prescription", {"durability_index": 93.5}),
        ("/workouts/export", {"workout": {"steps": [{"duration_s": 60, "target_w": 200}]}, "format": "mrc"}),
        ("/workouts/export", {"workout": {"steps": [{"duration_s": 60, "target_w": 200}]}, "format": "zwo"}),
        ("/ride/analytics/w-prime/balance", {"power": [300, 350, 400, 200, 150], "cp": 280, "w_prime": 20000}),
        ("/ride/analytics/durability/index", {"power": [250] * 7200}),
        ("/integrations/activity/normalize", {"activity": {"source": "strava", "duration_s": 3600}}),
        ("/integrations/health/daily-energy", {
            "health_daily": {
                "total_calories_kcal": 2800,
                "active_calories_kcal": 700,
                "basal_calories_kcal": 1600,
            },
            "athlete": ATHLETE,
        }),
    ],
)
def test_extended_engine_endpoints_return_json(path: str, payload: dict) -> None:
    assert_http_json(client.post(path, json=payload))


def test_meta_engine_tiers() -> None:
    body = assert_http_ok(client.get("/meta/engine-tiers"), required_keys=("tiers", "engines"))


def test_twin_state_validate_minimal() -> None:
    build = assert_http_json(
        client.post(
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
        ),
        required_keys=("athlete_id", "schema_version"),
    )
    validate = assert_http_json(
        client.post("/twin/state/validate", json={"twin_state": build}),
        required_keys=("athlete_id", "schema_version"),
    )
    assert validate["athlete_id"] == "api_smoke"


def test_ride_analytics_power_json() -> None:
    power = [200 + (i % 60) for i in range(600)]
    body = assert_http_engine_json(
        client.post(
            "/ride/analytics/power",
            data={"weight_kg": "70", "ftp": "250", "power_json": json.dumps(power)},
        ),
        allowed_statuses={"success"},
    )
    assert body.get("status") == "success"
