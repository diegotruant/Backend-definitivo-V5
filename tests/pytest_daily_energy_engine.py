"""Daily energy engine and health sync integration tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
from engines.integrations.health_daily_normalizer import normalize_health_daily
from engines.nutrition.daily_energy_engine import build_daily_energy_analysis
from engines.twin_state.models import build_twin_state
from tests.conftest import assert_http_engine_json

client = TestClient(app)


def test_normalize_google_health_aliases() -> None:
    out = normalize_health_daily(
        {
            "date": "2026-06-17",
            "source": "google_health",
            "totalEnergyBurned": 3050,
            "activeEnergyBurned": 980,
            "basalEnergyBurned": 1680,
        }
    )
    assert out["total_calories_kcal"] == 3050.0
    assert out["active_calories_kcal"] == 980.0
    assert out["source"] == "google_health"


def test_physical_job_high_non_training_load() -> None:
    """Muratore-style day: ~3000 kcal total with heavy non-training active burn."""
    out = build_daily_energy_analysis(
        health_daily={
            "date": "2026-06-17",
            "source": "google_health",
            "total_calories_kcal": 3050,
            "active_calories_kcal": 980,
            "basal_calories_kcal": 1680,
        },
        athlete={"weight_kg": 78, "age": 35, "gender": "MALE", "occupation_load": "physical_job"},
        training_calories_kcal=320,
    )
    assert out["status"] == "success"
    assert out["schema_version"] == "daily_energy.v1"
    assert out["not_a_diet"] is True
    assert out["derived"]["non_training_active_kcal"] == 660.0
    assert out["classifications"]["physical_job_load"] == "moderate"
    assert out["classifications"]["daily_energy_load"] in {"high", "very_high"}
    assert "high_non_training_load" not in out["coach_flags"]  # threshold is 700

    heavy = build_daily_energy_analysis(
        health_daily={
            "total_calories_kcal": 3200,
            "active_calories_kcal": 1150,
            "basal_calories_kcal": 1700,
        },
        athlete={"weight_kg": 78, "occupation_load": "muratore"},
        training_calories_kcal=300,
    )
    assert "high_non_training_load" in heavy["coach_flags"]
    assert heavy["nutrition_energy_context"]["high_non_training_load"] is True


def test_insufficient_data_without_total() -> None:
    out = build_daily_energy_analysis(health_daily={"steps": 8000})
    assert out["status"] == "insufficient_data"


def test_integrations_health_daily_energy_endpoint() -> None:
    response = client.post(
        "/integrations/health/daily-energy",
        json={
            "health_daily": {
                "date": "2026-06-17",
                "source": "oura",
                "total_calories_kcal": 2900,
                "active_calories_kcal": 850,
                "basal_calories_kcal": 1650,
            },
            "athlete": {"weight_kg": 72, "gender": "MALE"},
            "training_calories_kcal": 500,
        },
    )
    body = assert_http_engine_json(response)
    assert body["schema_version"] == "daily_energy.v1"
    assert body["reported"]["total_calories_kcal"] == 2900
    assert body["derived"]["training_calories_kcal"] == 500.0


def test_twin_state_serializes_daily_energy_state() -> None:
    analysis = build_daily_energy_analysis(
        health_daily={"total_calories_kcal": 2800, "active_calories_kcal": 700, "basal_calories_kcal": 1600},
        athlete={"weight_kg": 70},
    )
    twin = build_twin_state({"athlete_id": "a-3", "daily_energy": analysis})
    assert twin["daily_energy_state"]["schema_version"] == "daily_energy_state.v1"
    assert twin["daily_energy_state"]["reported"]["total_calories_kcal"] == 2800
