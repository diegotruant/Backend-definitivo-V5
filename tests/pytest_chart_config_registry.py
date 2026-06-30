"""Contract tests for /meta/chart-config registry wiring."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
from engines.io.chart_registry import build_chart_config, get_chart_registry
from tests.conftest import assert_http_engine_json

client = TestClient(app)

_SNAPSHOT = {
    "status": "success",
    "fatmax_power_watts": 185.0,
    "mlss_power_watts": 282.0,
    "map_aerobic_watts": 392.0,
    "estimated_vo2max": 58.0,
    "estimated_vlamax_mmol_L_s": 0.42,
    "combustion_curve": [
        {"watt": 120, "fat_oxidation_g_min_est": 0.4, "carbohydrate_oxidation_g_min_est": 0.2},
        {"watt": 280, "fat_oxidation_g_min_est": 0.2, "carbohydrate_oxidation_g_min_est": 1.0},
    ],
}


def test_chart_registry_exposes_all_builders() -> None:
    registry = get_chart_registry()
    assert len(registry) >= 27
    expected = {
        "metabolic_combustion",
        "cardiac_drift",
        "efforts_radar",
        "phenotype_spider",
        "cross_validation_matrix",
        "hr_kinetics",
        "power_hr_scatter",
        "hr_recovery",
        "vo2_demand",
        "lactate",
        "activity_power",
        "activity_elevation",
        "w_prime_balance",
        "session_fuel_partitioning",
    }
    assert expected.issubset(set(registry.keys()))


def test_meta_chart_types_endpoint_lists_catalog() -> None:
    body = assert_http_engine_json(client.get("/meta/chart-types"))
    assert body["total"] >= 27
    assert "vo2_demand" in body["chart_types"]
    assert "activity_thermal" in body["chart_types"]


def test_chart_config_metabolic_combustion_and_vo2_demand() -> None:
    combustion = build_chart_config(
        "metabolic_combustion",
        {
            "power_points": [100, 200, 300],
            "fat_contribution": [80, 50, 20],
            "carb_contribution": [15, 35, 60],
            "anaerobic_contribution": [5, 15, 20],
        },
    )
    assert combustion["status"] == "success"
    assert combustion["config"]["type"] == "area_stacked"

    vo2 = build_chart_config(
        "vo2_demand",
        {"metabolic_snapshot": _SNAPSHOT, "weight_kg": 72.0},
    )
    assert vo2["config"]["curve_id"] == "vo2_demand"
    assert vo2["config"]["series"]


def test_chart_config_activity_power_from_stream_payload() -> None:
    power = [150.0, 200.0, 220.0, 180.0, 160.0]
    out = build_chart_config("activity_power", {"power": power})
    assert out["status"] == "success"
    assert out["config"].get("type") == "line" or out["config"].get("available") is not False


def test_chart_config_session_fuel_partitioning_includes_fat_series() -> None:
    power = [180.0] * 120 + [280.0] * 180
    out = build_chart_config(
        "session_fuel_partitioning",
        {"metabolic_snapshot": _SNAPSHOT, "power": power, "weight_kg": 72.0},
    )
    names = {s["name"] for s in out["config"]["series"]}
    assert "Fat rate" in names
    assert "Cumulative fat" in names


def test_chart_config_w_prime_balance() -> None:
    power = [200.0] * 60 + [350.0] * 30 + [200.0] * 60
    out = build_chart_config(
        "w_prime_balance",
        {"power": power, "cp_w": 280.0, "w_prime_j": 20000.0},
    )
    assert out["config"]["type"] == "line_multi"
    assert out["config"]["series"][0]["name"] == "W′ balance %"


def test_chart_config_lactate_from_steps() -> None:
    steps = [
        {"power_w": 160, "lactate_mmol": 1.5},
        {"power_w": 220, "lactate_mmol": 2.4},
        {"power_w": 280, "lactate_mmol": 4.1},
        {"power_w": 320, "lactate_mmol": 7.0},
    ]
    out = build_chart_config("lactate", {"lactate_steps": steps})
    assert out["config"]["curve_id"] == "lactate"
    assert out["config"]["measurement_tier"] == "LAB_MEASURED"


def test_meta_chart_config_http_vo2_demand() -> None:
    response = client.post(
        "/meta/chart-config",
        json={
            "chart_type": "vo2_demand",
            "payload": {"metabolic_snapshot": _SNAPSHOT, "weight_kg": 72},
        },
    )
    body = assert_http_engine_json(response)
    assert body["chart_type"] == "vo2_demand"
    assert body["config"]["schema_version"] == "chart_config.v1"
