"""Product engines edge cases and phenotype-aware recommendation verification."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
from engines.history.athlete_history import build_history_summary
from engines.workouts.recommendation_engine import recommend_workout

client = TestClient(app)

SPRINTER_PROFILE = {
    "cp_w": 200,
    "weight_kg": 72,
    "mmp": {"15": 961, "60": 520, "300": 280, "1200": 200, "3600": 175},
}


def test_history_summary_empty_activities_engine_level() -> None:
    """Engine handles empty list; HTTP API requires min_length=1 on activities."""
    out = build_history_summary([], weight_kg=70)
    assert out["status"] == "success"
    assert out["activity_count"] == 0
    assert out["personal_records"]["records"] == []

    response = client.post("/history/summary", json={"weight_kg": 70, "activities": []})
    assert response.status_code == 422


def test_readiness_score_zero_recommends_recovery() -> None:
    response = client.post(
        "/readiness/today",
        json={"load_state": {"acute_load": 120, "chronic_load": 40}, "subjective": {"score": 0.1}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["readiness_score"] == 0 or body["readiness_band"] == "low"
    rec = recommend_workout(SPRINTER_PROFILE, readiness={"readiness_score": 0})
    assert rec["recommendation"]["focus"] == "recovery"


def test_workout_export_tolerates_steps_without_duration_s() -> None:
    response = client.post(
        "/workouts/export",
        json={
            "format": "erg",
            "workout": {
                "name": "Edge case",
                "steps": [{"target_w": 220}, {"target_w": 180, "duration_s": 120}],
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["content"].startswith("[COURSE HEADER]")


def test_recommendation_phenotype_aware_for_sprinter_profile() -> None:
    out = recommend_workout(
        SPRINTER_PROFILE,
        readiness={"readiness_score": 82},
        goal={"focus": "balanced"},
    )
    assert out["status"] == "success"
    rec = out["recommendation"]
    assert rec["ability_context"]["dominant_ability"] in {"sprint", "anaerobic", "vo2"}
    assert rec["ability_context"]["selection_strategy"] == "phenotype_aware_limiter"
    assert rec["focus"] in {"anaerobic", "vo2", "threshold"}
    assert any(note.startswith("phenotype_") for note in rec["rationale"])


def test_recommendation_goal_overrides_phenotype_pool() -> None:
    out = recommend_workout(
        SPRINTER_PROFILE,
        readiness={"readiness_score": 80},
        goal={"focus": "endurance"},
    )
    assert out["recommendation"]["focus"] == "endurance"
    assert out["recommendation"]["ability_context"]["selection_strategy"] == "goal_directed"


def test_season_plan_uses_ability_profile_from_mmp() -> None:
    response = client.post(
        "/planning/create-season-plan",
        json={
            "start_date": "2026-06-01",
            "target_date": "2026-08-01",
            "weekly_hours": 9,
            "athlete_profile": SPRINTER_PROFILE,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["planning_context"]["intensity_bias"] == "anaerobic"
    assert body["planning_context"]["phenotype"] in {"sprint", "anaerobic", "vo2"}


def test_progression_levels_endpoint_requires_history_fields_for_feedback() -> None:
    profile = {"weight_kg": 70, "mmp": {"60": 500, "300": 350, "1200": 280}}
    without = client.post("/workouts/progression-levels", json={"athlete_profile": profile, "workout_history": []})
    with_feedback = client.post(
        "/workouts/progression-levels",
        json={
            "athlete_profile": profile,
            "workout_history": [{"target_zone": "vo2", "compliance_score": 90}],
        },
    )
    assert without.status_code == 200
    assert with_feedback.status_code == 200
    assert without.json()["levels"] == with_feedback.json()["levels"] or with_feedback.json()["levels"]["vo2"] >= without.json()["levels"]["vo2"]
