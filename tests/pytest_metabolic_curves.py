"""Coach-facing metabolic curves tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
from engines.metabolic.metabolic_coach_curves import build_vo2_demand_curve
from engines.twin_state.models import build_twin_state
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


def test_profile_metabolic_curves_endpoint_includes_session_fuel_and_recovery() -> None:
    power = [180.0] * 300 + [330.0] * 60 + [150.0] * 240
    response = client.post(
        "/profile/metabolic/curves",
        json={
            "athlete": {"weight_kg": 72, "gender": "MALE", "training_years": 10, "discipline": "ROAD"},
            "mmp": {"5": 900, "60": 480, "300": 340, "1200": 285, "3600": 255},
            "metabolic_snapshot": _snapshot(),
            "expected_eta": 0.22,
            "power_series": power,
            "dt_s": 1.0,
            "ftp_w": 285,
            "cp_w": 300,
            "w_prime_j": 20000,
            "include_curves": ["session_fuel_demand", "post_effort_recovery"],
        },
    )
    body = assert_http_engine_json(response)
    assert "session_fuel_demand" in body["available_curves"]
    assert "post_effort_recovery" in body["available_curves"]
    fuel = body["curves"]["session_fuel_demand"]
    recovery = body["curves"]["post_effort_recovery"]
    assert fuel["summary"]["carbohydrate_g"] > 0
    assert fuel["summary"]["fat_g"] > 0
    assert recovery["summary"]["estimated_recovery_hours"] >= 6
    assert recovery["measurement_tier"] == "HEURISTIC"


def test_twin_state_serializes_lactate_curve_state() -> None:
    lactate_curve = {
        "curve_id": "lactate",
        "measurement_tier": "LAB_MEASURED",
        "points": [
            {"power_w": 160, "lactate_mmol": 1.5},
            {"power_w": 220, "lactate_mmol": 2.4},
            {"power_w": 280, "lactate_mmol": 4.1},
        ],
        "thresholds": {
            "mlss_dmax_watts": 260.0,
            "obla_4mmol_watts": 276.0,
            "aerobic_2mmol_watts": 195.0,
        },
    }
    twin = build_twin_state(
        {
            "athlete_id": "athlete-1",
            "metabolic_curves": {"curves": {"lactate": lactate_curve}},
            "metabolic_snapshot": _snapshot(),
        }
    )
    assert twin["lactate_state"]["schema_version"] == "lactate_state.v1"
    assert twin["lactate_state"]["thresholds"]["mlss_dmax_watts"] == 260.0
    assert twin["lactate_state"]["last_test_summary"]["points_count"] == 3
