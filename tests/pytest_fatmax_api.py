"""FATmax API endpoint smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
from tests.conftest import assert_http_engine_json

client = TestClient(app)


def test_profile_fatmax_lab_endpoint() -> None:
    response = client.post(
        "/profile/fatmax/lab",
        json={
            "athlete": {"weight_kg": 72, "gender": "MALE", "training_years": 12, "discipline": "ROAD"},
            "mlss_power_w": 285,
            "points": [
                {"power_w": 120, "vo2_l_min": 2.05, "vco2_l_min": 1.65},
                {"power_w": 160, "vo2_l_min": 2.45, "vco2_l_min": 1.95},
                {"power_w": 190, "vo2_l_min": 2.80, "vco2_l_min": 2.22},
            ],
        },
    )
    body = assert_http_engine_json(response)
    assert body["measurement_tier"] == "LAB_MEASURED"


def test_profile_fatmax_report_endpoint_model_estimate() -> None:
    response = client.post(
        "/profile/fatmax/report",
        json={
            "athlete": {"weight_kg": 72, "gender": "MALE", "training_years": 12, "discipline": "ROAD"},
            "mmp": {"5": 900, "60": 480, "300": 340, "1200": 285, "3600": 255},
            "metabolic_snapshot": {
                "status": "success",
                "fatmax_power_watts": 185.0,
                "mlss_power_watts": 282.0,
                "map_aerobic_watts": 392.0,
            },
        },
    )
    body = assert_http_engine_json(response)
    assert body["measurement_tier"] == "MODEL_ESTIMATE"


def test_profile_fatmax_compare_endpoint() -> None:
    response = client.post(
        "/profile/fatmax/compare",
        json={
            "previous_report": {"summary": {"fatmax_power_w": 170}},
            "current_report": {"summary": {"fatmax_power_w": 184}},
        },
    )
    body = assert_http_engine_json(response)
    assert body["shift"]["direction"] == "right_shift"
