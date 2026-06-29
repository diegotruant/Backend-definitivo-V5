"""Metabolic curves API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.routers.profile_extended import MetabolicCurvesRequest
from api.services.profile_extended_service import ProfileExtendedService
from api_app import app
from tests.conftest import assert_http_engine_json

client = TestClient(app)


def test_profile_metabolic_curves_endpoint_returns_curve_bundle() -> None:
    response = client.post(
        "/profile/metabolic/curves",
        json={
            "athlete": {"weight_kg": 72, "gender": "MALE", "training_years": 12, "discipline": "ROAD"},
            "mmp": {"5": 900, "60": 480, "300": 340, "1200": 285, "3600": 255},
            "expected_eta": 0.22,
            "metabolic_snapshot": {
                "status": "success",
                "fatmax_power_watts": 185.0,
                "mlss_power_watts": 282.0,
                "map_aerobic_watts": 392.0,
                "estimated_vo2max": 58.0,
                "estimated_vlamax_mmol_L_s": 0.42,
            },
            "lactate_steps": [
                {"power_w": 120, "lactate_mmol": 1.2},
                {"power_w": 170, "lactate_mmol": 1.7},
                {"power_w": 220, "lactate_mmol": 2.4},
                {"power_w": 270, "lactate_mmol": 4.1},
                {"power_w": 320, "lactate_mmol": 7.2},
            ],
            "power_series": [150.0] * 60 + [360.0] * 90 + [140.0] * 120,
            "cp_w": 280,
            "w_prime_j": 18000,
            "ftp_w": 280,
        },
    )
    body = assert_http_engine_json(response)
    assert body["schema_version"] == "metabolic_curves.v1"
    assert "vo2_demand" in body["curves"]
    assert "substrate_oxidation" in body["curves"]
    assert "lactate" in body["available_curves"]
    assert "w_prime_balance" in body["available_curves"]
    assert "durability_decay" in body["curves"]
    assert body["curves"]["vo2_demand"]["points"]
    assert body["curves"]["vo2_demand"]["measurement_tier"] == "MODEL_ESTIMATE"


def test_metabolic_curves_service_returns_insufficient_data_when_snapshot_fails() -> None:
    service = ProfileExtendedService()
    body = service.metabolic_curves(
        MetabolicCurvesRequest.model_validate(
            {
                "athlete": {"weight_kg": 72, "gender": "MALE", "training_years": 5, "discipline": "ROAD"},
                "mmp": {},
            }
        )
    )
    assert body["status"] == "insufficient_data"
    assert body["reason"] == "metabolic_snapshot_generation_failed"
