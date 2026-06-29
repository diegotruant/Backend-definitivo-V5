"""Season planner profile linkage, readiness EWMA warm-up, progression contract."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from api_app import app
from engines.planning.season_planner import create_season_plan
from engines.readiness.readiness_engine import compute_readiness_today, update_load_state
from engines.workouts.progression_levels import compute_progression_levels

client = TestClient(app)


def test_season_plan_anaerobic_profile_distributes_more_quality_in_peak() -> None:
    generic = create_season_plan(
        start_date="2026-06-01",
        target_date="2026-08-15",
        weekly_hours=10,
        goal={"focus": "balanced"},
    )
    anaerobic = create_season_plan(
        start_date="2026-06-01",
        target_date="2026-08-15",
        weekly_hours=10,
        goal={"focus": "anaerobic"},
        athlete_profile={
            "cp_w": 200,
            "estimated_vlamax_mmol_L_s": 0.62,
            "mmp": {"15": 961, "300": 280, "1200": 200},
            "dominant_ability": "anaerobic",
        },
    )
    assert anaerobic["planning_context"]["intensity_bias"] == "anaerobic"
    peak_weeks = [w for w in anaerobic["weeks"] if w["phase"] == "peak" and not w.get("recovery_week")]
    assert peak_weeks
    peak_workouts = peak_weeks[0]["workouts"]
    assert len(peak_workouts) >= 4
    quality_types = {w["type"] for w in peak_workouts}
    assert "anaerobic" in quality_types or "vo2" in quality_types
    assert generic["weeks"][0]["workouts"][0]["type"] != peak_workouts[0]["type"] or len(peak_workouts) != len(
        generic["weeks"][0]["workouts"]
    )


def test_season_plan_endpoint_accepts_athlete_profile() -> None:
    response = client.post(
        "/planning/create-season-plan",
        json={
            "start_date": "2026-06-01",
            "target_date": "2026-07-15",
            "weekly_hours": 8,
            "athlete_profile": {"cp_w": 250, "estimated_vlamax_mmol_L_s": 0.5},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["planning_context"]["cp_w"] == 250


def test_load_state_tracks_confidence_valid_from_date() -> None:
    state = update_load_state(None, 80)
    assert state["ewma_tracking_started_at"]
    assert state["confidence_valid_from_date"]
    started = date.fromisoformat(state["ewma_tracking_started_at"])
    valid = date.fromisoformat(state["confidence_valid_from_date"])
    assert (valid - started).days == 42
    assert state["ewma_trust_level"] == "cold"

    for load in (70, 65, 60, 55):
        state = update_load_state(state, load)
    assert state["load_sessions_count"] == 5


def test_readiness_exposes_confidence_valid_from_date_during_cold_start() -> None:
    state = update_load_state(None, 75)
    out = compute_readiness_today(load_state=state)
    assert out["confidence_valid_from_date"] == state["confidence_valid_from_date"]
    assert out["ewma_trust_level"] == "cold"
    assert "ewma_cold_start" in out["warnings"]
    assert out["model_metadata"]["confidence_score"] <= 0.5


def test_readiness_stable_after_warmup_window() -> None:
    started = (date.today() - timedelta(days=50)).isoformat()
    state = {
        "acute_load": 55,
        "chronic_load": 48,
        "load_balance": -7,
        "ewma_tracking_started_at": started,
        "load_sessions_count": 12,
    }
    out = compute_readiness_today(load_state=state)
    assert out["ewma_warmup_complete"] is True
    assert out["ewma_trust_level"] == "stable"
    assert out["confidence_valid_from_date"] <= date.today().isoformat()


def test_progression_levels_without_zone_compliance_unchanged() -> None:
    profile = {"weight_kg": 70, "mmp": {"60": 500, "300": 350, "1200": 280}}
    base = compute_progression_levels(profile, workout_history=[])
    with_history = compute_progression_levels(
        profile,
        workout_history=[{"date": "2026-01-01"}, {"classification": "completed"}],
    )
    assert base["levels"] == with_history["levels"]


def test_progression_levels_adjusts_when_zone_and_compliance_present() -> None:
    profile = {"weight_kg": 70, "mmp": {"60": 500, "300": 350, "1200": 280}}
    history = [
        {"target_zone": "vo2", "compliance_score": 95},
        {"target_zone": "vo2", "compliance_score": 92},
        {"target_zone": "threshold", "compliance_score": 40},
    ]
    out = compute_progression_levels(profile, workout_history=history)
    assert out["levels"]["vo2"] >= out["ability_profile"]["levels"]["vo2"]
    assert out["levels"]["threshold"] <= out["ability_profile"]["levels"]["threshold"]
