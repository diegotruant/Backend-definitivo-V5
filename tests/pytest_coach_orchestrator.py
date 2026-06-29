"""Coach orchestrator, equipment comfort, female athlete context — verification suite."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
from engines.coach.coach_orchestrator import build_daily_brief, build_session_decision
from engines.coach.equipment_comfort_engine import evaluate_equipment_comfort
from engines.coach.female_athlete_context_engine import build_female_athlete_context
from engines.coach.pnei_context_engine import build_pnei_context
from engines.endocrine.endocrine_context_engine import build_endocrine_context
from engines.twin_state.models import build_twin_state
from tests.conftest import assert_http_engine_json

client = TestClient(app)

SNAPSHOT = {
    "mlss_power_watts": 275,
    "fatmax_power_watts": 175,
    "confidence_score": 0.35,
    "expressiveness": {"reliability": {"mlss": False}},
}


def test_equipment_comfort_links_back_pain_and_power_drop() -> None:
    out = evaluate_equipment_comfort(
        athlete_id="o-1",
        comfort_notes=["lower back pain on long rides", "saddle discomfort"],
        session_history=[{"duration_min": 120, "power_decay_pct": 12}],
        position_change_log=[{"date": "2026-06-01", "change": "saddle_height"}],
    )
    assert out["schema_version"] == "equipment_comfort_review.v1"
    review = out["equipment_comfort_review"]
    assert "back" in review["comfort_flags"]
    assert review["comfort_performance_links"]
    assert review["status"] in {"review_recommended", "high_priority_review"}


def test_equipment_comfort_ok_without_flags() -> None:
    out = evaluate_equipment_comfort(athlete_id="o-2")
    assert out["equipment_comfort_review"]["status"] == "ok"


def test_female_athlete_context_not_reported() -> None:
    out = build_female_athlete_context(athlete_id="o-3")
    ctx = out["female_athlete_context"]
    assert ctx["status"] == "not_reported"
    assert ctx["auto_prescription_from_cycle"] is False


def test_female_athlete_context_irregularity_flags_review() -> None:
    out = build_female_athlete_context(
        athlete_id="o-4",
        context={"menstrual_irregularity": True, "energy": 3, "symptoms": ["fatigue"]},
    )
    ctx = out["female_athlete_context"]
    assert ctx["status"] == "optional_context_available"
    assert ctx["professional_review_recommended"] is True
    assert "not automatic cycle" in ctx["coach_note"]


def test_daily_brief_aggregates_attention_and_safety() -> None:
    out = build_daily_brief(
        athlete_id="o-5",
        load_state={"tsb": -28},
        readiness_state={"readiness_score": 42},
        checkin={"stress": 9, "motivation": 3, "perceived_fatigue": 8},
        last_compliance={"compliance_score": 55, "missed_key_work": True},
        upcoming_key_session=True,
        metabolic_snapshot=SNAPSHOT,
        include_communication_draft=True,
    )
    assert out["schema_version"] == "coach_daily_brief.v1"
    brief = out["coach_daily_brief"]
    assert brief["attention_priority"] in {"high", "medium", "low"}
    assert brief["priority_actions"]
    assert brief["modules"]["decision_safety"]
    assert brief["modules"]["pnei_context"]
    assert brief["modules"]["communication_draft"]
    assert brief["coach_review_required"] is True
    assert brief["not_autonomous"] is True


def test_daily_brief_routine_when_signals_mild() -> None:
    out = build_daily_brief(
        athlete_id="o-6",
        load_state={"tsb": 5},
        readiness_state={"readiness_score": 78, "hrv_baseline": 60, "hrv_7d": 58},
        checkin={"stress": 4, "motivation": 7},
    )
    brief = out["coach_daily_brief"]
    assert brief["intensity_gate"] == "ok_to_auto_suggest"


def test_session_decision_downgrades_vo2_under_strain() -> None:
    out = build_session_decision(
        athlete_id="o-7",
        planned_session={"type": "vo2", "name": "5x5min VO2max", "duration_min": 75},
        twin_state={
            "metabolic_snapshot": SNAPSHOT,
            "load_state": {"tsb": -30},
        },
        checkin={"stress": 9, "motivation": 2, "perceived_fatigue": 9},
    )
    assert out["schema_version"] == "coach_session_decision.v1"
    decision = out["session_decision"]
    assert decision["final_recommendation"] in {"downgrade", "hold", "modify"}
    assert decision["replacement"] is not None
    assert decision["coach_review_required"] is True


def test_session_decision_proceeds_when_context_ok() -> None:
    out = build_session_decision(
        athlete_id="o-8",
        planned_session={"type": "endurance", "duration_min": 90},
        twin_state={"metabolic_snapshot": SNAPSHOT},
        load_state={"tsb": 8},
        readiness_state={"readiness_score": 80},
        checkin={"stress": 4, "motivation": 8},
    )
    assert out["session_decision"]["final_recommendation"] == "proceed"


def test_session_decision_heat_modifies_high_intensity() -> None:
    out = build_session_decision(
        athlete_id="o-9",
        planned_session={"type": "threshold", "duration_min": 60},
        twin_state={"metabolic_snapshot": SNAPSHOT},
        load_state={"tsb": 5},
        readiness_state={"readiness_score": 75},
        environment_context={"temperature_c": 34},
    )
    assert out["session_decision"]["final_recommendation"] in {"modify", "downgrade", "proceed"}


def test_coach_daily_brief_endpoint() -> None:
    response = client.post(
        "/coach/daily-brief",
        json={
            "athlete_id": "o-10",
            "load_state": {"tsb": -15},
            "checkin": {"perceived_fatigue": 7},
        },
    )
    body = assert_http_engine_json(response)
    assert body["coach_daily_brief"]["modules"]


def test_coach_session_decision_endpoint() -> None:
    response = client.post(
        "/coach/session-decision",
        json={
            "athlete_id": "o-11",
            "planned_session": {"type": "vo2", "duration_min": 60},
            "twin_state": {"metabolic_snapshot": SNAPSHOT},
        },
    )
    body = assert_http_engine_json(response)
    assert body["session_decision"]["planned_session"]["type"] == "vo2"


def test_coach_equipment_comfort_endpoint() -> None:
    response = client.post(
        "/coach/equipment-comfort",
        json={"athlete_id": "o-12", "comfort_notes": ["numbness in hands"]},
    )
    body = assert_http_engine_json(response)
    assert "hands" in body["equipment_comfort_review"]["comfort_flags"]


def test_coach_female_athlete_context_endpoint() -> None:
    response = client.post(
        "/coach/female-athlete-context",
        json={"athlete_id": "o-13", "context": {"cycle_phase": "follicular", "energy": 6}},
    )
    body = assert_http_engine_json(response)
    assert body["female_athlete_context"]["auto_prescription_from_cycle"] is False


def test_twin_state_serializes_orchestrator_outputs() -> None:
    brief = build_daily_brief(athlete_id="o-14", load_state={"tsb": -10})
    decision = build_session_decision(
        athlete_id="o-14",
        planned_session={"type": "endurance"},
    )
    equipment = evaluate_equipment_comfort(comfort_notes=["knee pain"])
    female = build_female_athlete_context(context={"energy": 5})
    twin = build_twin_state(
        {
            "athlete_id": "o-14",
            "coach_daily_brief": brief,
            "session_decision": decision,
            "equipment_comfort_review": equipment,
            "female_athlete_context": female,
            "pnei_context": build_pnei_context(checkin={"stress": 6}),
            "endocrine_context": build_endocrine_context(),
        }
    )
    assert twin["daily_brief_state"]["schema_version"] == "daily_brief_state.v1"
    assert twin["session_decision_state"]["session_decision"]["final_recommendation"]
    assert twin["equipment_state"]["equipment_comfort_review"]["comfort_flags"]
    assert twin["female_athlete_context_state"]["female_athlete_context"]["status"]
    assert twin["pnei_state"]["pnei_context"]
    assert twin["endocrine_context_state"]["endocrine_context"]


def test_equipment_high_priority_many_flags() -> None:
    out = evaluate_equipment_comfort(
        comfort_notes=["saddle pain", "back pain", "knee pain", "hand numbness"],
    )
    assert out["equipment_comfort_review"]["status"] == "high_priority_review"


def test_female_athlete_context_from_checkin_only() -> None:
    out = build_female_athlete_context(
        checkin={"energy": 3, "sleep_quality": 3, "symptoms": ["bloating"]},
    )
    assert out["female_athlete_context"]["status"] == "optional_context_available"


def test_all_coach_endpoints_respond_200() -> None:
    """Smoke matrix for coach API surface."""
    payloads = [
        ("/coach/daily-brief", {"athlete_id": "smoke-1"}),
        ("/coach/session-decision", {"athlete_id": "smoke-2", "planned_session": {"type": "endurance"}}),
        ("/coach/equipment-comfort", {"athlete_id": "smoke-3"}),
        ("/coach/female-athlete-context", {"athlete_id": "smoke-4"}),
        ("/coach/pnei-context", {"athlete_id": "smoke-5", "checkin": {"stress": 5}}),
        ("/coach/endocrine-context", {"athlete_id": "smoke-6"}),
        ("/coach/constraints", {"athlete_id": "smoke-7", "constraints": {"travel_week": True}}),
        ("/coach/training-safety", {"athlete_id": "smoke-8"}),
        ("/coach/attention", {"athlete_id": "smoke-9"}),
        ("/coach/decision-safety", {"athlete_id": "smoke-10"}),
    ]
    for path, payload in payloads:
        response = client.post(path, json=payload)
        assert response.status_code == 200, f"{path} returned {response.status_code}"
