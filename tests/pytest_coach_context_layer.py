"""Coach PNEI, endocrine, constraints and training safety layer."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
from engines.coach.constraints_engine import evaluate_constraints
from engines.coach.decision_safety_engine import evaluate_decision_safety
from engines.coach.injury_illness_engine import evaluate_training_safety
from engines.coach.pnei_context_engine import build_pnei_context
from engines.endocrine.endocrine_context_engine import build_endocrine_context
from engines.twin_state.models import build_twin_state
from tests.conftest import assert_http_engine_json

client = TestClient(app)


def test_pnei_context_flags_systemic_strain() -> None:
    out = build_pnei_context(
        athlete_id="p-1",
        load_state={"tsb": -28, "acute_load_spike": True},
        readiness_state={"hrv_baseline": 62, "hrv_7d": 48, "resting_hr_baseline": 48, "resting_hr_7d": 56},
        checkin={"stress": 9, "motivation": 3, "perceived_fatigue": 8},
        sleep={"sleep_hours_7d": 5.8},
        nutrition_energy={"low_energy_availability_risk": "moderate"},
    )
    assert out["schema_version"] == "pnei_context.v1"
    ctx = out["pnei_context"]
    assert ctx["status"] in {"caution", "human_review", "professional_review"}
    assert ctx["training_decision"]["permission"] in {"modify", "hold_intensity", "stop_and_review"}
    assert "hrv_below_baseline" in ctx["reasons"]


def test_endocrine_context_flags_energy_risk_without_diagnosis() -> None:
    out = build_endocrine_context(
        athlete_id="p-2",
        nutrition_energy={"red_flags": ["reds_risk_flag"], "weight_trend": "down_fast"},
        checkin={"perceived_fatigue": 9, "motivation": 3},
        performance={"power_drop": True},
    )
    assert out["schema_version"] == "endocrine_context.v1"
    assert out["measurement_tier"] == "RISK_MODEL"
    endo = out["endocrine_context"]
    assert endo["status"] == "professional_review"
    assert endo["requires_professional_interpretation"] is True
    assert "Hormonal interpretation" in out["limitations"][1]


def test_endocrine_cycle_context_optional_not_prescriptive() -> None:
    out = build_endocrine_context(
        cycle_context={"menstrual_irregularity": True},
    )
    reproductive = out["endocrine_context"]["subsystems"]["reproductive_axis"]
    assert reproductive["professional_review_recommended"] is True
    assert reproductive["not_a_diagnosis"] is True


def test_constraints_adapt_travel_week() -> None:
    out = evaluate_constraints(
        constraints={"travel_week": True, "available_days": ["tue", "sat"], "max_session_duration_min": 50},
        season_phase="build",
        planned_weekly_hours=10,
    )
    assert out["schema_version"] == "constraints_adaptation.v1"
    assert out["adaptation"]["volume_factor"] < 1.0
    assert out["adaptation"]["intensity_cap"] == "hold"


def test_training_safety_stops_on_illness() -> None:
    out = evaluate_training_safety(
        illness_symptoms=True,
        readiness_state={"readiness_score": 42},
    )
    assert out["schema_version"] == "training_safety.v1"
    assert out["training_safety"]["status"] == "stop"
    assert "high_intensity" in out["training_safety"]["avoid_today"]


def test_decision_safety_escalates_with_pnei_context() -> None:
    pnei = build_pnei_context(
        load_state={"tsb": -30},
        readiness_state={"readiness_score": 40},
        checkin={"stress": 9, "motivation": 2, "perceived_fatigue": 9},
        illness_symptoms=True,
    )
    out = evaluate_decision_safety(pnei_context=pnei)
    assert out["decision_safety"]["level"] == "professional_review_recommended"
    assert out["context_layers"]["pnei_considered"] is True


def test_coach_pnei_context_endpoint() -> None:
    response = client.post(
        "/coach/pnei-context",
        json={
            "athlete_id": "p-3",
            "load_state": {"tsb": -22},
            "checkin": {"stress": 8, "motivation": 4},
        },
    )
    body = assert_http_engine_json(response)
    assert body["pnei_context"]["subsystems"]["psychological"]["strain"] in {"low", "moderate", "high"}


def test_coach_endocrine_context_endpoint() -> None:
    response = client.post(
        "/coach/endocrine-context",
        json={"athlete_id": "p-4", "weight_trend": "down_fast", "fuel_deficit_g": 90},
    )
    body = assert_http_engine_json(response)
    assert body["endocrine_context"]["training_decision"]["permission"] in {
        "normal",
        "modify",
        "professional_review",
    }


def test_coach_constraints_endpoint() -> None:
    response = client.post(
        "/coach/constraints",
        json={"athlete_id": "p-5", "constraints": {"sleep_restricted": True}},
    )
    body = assert_http_engine_json(response)
    assert body["adaptation"]["coach_notes"]


def test_coach_training_safety_endpoint() -> None:
    response = client.post(
        "/coach/training-safety",
        json={"athlete_id": "p-6", "injury_flags": ["acute_pain"]},
    )
    body = assert_http_engine_json(response)
    assert body["training_safety"]["red_flags"]


def test_pnei_context_ok_when_signals_mild() -> None:
    out = build_pnei_context(
        load_state={"tsb": 5},
        readiness_state={"hrv_baseline": 60, "hrv_7d": 58, "readiness_score": 75},
        checkin={"stress": 4, "motivation": 7, "perceived_fatigue": 4},
    )
    assert out["pnei_context"]["status"] == "ok"
    assert out["pnei_context"]["training_decision"]["permission"] == "normal"


def test_endocrine_biomarkers_require_professional_interpretation() -> None:
    out = build_endocrine_context(
        biomarkers={
            "free_testosterone": {"status": "low"},
            "ferritin": {"classification": "below_range"},
        },
    )
    bio = out["endocrine_context"]["subsystems"]["biomarker_context"]
    assert bio["available"] is True
    assert bio["requires_professional_interpretation"] is True
    assert out["endocrine_context"]["status"] == "professional_review"


def test_decision_safety_reads_context_from_twin_state() -> None:
    pnei = build_pnei_context(checkin={"stress": 9, "motivation": 2, "perceived_fatigue": 9})
    twin = build_twin_state({"athlete_id": "p-8", "pnei_context": pnei})
    out = evaluate_decision_safety(twin_state=twin)
    assert out["decision_safety"]["level"] == "coach_review_recommended"
    assert out["context_layers"]["pnei_considered"] is True


def test_training_safety_caution_on_multiple_flags() -> None:
    out = evaluate_training_safety(
        checkin={"perceived_fatigue": 8, "joint_pain": 8},
        load_state={"tsb": -22},
        readiness_state={"readiness_score": 48},
    )
    assert out["training_safety"]["status"] == "caution"


def test_twin_state_serializes_context_layers() -> None:
    pnei = build_pnei_context(checkin={"stress": 7})
    endocrine = build_endocrine_context(weight_trend="down")
    safety = evaluate_training_safety(checkin={"joint_pain": 8})
    constraints = evaluate_constraints(constraints={"travel_week": True})
    twin = build_twin_state(
        {
            "athlete_id": "p-7",
            "pnei_context": pnei,
            "endocrine_context": endocrine,
            "training_safety": safety,
            "constraints_adaptation": constraints,
        }
    )
    assert twin["pnei_state"]["schema_version"] == "pnei_state.v1"
    assert twin["endocrine_context_state"]["endocrine_context"]["status"]
    assert twin["training_safety_state"]["training_safety"]["status"]
    assert twin["constraints_state"]["adaptation"]["volume_factor"] < 1.0
