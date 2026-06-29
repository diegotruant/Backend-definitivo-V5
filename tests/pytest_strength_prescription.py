"""Strength prescription engine tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
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


def _base_kwargs() -> dict:
    return {
        "athlete": {"weight_kg": 68, "gender": "MALE", "training_years": 8},
        "metabolic_snapshot": SNAPSHOT,
        "load_state": {"tsb": 2, "atl": 65},
        "readiness_state": {"readiness_score": 72},
        "goal": "climbing",
        "season_phase": "base",
        "equipment": ["barbell", "dumbbells"],
        "days_available": 2,
        "mmp": {"5": 900, "60": 420, "3600": 255},
    }


def test_prescribe_strength_for_climber_prioritizes_neural_strength() -> None:
    out = prescribe_strength(**_base_kwargs())
    assert out["schema_version"] == "strength_prescription.v1"
    assert out["measurement_tier"] == "PRESCRIPTION_MODEL"
    assert out["primary_need"] in {"max_strength", "low_cadence_torque", "structural_stability"}
    assert out["weekly_frequency"] >= 1
    assert out["sessions"][0]["blocks"]
    assert out["bike_conflict_rules"]["minimum_gap_h_before_key_session"] >= 24
    assert out["strength_target"]["hypertrophy_risk"] == "low"


def test_prescribe_strength_blocks_on_injury_flag() -> None:
    out = prescribe_strength(**{**_base_kwargs(), "injury_flags": ["acute_pain"]})
    assert out["status"] == "requires_professional_review"
    assert out["safe_output"] == "mobility_and_low_load_technical_work_only"
    assert out["sessions"][0]["focus"] == "mobility_and_activation"


def test_prescribe_strength_reduces_load_when_readiness_low() -> None:
    kwargs = _base_kwargs()
    kwargs["readiness_state"] = {"readiness_score": 38}
    kwargs["load_state"] = {"tsb": -28, "atl": 110}
    out = prescribe_strength(**kwargs)
    assert out["decision_safety"]["level"] == "coach_review_recommended"
    assert out["sessions"][0]["focus"] in {"neural_maintenance", "mobility_and_activation"}


def test_coach_strength_prescription_endpoint() -> None:
    response = client.post(
        "/coach/strength/prescription",
        json={
            "athlete": {"weight_kg": 68, "gender": "MALE", "training_years": 8},
            "metabolic_snapshot": SNAPSHOT,
            "load_state": {"tsb": 0},
            "readiness_state": {"readiness_score": 70},
            "goal": "granfondo",
            "season_phase": "build",
            "upcoming_bike_sessions": [{"type": "vo2max", "scheduled_at": "2026-07-02"}],
        },
    )
    body = assert_http_engine_json(response)
    assert body["schema_version"] == "strength_prescription.v1"
    assert body["interference_risk"] in {"moderate", "high"}
    assert "bike_conflict_rules" in body


def test_twin_state_serializes_strength_prescription() -> None:
    prescription = prescribe_strength(**_base_kwargs())
    twin = build_twin_state(
        {
            "athlete_id": "a-1",
            "metabolic_snapshot": SNAPSHOT,
            "strength_prescription": prescription,
        }
    )
    assert twin["strength_state"]["schema_version"] == "strength_state.v1"
    assert twin["strength_state"]["primary_need"] == prescription["primary_need"]
