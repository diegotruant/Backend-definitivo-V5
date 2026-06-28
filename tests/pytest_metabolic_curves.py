"""Coach-facing metabolic curves tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
from engines.metabolic.metabolic_coach_curves import build_vo2_demand_curve
from tests.conftest import assert_http_engine_json

client = TestClient(app)


def _snapshot() -> dict:
    return {
        "status": "success",
        "fatmax_power_watts": 185.0,
        "mlss_power_watts": 282.0,
        "map_aerobic_watts": 392.0,
        "estimated_vo2max": 60.0,
        "estimated_vlamax_mmol_L_s": 0.42,
    }


def test_vo2_demand_curve_returns_pct_vo2max_points() -> None:
    curve = build_vo2_demand_curve(
        _snapshot(),
        weight_kg=72,
        eta=0.22,
        power_points=[120, 185, 282],
    )
    assert curve["measurement_tier"] == "MODEL_ESTIMATE"
    assert curve["curve_id"] == "vo2_demand"
    assert len(curve["points"]) == 3
    assert curve["points"][0]["pct_vo2max"] > 0
    assert curve["points"][-1]["pct_vo2max"] > curve["points"][0]["pct_vo2max"]
    assert any(anchor["label"] == "FATmax" for anchor in curve["anchors"])
    assert "model_parameters" in curve


def test_profile_metabolic_curves_endpoint_for_frontend_contract() -> None:
    response = client.post(
        "/profile/metabolic/curves",
        json={
            "athlete": {"weight_kg": 72, "gender": "MALE", "training_years": 10, "discipline": "ROAD"},
            "mmp": {"5": 900, "60": 480, "300": 340, "1200": 285, "3600": 255},
            "metabolic_snapshot": _snapshot(),
            "expected_eta": 0.22,
            "include_curves": ["vo2_demand"],
        },
    )
    body = assert_http_engine_json(response)
    assert body["schema_version"] == "metabolic_curves.v1"
    assert "vo2_demand" in body["available_curves"]
    vo2_curve = body["curves"]["vo2_demand"]
    assert vo2_curve["x_axis"] == {"key": "power_w", "unit": "W"}
    assert vo2_curve["frontend_hint"]["chart_type"] == "line"
    assert vo2_curve["points"]
