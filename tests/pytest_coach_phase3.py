"""Coach phase-3: adherence, testing plan, race execution."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
from engines.coach.adherence_engine import evaluate_adherence
from engines.coach.race_execution_engine import build_race_execution_plan
from engines.coach.testing_scheduler_engine import build_testing_plan
from engines.twin_state.models import build_twin_state
from tests.conftest import assert_http_engine_json

client = TestClient(app)

SNAPSHOT = {
    "status": "success",
    "confidence_score": 0.42,
    "mlss_power_watts": 282.0,
    "fatmax_power_watts": 185.0,
    "estimated_vlamax_mmol_L_s": None,
    "expressiveness": {"reliability": {"mlss": False, "vlamax": False, "fatmax": False}},
}


def test_adherence_explains_low_compliance_with_reasons() -> None:
    out = evaluate_adherence(
        athlete_id="a-1",
        performed_compliance={
            "compliance_score": 58,
            "classification": "partially_completed",
            "summary": {"planned_key_intervals": 4, "completed_key_intervals": 2},
        },
        readiness_state={"readiness_score": 48},
        checkin={"perceived_fatigue": 8},
    )
    assert out["schema_version"] == "adherence_report.v1"
    assert out["compliance"]["missed_key_work"] is True
    assert "fatigue" in out["compliance"]["reason_candidates"]


def test_testing_plan_recommends_lactate_when_calibration_weak() -> None:
    out = build_testing_plan(metabolic_snapshot=SNAPSHOT, season_phase="build")
    assert out["schema_version"] == "testing_plan.v1"
    assert out["testing_recommendation"]["priority"] == "high"
    assert out["testing_recommendation"]["test"] == "lactate_step_test"


def test_race_execution_plan_includes_pacing_and_failure_modes() -> None:
    out = build_race_execution_plan(
        target_event="granfondo",
        metabolic_snapshot={
            "mlss_power_watts": 280,
            "fatmax_power_watts": 180,
            "w_prime_j": 12000,
        },
        duration_h=5.0,
    )
    assert out["schema_version"] == "race_execution_plan.v1"
    plan = out["race_execution_plan"]
    assert "pacing_strategy" in plan
    assert plan["fueling_targets"]["carbohydrate_availability"] == "high"
    assert "durability drop after hour 3" in plan["failure_modes"]


def test_coach_adherence_endpoint() -> None:
    response = client.post(
        "/coach/adherence",
        json={
            "athlete_id": "a-2",
            "performed_compliance": {"compliance_score": 72, "classification": "mostly_completed"},
        },
    )
    body = assert_http_engine_json(response)
    assert body["compliance"]["score"] == 72


def test_coach_testing_plan_endpoint() -> None:
    response = client.post(
        "/coach/testing-plan",
        json={"athlete_id": "a-3", "metabolic_snapshot": SNAPSHOT, "season_phase": "base"},
    )
    body = assert_http_engine_json(response)
    assert body["testing_recommendations"]


def test_coach_race_execution_endpoint() -> None:
    response = client.post(
        "/coach/race-execution",
        json={
            "athlete_id": "a-4",
            "target_event": "granfondo",
            "metabolic_snapshot": {"mlss_power_watts": 275, "fatmax_power_watts": 170, "w_prime_j": 14000},
        },
    )
    body = assert_http_engine_json(response)
    assert body["race_execution_plan"]["target_event"] == "granfondo"


def test_twin_state_serializes_phase3_states() -> None:
    adherence = evaluate_adherence(
        performed_compliance={"compliance_score": 80, "classification": "mostly_completed"},
    )
    testing = build_testing_plan(metabolic_snapshot=SNAPSHOT)
    race = build_race_execution_plan(metabolic_snapshot={"mlss_power_watts": 270})
    twin = build_twin_state(
        {
            "athlete_id": "a-5",
            "adherence_report": adherence,
            "testing_plan": testing,
            "race_execution_plan": race,
        }
    )
    assert twin["adherence_state"]["schema_version"] == "adherence_state.v1"
    assert twin["testing_plan_state"]["testing_recommendation"]["test"]
    assert twin["race_execution_state"]["race_execution_plan"]["pacing_strategy"]
