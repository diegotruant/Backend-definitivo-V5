"""Coach phase-4: periodization, communication draft, environment adjustment."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
from engines.coach.communication_draft_engine import build_communication_draft
from engines.coach.environment_adjustment_engine import build_environment_adjustment
from engines.coach.periodization_engine import review_periodization
from engines.twin_state.models import build_twin_state
from tests.conftest import assert_http_engine_json

client = TestClient(app)


def test_periodization_flags_gym_bike_conflict() -> None:
    out = review_periodization(
        athlete_id="a-1",
        season_phase="build",
        goal={"focus": "threshold"},
        season_plan=[{"week_index": 1, "phase": "build", "workouts": [{"load": 80}]}],
        strength_prescription={"scheduled_days": ["2026-06-20"]},
        upcoming_bike_sessions=[{"date": "2026-06-20", "type": "threshold"}],
    )
    assert out["schema_version"] == "periodization_review.v1"
    review = out["periodization_review"]
    assert review["conflicts"]
    assert review["coherence_status"] in {"review_recommended", "misaligned"}


def test_communication_draft_requires_coach_review() -> None:
    out = build_communication_draft(
        athlete_id="a-2",
        athlete_profile={"first_name": "Marco"},
        decision_safety={"level": "coach_review_recommended", "reasons": ["readiness_drop"]},
        adherence_report={
            "compliance": {"score": 62, "coach_note": "Compliance is low — review target realism."},
        },
        tone="supportive",
    )
    assert out["schema_version"] == "communication_draft.v1"
    draft = out["communication_draft"]
    assert draft["coach_review_required"] is True
    assert draft["not_autonomous"] is True
    assert "Marco" in draft["body"]


def test_environment_adjustment_caps_intensity_in_heat() -> None:
    out = build_environment_adjustment(
        environment_context={"temperature_c": 34, "humidity_pct": 70, "altitude_m": 200},
        metabolic_snapshot={"mlss_power_watts": 280},
        session_context={"duration_min": 120},
    )
    assert out["schema_version"] == "environment_adjustment.v1"
    adj = out["environment_adjustment"]
    assert adj["heat_stress_level"] == "high"
    assert adj["intensity_cap_adjustment_pct"] < 100
    assert adj["hydration_notes"]


def test_coach_periodization_endpoint() -> None:
    response = client.post(
        "/coach/periodization",
        json={
            "athlete_id": "a-3",
            "start_date": "2026-06-01",
            "target_date": "2026-08-01",
            "season_phase": "base",
            "goal": {"focus": "endurance"},
        },
    )
    body = assert_http_engine_json(response)
    assert body["periodization_review"]["weeks_reviewed"] >= 1


def test_coach_communication_draft_endpoint() -> None:
    response = client.post(
        "/coach/communication-draft",
        json={
            "athlete_id": "a-4",
            "athlete": {"first_name": "Luca"},
            "attention": {"priority": "high", "reasons": ["readiness_drop"]},
            "tone": "direct",
        },
    )
    body = assert_http_engine_json(response)
    assert body["communication_draft"]["subject"]
    assert body["communication_draft"]["not_a_diagnosis"] is True


def test_coach_environment_adjustment_endpoint() -> None:
    response = client.post(
        "/coach/environment-adjustment",
        json={
            "athlete_id": "a-5",
            "environment_context": {"temperature_c": 28, "humidity_pct": 55, "altitude_m": 1800},
            "metabolic_snapshot": {"mlss_power_watts": 265},
        },
    )
    body = assert_http_engine_json(response)
    assert body["environment_adjustment"]["altitude_power_factor"] < 1.0


def test_environment_adjustment_insufficient_data() -> None:
    out = build_environment_adjustment()
    assert out["status"] == "insufficient_data"
    assert out["reason"] == "missing_environment_context"


def test_periodization_aligned_phase_for_endurance_goal() -> None:
    out = review_periodization(season_phase="base", goal={"focus": "endurance"})
    assert out["periodization_review"]["phase_alignment"]["status"] == "aligned"


def test_communication_draft_brief_tone_without_signals() -> None:
    out = build_communication_draft(athlete_id="a-7", tone="brief")
    assert out["communication_draft"]["tone"] == "brief"
    assert "check-in" in out["communication_draft"]["body"].lower()


def test_communication_draft_includes_psych_and_motivation_flags() -> None:
    out = build_communication_draft(
        athlete_id="a-8",
        decision_safety={
            "psychological_support_flag": {"human_check_recommended": True},
        },
        checkin={"motivation": 3, "perceived_fatigue": 9},
        tone="direct",
    )
    highlights = out["communication_draft"]["highlights"]
    assert any("fatigue" in h.lower() or "motivation" in h.lower() for h in highlights)
    assert any("supportive" in h.lower() or "diagnosis" in h.lower() for h in highlights)


def test_periodization_misaligned_peak_for_endurance() -> None:
    out = review_periodization(season_phase="peak", goal={"focus": "endurance"})
    assert out["periodization_review"]["phase_alignment"]["status"] == "misaligned"


def test_periodization_high_load_risk_escalates_coherence() -> None:
    weeks = [{"week_index": i + 1, "workouts": [{"load": 50 + i * 40}]} for i in range(4)]
    out = review_periodization(season_plan=weeks, load_state={"chronic_load": 30})
    assert out["periodization_review"]["load_risk"]["level"] in {"moderate", "high"}


def test_environment_cold_wind_and_thermal_branches() -> None:
    out = build_environment_adjustment(
        environment_context={"temperature_c": 5, "wind_speed_kmh": 30},
        thermal_state={"thermal_rise_rate": 0.04},
        metabolic_snapshot={"mlss_power_watts": 300},
    )
    adj = out["environment_adjustment"]
    assert adj["heat_stress_level"] == "cold"
    assert any("wind" in n.lower() for n in adj["pacing_notes"])
    assert adj["intensity_cap_adjustment_pct"] < 100


def test_environment_high_altitude_tier() -> None:
    out = build_environment_adjustment(
        environment_context={"altitude_m": 3600},
        metabolic_snapshot={"mlss_power_watts": 250},
    )
    assert out["environment_adjustment"]["altitude_power_factor"] <= 0.82


def test_communication_draft_invalid_tone_defaults_supportive() -> None:
    out = build_communication_draft(athlete_id="a-10", tone="unknown")
    assert out["communication_draft"]["tone"] == "supportive"


def test_twin_state_accepts_direct_phase4_state_keys() -> None:
    twin = build_twin_state(
        {
            "athlete_id": "a-9",
            "periodization_state": {"schema_version": "periodization_state.v1", "coherence_status": "aligned"},
            "communication_draft_state": {"schema_version": "communication_draft_state.v1"},
            "environment_state": {"schema_version": "environment_state.v1"},
        }
    )
    assert twin["periodization_state"]["coherence_status"] == "aligned"


def test_twin_state_serializes_phase4_states() -> None:
    periodization = review_periodization(season_phase="build", goal={"focus": "vo2"})
    draft = build_communication_draft(athlete_id="a-6")
    environment = build_environment_adjustment(environment_context={"temperature_c": 22})
    twin = build_twin_state(
        {
            "athlete_id": "a-6",
            "periodization_review": periodization,
            "communication_draft": draft,
            "environment_adjustment": environment,
        }
    )
    assert twin["periodization_state"]["schema_version"] == "periodization_state.v1"
    assert twin["communication_draft_state"]["communication_draft"]["coach_review_required"] is True
    assert twin["environment_state"]["environment_adjustment"]["heat_stress_level"]
