"""Coach phase-2: checkin, decision safety, attention."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
from engines.coach.attention_engine import evaluate_athlete_attention, evaluate_roster_attention
from engines.coach.checkin_engine import process_checkin
from engines.coach.decision_safety_engine import evaluate_decision_safety
from engines.twin_state.models import build_twin_state
from tests.conftest import assert_http_engine_json

client = TestClient(app)


def test_checkin_flags_human_review_after_low_motivation_streak() -> None:
    history = [{"motivation": 3} for _ in range(5)]
    out = process_checkin(motivation=3, stress=8, recent_checkins=history)
    assert out["schema_version"] == "athlete_checkin.v1"
    assert out["psychological_support_flag"]["human_check_recommended"] is True
    assert out["psychological_support_flag"]["not_a_diagnosis"] is True


def test_decision_safety_blocks_auto_progress_on_low_compliance() -> None:
    out = evaluate_decision_safety(
        athlete_id="a-1",
        readiness_state={"readiness_score": 62},
        load_state={"tsb": -5},
        last_compliance={"compliance_score": 52, "missed_key_work": True},
    )
    assert out["schema_version"] == "decision_safety.v1"
    assert out["decision_safety"]["intensity_gate"] == "do_not_auto_progress"
    assert "missed_key_work" in out["decision_safety"]["reasons"]


def test_attention_high_priority_when_readiness_and_compliance_poor() -> None:
    out = evaluate_athlete_attention(
        athlete_id="a-2",
        readiness_state={"readiness_score": 42},
        load_state={"tsb": -30, "atl": 105},
        last_compliance={"compliance_score": 55},
        upcoming_key_session=True,
    )
    assert out["athlete_attention"]["priority"] == "high"
    assert out["athlete_attention"]["attention_score"] >= 45


def test_roster_attention_ranks_highest_risk_first() -> None:
    out = evaluate_roster_attention([
        {
            "athlete_id": "stable",
            "readiness_state": {"readiness_score": 80},
            "load_state": {"tsb": 5},
        },
        {
            "athlete_id": "at_risk",
            "readiness_state": {"readiness_score": 38},
            "load_state": {"tsb": -28},
            "last_compliance": {"compliance_score": 50, "missed_key_work": True},
        },
    ])
    assert out["roster_attention"][0]["athlete_id"] == "at_risk"
    assert out["high_priority_count"] >= 1


def test_coach_checkin_endpoint() -> None:
    response = client.post(
        "/coach/checkin",
        json={
            "athlete_id": "a-3",
            "checkin": {"motivation": 3, "stress": 8, "perceived_fatigue": 8},
            "recent_checkins": [{"motivation": 3}] * 4,
        },
    )
    body = assert_http_engine_json(response)
    assert body["schema_version"] == "athlete_checkin.v1"
    assert body["psychological_support_flag"]["status"] == "human_check_recommended"


def test_coach_decision_safety_endpoint() -> None:
    response = client.post(
        "/coach/decision-safety",
        json={
            "athlete_id": "a-4",
            "readiness_state": {"readiness_score": 35},
            "load_state": {"tsb": -30},
            "injury_flags": [],
        },
    )
    body = assert_http_engine_json(response)
    assert body["decision_safety"]["level"] == "coach_review_recommended"


def test_coach_attention_endpoint() -> None:
    response = client.post(
        "/coach/attention",
        json={
            "athlete_id": "a-5",
            "readiness_state": {"readiness_score": 40},
            "load_state": {"tsb": -20},
            "upcoming_key_session": True,
        },
    )
    body = assert_http_engine_json(response)
    assert body["schema_version"] == "coach_attention.v1"
    assert body["athlete_attention"]["priority"] in {"high", "medium", "low"}


def test_twin_state_serializes_checkin_and_safety() -> None:
    checkin = process_checkin(motivation=4, stress=7)
    safety = evaluate_decision_safety(
        athlete_id="a-6",
        checkin={"motivation": 4, "stress": 7},
        readiness_state={"readiness_score": 70},
    )
    twin = build_twin_state(
        {
            "athlete_id": "a-6",
            "checkin": checkin,
            "decision_safety_response": safety,
        }
    )
    assert twin["checkin_state"]["schema_version"] == "athlete_checkin.v1"
    assert twin["decision_safety_state"]["schema_version"] == "decision_safety_state.v1"
