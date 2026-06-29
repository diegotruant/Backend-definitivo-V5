"""Performance fueling targets tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
from engines.nutrition.performance_fueling_engine import build_performance_fueling_targets
from engines.strength.strength_prescription_engine import prescribe_strength
from engines.twin_state.models import build_twin_state
from tests.conftest import assert_http_engine_json

client = TestClient(app)

SNAPSHOT = {
    "status": "success",
    "fatmax_power_watts": 185.0,
    "mlss_power_watts": 282.0,
    "map_aerobic_watts": 392.0,
    "estimated_vo2max": 60.0,
    "estimated_vlamax_mmol_L_s": 0.42,
}


def test_performance_fueling_includes_session_fat_g_with_power_stream() -> None:
    """INSCYD parity: expose absolute CHO and FAT grams for the session."""
    power = [220.0] * 180 + [300.0] * 60
    out = build_performance_fueling_targets(
        athlete={"weight_kg": 72, "gender": "MALE", "training_years": 10},
        metabolic_snapshot=SNAPSHOT,
        power_stream=power,
    )
    demands = out["estimated_demands"]
    assert demands["session_carbohydrate_g"] is not None
    assert demands["session_fat_g"] is not None
    assert demands["session_fat_g"] >= 0
    assert demands["session_carbohydrate_g"] > demands["session_fat_g"]


def test_performance_fueling_targets_are_not_a_diet() -> None:
    out = build_performance_fueling_targets(
        athlete={"weight_kg": 72, "gender": "MALE", "training_years": 10},
        metabolic_snapshot=SNAPSHOT,
        load_state={"tsb": -5},
        readiness_state={"readiness_score": 60},
        session_context="gym_strength + bike_endurance",
        strength_prescription=prescribe_strength(
            athlete={"weight_kg": 72},
            metabolic_snapshot=SNAPSHOT,
            goal="general_performance",
        ),
    )
    assert out["schema_version"] == "performance_fueling_targets.v1"
    assert out["not_a_diet"] is True
    assert "targets" in out
    assert out["targets"]["protein_recovery_priority"] == "high"
    notes = " ".join(out["coach_notes"]).lower()
    assert "not a meal plan" in notes
    assert "breakfast" not in notes


def test_performance_fueling_flags_reds_risk() -> None:
    out = build_performance_fueling_targets(
        athlete={"weight_kg": 60},
        metabolic_snapshot=SNAPSHOT,
        injury_flags=["reds_risk"],
    )
    assert "reds_risk_flag" in out["red_flags"]


def test_coach_nutrition_performance_targets_endpoint() -> None:
    response = client.post(
        "/coach/nutrition/performance-targets",
        json={
            "athlete": {"weight_kg": 72, "gender": "MALE", "training_years": 10},
            "metabolic_snapshot": SNAPSHOT,
            "session_context": "bike_endurance",
            "power_series": [220.0] * 180 + [300.0] * 60,
        },
    )
    body = assert_http_engine_json(response)
    assert body["schema_version"] == "performance_fueling_targets.v1"
    assert body["not_a_diet"] is True
    assert body["targets"]["carbohydrate_availability"] in {"moderate", "high"}
    assert body["estimated_demands"]["session_fat_g"] is not None


def test_twin_state_serializes_nutrition_performance_state() -> None:
    targets = build_performance_fueling_targets(
        athlete={"weight_kg": 72},
        metabolic_snapshot=SNAPSHOT,
    )
    twin = build_twin_state(
        {
            "athlete_id": "a-2",
            "metabolic_snapshot": SNAPSHOT,
            "performance_fueling_targets": targets,
        }
    )
    assert twin["nutrition_performance_state"]["schema_version"] == "nutrition_performance_state.v1"
    assert twin["nutrition_performance_state"]["not_a_diet"] is True
