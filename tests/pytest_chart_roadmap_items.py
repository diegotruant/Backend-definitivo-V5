"""Tests for chart roadmap items (ACWR, readiness, durability, race, Kalman, PMC, segments, dashboard)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from api_app import app
from engines.io.chart_registry import build_chart_config, get_chart_registry
from engines.performance.consistency_engine import calculate_eddington_number
from tests.conftest import assert_http_engine_json
from tests.pytest_phase5_race_prediction_port import GPX

client = TestClient(app)

_KALMAN_STATES = [
    {
        "date": (date.today() - timedelta(days=2)).isoformat(),
        "vo2max": 55.0,
        "vo2max_std": 2.0,
        "vo2max_ci95": [51.1, 58.9],
    },
    {
        "date": (date.today() - timedelta(days=1)).isoformat(),
        "vo2max": 55.8,
        "vo2max_std": 1.8,
        "vo2max_ci95": [52.3, 59.3],
    },
    {
        "date": date.today().isoformat(),
        "vo2max": 56.2,
        "vo2max_std": 1.6,
        "vo2max_ci95": [53.1, 59.3],
    },
]

_ROADMAP_TYPES = {
    "acwr_trend",
    "monotony_strain",
    "readiness_trend",
    "durability_fingerprint",
    "race_simulation_overlay",
    "kalman_trajectory",
    "pmc_forecast",
    "segment_history",
    "eddington_consistency",
}


def test_registry_includes_roadmap_chart_types() -> None:
    registry = get_chart_registry()
    assert _ROADMAP_TYPES.issubset(set(registry.keys()))
    assert len(registry) >= 42


def test_acwr_trend_from_atl_ctl() -> None:
    dates = [date.today() - timedelta(days=i) for i in range(3, 0, -1)]
    out = build_chart_config(
        "acwr_trend",
        {"dates": dates, "atl_values": [70, 65, 60], "ctl_values": [55, 56, 57]},
    )
    assert out["config"]["schema_version"] == "chart_config.v1"
    assert out["config"]["series"][0]["name"] == "ACWR"


def test_monotony_strain_from_daily_tss() -> None:
    out = build_chart_config("monotony_strain", {"daily_tss": [80, 65, 90, 75, 100, 60, 85]})
    assert out["config"]["type"] == "combo"
    assert "Monotony" in {s["name"] for s in out["config"]["series"]}


def test_readiness_trend_with_components() -> None:
    dates = [date.today() - timedelta(days=i) for i in range(2, -1, -1)]
    out = build_chart_config(
        "readiness_trend",
        {
            "dates": dates,
            "readiness_scores": [72, 68, 75],
            "hrv_component": [0.7, 0.65, 0.72],
        },
    )
    names = {s["name"] for s in out["config"]["series"]}
    assert "Readiness" in names
    assert "HRV" in names


def test_durability_fingerprint_from_power() -> None:
    power = [250.0] * 7200 + [230.0] * 3600
    out = build_chart_config(
        "durability_fingerprint",
        {"power": power, "duration_s": len(power), "threshold_power": 280},
    )
    assert out["config"]["type"] == "radar"
    assert out["config"]["categories"]


def test_race_simulation_overlay_from_gpx() -> None:
    out = build_chart_config(
        "race_simulation_overlay",
        {"gpx": GPX, "weight_kg": 72.0, "ftp_w": 300.0},
    )
    assert out["config"]["type"] == "line_multi"
    assert len(out["config"]["series"]) >= 2


def test_kalman_trajectory_ci_bands() -> None:
    out = build_chart_config("kalman_trajectory", {"states": _KALMAN_STATES})
    assert out["config"]["type"] == "line_band"
    assert "95% CI" in out["config"]["series"][1]["name"]


def test_pmc_forecast_with_split() -> None:
    dates = [date.today() + timedelta(days=i) for i in range(7)]
    out = build_chart_config(
        "pmc_forecast",
        {
            "dates": dates,
            "ctl_values": [50, 51, 52, 53, 54, 55, 56],
            "atl_values": [48, 49, 50, 51, 52, 53, 54],
            "tsb_values": [2, 2, 2, 2, 2, 2, 2],
            "forecast_start_index": 3,
        },
    )
    assert out["config"]["forecast_start_date"] == dates[3].isoformat()
    assert any(s.get("dash") == "dash" for s in out["config"]["series"])


def test_segment_history_and_eddington() -> None:
    history = [
        {"segment_id": "climb_a", "elapsed_s": 420, "avg_power_w": 280},
        {"segment_id": "climb_a", "elapsed_s": 405, "avg_power_w": 290},
    ]
    seg = build_chart_config("segment_history", {"segment_history": history})
    assert seg["config"]["type"] == "bar_grouped"

    edd = calculate_eddington_number([2.5, 3.0, 4.0, 5.0, 3.5, 4.5, 5.5])
    assert edd["eddington_number"] >= 3
    chart = build_chart_config("eddington_consistency", {"activity_values": [2.5, 3.0, 4.0, 5.0, 3.5, 4.5, 5.5]})
    assert chart["config"]["summary"]["eddington_number"] == edd["eddington_number"]


def test_dashboard_athlete_snapshot_endpoint() -> None:
    body = assert_http_engine_json(
        client.post(
            "/dashboard/athlete-snapshot",
            json={
                "load_state": {"acute_load": 65, "chronic_load": 55, "load_balance": -10},
                "daily_tss": [80, 65, 90, 75, 100, 60, 85],
            },
        )
    )
    assert body["schema_version"] == "dashboard_snapshot.v1"
    assert body["readiness"]["readiness_score"] is not None
    assert body["acwr"]["acwr"] is not None
    assert body["chart_hints"]


def test_meta_chart_config_validates_pydantic_envelope() -> None:
    dates = [date.today().isoformat()]
    response = client.post(
        "/meta/chart-config",
        json={
            "chart_type": "acwr_trend",
            "payload": {"dates": dates, "acwr_values": [1.1]},
        },
    )
    body = assert_http_engine_json(response)
    assert body["category"] == "load"
    assert body["config"]["schema_version"] == "chart_config.v1"
