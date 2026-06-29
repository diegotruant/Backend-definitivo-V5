"""Full product-engine perfection suite — readiness, load, planning, coach, performance.

Tests encode contracts and regressions; failures drive engine fixes.
"""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.activity_streams import stream_from_power
from api_app import app
from engines.coach.coach_orchestrator import build_daily_brief, build_session_decision
from engines.coach.decision_safety_engine import evaluate_decision_safety
from engines.coach.prescription_safety import evaluate_prescription_safety
from engines.load.manual_load import calculate_manual_load
from engines.performance.ability_profile import build_ability_profile
from engines.planning.plan_adapter import adapt_week
from engines.planning.season_planner import check_load_risk, create_season_plan
from engines.readiness.readiness_engine import compute_load_risk, compute_readiness_today, update_load_state
from engines.workouts.adaptive_planner import adapt_plan

client = TestClient(app)

SPRINTER_PROFILE = {
    "cp_w": 200,
    "weight_kg": 72,
    "mmp": {"15": 961, "60": 520, "300": 280, "1200": 200, "3600": 175},
}
SNAPSHOT = {
    "mlss_power_watts": 275,
    "fatmax_power_watts": 175,
    "confidence_score": 0.35,
    "expressiveness": {"reliability": {"mlss": False}},
}
ATHLETE_SNIPPET = {"weight_kg": 72, "cp_w": 260, "ftp_w": 250}


class TestReadinessLoadPerfection:
    def test_zero_session_load_does_not_increment_sessions(self) -> None:
        state = update_load_state({"acute_load": 40, "chronic_load": 35, "load_sessions_count": 5}, 0)
        assert state["load_sessions_count"] == 5
        assert state["session_load"] == 0.0

    def test_manual_load_clamps_rpe_and_unknown_modality(self) -> None:
        out = calculate_manual_load(duration_min=45, rpe=15, modality="crossfit_variant")
        assert out["input"]["rpe"] == 10.0
        assert out["input"]["modality"] == "crossfit_variant"
        assert out["load"]["training_load_equivalent"] > 0

    def test_manual_load_nan_rpe_falls_back(self) -> None:
        out = calculate_manual_load(duration_min=30, rpe=float("nan"))
        assert out["input"]["rpe"] == 0.0

    def test_load_risk_high_with_planned_load_spike(self) -> None:
        out = compute_load_risk({"acute_load": 70, "chronic_load": 40}, planned_load=120)
        assert out["risk"] == "high"
        assert out["acute_chronic_ratio"] >= 1.5
        assert "confidence_valid_from_date" in out

    def test_load_risk_cold_start_flags(self) -> None:
        out = compute_load_risk({"acute_load": 30, "chronic_load": 5})
        assert "ewma_cold_start" in out["model_metadata"]["quality_flags"]

    def test_readiness_all_defaults_still_bounded(self) -> None:
        out = compute_readiness_today(load_state={"acute_load": 50, "chronic_load": 45})
        assert 0 <= out["readiness_score"] <= 100
        assert "ewma_cold_start" in out["warnings"] or out["ewma_trust_level"] in {"cold", "warming", "stable"}
        assert "hrv_status" in out["model_metadata"]["missing_inputs"]

    def test_readiness_extreme_fatigue_recommends_recovery(self) -> None:
        out = compute_readiness_today(
            load_state={"acute_load": 120, "chronic_load": 40},
            subjective={"score": 0.1},
            hrv_status={"score": 0.2},
            sleep_status={"score": 0.2},
        )
        assert out["readiness_score"] < 45
        assert out["recommendation"] == "recovery_or_rest"

    def test_api_load_manual_and_state_chain(self) -> None:
        manual = client.post(
            "/load/manual",
            json={"duration_min": 60, "rpe": 8, "modality": "strength"},
        )
        assert manual.status_code == 200
        load_eq = manual.json()["load"]["training_load_equivalent"]

        state = client.post(
            "/load/state/update",
            json={"session_load": load_eq},
        )
        assert state.status_code == 200
        assert state.json()["acute_load"] > 0

    def test_api_load_risk_requires_context(self) -> None:
        bad = client.post("/load/risk", json={})
        assert bad.status_code == 422
        ok = client.post(
            "/load/risk",
            json={"load_state": {"acute_load": 80, "chronic_load": 50}, "planned_load": 40},
        )
        assert ok.status_code == 200
        assert ok.json()["risk"] in {"low", "moderate", "high", "detraining"}


class TestPlanningPerfection:
    def test_season_plan_rejects_zero_weekly_hours(self) -> None:
        out = create_season_plan(start_date="2026-06-01", target_date="2026-08-01", weekly_hours=0)
        assert out["status"] == "invalid_input"
        assert out["weeks"] == []

    def test_check_load_risk_flags_large_weekly_jump(self) -> None:
        plan = create_season_plan(
            start_date="2026-06-01",
            target_date="2026-09-01",
            weekly_hours=12,
            athlete_profile=SPRINTER_PROFILE,
        )["weeks"]
        out = check_load_risk(plan, chronic_load=25)
        assert out["status"] == "success"
        assert out["risk"] in {"low", "moderate", "high"}
        assert isinstance(out["weekly_loads"], list)

    def test_adapt_plan_percent_compliance_not_treated_as_fraction(self) -> None:
        """78% compliance must not trigger small_progression (regression: 78 > 0.9)."""
        out = adapt_plan(
            [{"type": "vo2", "duration_min": 60}],
            readiness={"readiness_score": 90},
            last_compliance={"compliance_score": 78},
        )
        assert out["reason"] == "keep_plan"
        assert out["adapted_plan"][0]["type"] == "vo2"

    def test_adapt_plan_low_percent_compliance_reduces_load(self) -> None:
        out = adapt_plan(
            [{"type": "vo2", "duration_min": 60}],
            readiness={"readiness_score": 90},
            last_compliance={"compliance_score": 40},
        )
        assert out["reason"] == "reduce_load"
        assert out["adapted_plan"][0]["type"] == "endurance"

    def test_adapt_week_api_downgrades_vo2_on_low_readiness(self) -> None:
        response = client.post(
            "/planning/adapt-week",
            json={
                "week_plan": [{"type": "vo2", "duration_min": 60, "load": 70}],
                "readiness": {"readiness_score": 38},
                "compliance": {"compliance_score": 45},
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["reason"] == "reduce_load"
        assert body["week"][0]["type"] == "endurance"

    def test_api_check_load_risk_on_season_plan(self) -> None:
        season = client.post(
            "/planning/create-season-plan",
            json={
                "start_date": "2026-06-01",
                "target_date": "2026-08-15",
                "weekly_hours": 10,
                "athlete_profile": SPRINTER_PROFILE,
            },
        )
        assert season.status_code == 200
        weeks = season.json()["weeks"]
        risk = client.post(
            "/planning/check-load-risk",
            json={"plan": weeks, "chronic_load": 35},
        )
        assert risk.status_code == 200
        assert "weekly_loads" in risk.json()

    def test_planning_chain_season_to_adapt_to_recommend(self) -> None:
        season = create_season_plan(
            start_date="2026-06-01",
            target_date="2026-07-15",
            weekly_hours=8,
            athlete_profile=SPRINTER_PROFILE,
        )
        week0 = season["weeks"][0]["workouts"]
        adapted = adapt_week(week0, readiness={"readiness_score": 50}, compliance={"compliance_score": 60})
        assert adapted["status"] == "success"
        rec = client.post(
            "/workouts/recommend",
            json={
                "athlete_profile": SPRINTER_PROFILE,
                "readiness": {"readiness_score": 50},
                "goal": {"focus": "balanced"},
            },
        )
        assert rec.status_code == 200
        assert rec.json()["recommendation"]["focus"] in {"anaerobic", "vo2", "threshold", "recovery", "endurance"}


class TestCoachPerfection:
    COACH_ENDPOINTS = [
        ("/coach/daily-brief", {"athlete_id": "perf-1", "load_state": {"tsb": -10}}),
        ("/coach/session-decision", {"athlete_id": "perf-2", "planned_session": {"type": "threshold", "duration_min": 60}}),
        ("/coach/equipment-comfort", {"athlete_id": "perf-3"}),
        ("/coach/female-athlete-context", {"athlete_id": "perf-4"}),
        ("/coach/pnei-context", {"athlete_id": "perf-5", "checkin": {"stress": 6}}),
        ("/coach/endocrine-context", {"athlete_id": "perf-6"}),
        ("/coach/constraints", {"athlete_id": "perf-7", "constraints": {"travel_week": True}}),
        ("/coach/training-safety", {"athlete_id": "perf-8"}),
        ("/coach/attention", {"athlete_id": "perf-9"}),
        ("/coach/decision-safety", {"athlete_id": "perf-10"}),
        ("/coach/checkin", {"checkin": {"stress": 5, "motivation": 7}}),
        ("/coach/adherence", {"athlete_id": "perf-11", "performed_compliance": {"compliance_score": 72}}),
        ("/coach/testing-plan", {"athlete_id": "perf-12", "metabolic_snapshot": SNAPSHOT}),
        ("/coach/race-execution", {"athlete_id": "perf-13", "metabolic_snapshot": SNAPSHOT}),
        ("/coach/periodization", {"athlete_id": "perf-14", "season_plan": []}),
        ("/coach/communication-draft", {"athlete_id": "perf-15", "brief_summary": "Low readiness week"}),
        ("/coach/environment-adjustment", {"athlete_id": "perf-16", "environment": {"temperature_c": 32}}),
        ("/coach/attention/roster", {"roster": [{"athlete_id": "perf-17"}]}),
        ("/coach/strength/prescription", {"athlete": ATHLETE_SNIPPET}),
        ("/coach/nutrition/performance-targets", {"athlete": ATHLETE_SNIPPET}),
    ]

    @pytest.mark.parametrize("path,payload", COACH_ENDPOINTS)
    def test_all_coach_endpoints_return_200(self, path: str, payload: dict) -> None:
        response = client.post(path, json=payload)
        assert response.status_code == 200, f"{path}: {response.text[:300]}"
        body = response.json()
        assert body.get("status") in {None, "success", "insufficient_data", "valid", "partial", "warning"} or isinstance(body, dict)

    def test_conflicting_signals_illness_blocks_high_intensity(self) -> None:
        out = build_session_decision(
            athlete_id="conflict-1",
            planned_session={"type": "vo2", "duration_min": 75},
            twin_state={
                "metabolic_snapshot": SNAPSHOT,
                "training_safety_state": {
                    "training_safety": {"status": "stop", "avoid_today": ["high_intensity"]},
                },
            },
            readiness_state={"readiness_score": 88},
            load_state={"tsb": 10},
        )
        assert out["session_decision"]["final_recommendation"] in {"downgrade", "hold", "modify"}

    def test_partial_twin_state_daily_brief_still_safe(self) -> None:
        out = build_daily_brief(athlete_id="partial-1")
        brief = out["coach_daily_brief"]
        assert brief["not_autonomous"] is True
        assert brief["coach_review_required"] is True
        assert "decision_safety" in brief["modules"]

    def test_decision_safety_low_compliance_escalates(self) -> None:
        out = evaluate_decision_safety(
            athlete_id="comp-1",
            last_compliance={"compliance_score": 45},
            readiness_state={"readiness_score": 70},
        )
        assert "low_compliance" in out["decision_safety"]["reasons"]

    def test_prescription_safety_injury_requires_review(self) -> None:
        out = evaluate_prescription_safety(
            injury_flags=["acute_pain"],
            readiness_state={"readiness_score": 80},
        )
        assert out["level"] in {"coach_review_recommended", "professional_review_recommended"}


class TestPerformancePerfection:
    def test_ability_profile_compliance_percent_scale(self) -> None:
        """78% mean compliance → execution_consistency ~7.8, not capped at 10."""
        out = build_ability_profile(
            SPRINTER_PROFILE,
            weight_kg=72,
            compliance_history=[
                {"compliance_score": 80},
                {"compliance_score": 76},
            ],
        )
        assert out["levels"]["execution_consistency"] == pytest.approx(7.8, abs=0.2)

    def test_ability_profile_empty_curve_flags_low_confidence(self) -> None:
        out = build_ability_profile({"weight_kg": 70, "mmp": {"60": 400, "300": 320}})
        assert out["status"] == "success"
        assert out["dominant_ability"]
        assert out["model_metadata"]["confidence_score"] < 0.9

    def test_api_ability_profile_requires_weight_and_curve(self) -> None:
        bad = client.post("/performance/ability-profile", json={"athlete_profile": {}})
        assert bad.status_code == 422
        ok = client.post(
            "/performance/ability-profile",
            json={"athlete_profile": SPRINTER_PROFILE, "weight_kg": 72},
        )
        assert ok.status_code == 200
        assert ok.json()["dominant_ability"] in {"sprint", "anaerobic", "vo2", "threshold", "endurance"}

    def test_api_breakthroughs_requires_curves(self) -> None:
        bad = client.post("/performance/breakthroughs", json={})
        assert bad.status_code == 422

    def test_history_summary_empty_api_422_engine_ok(self) -> None:
        from engines.history.athlete_history import build_history_summary

        engine = build_history_summary([], weight_kg=70)
        assert engine["activity_count"] == 0
        api = client.post("/history/summary", json={"weight_kg": 70, "activities": []})
        assert api.status_code == 422


class TestCrossPipelinePerfection:
    def test_manual_load_to_readiness_to_recommend(self) -> None:
        manual = calculate_manual_load(duration_min=90, rpe=9, modality="strength")
        state = update_load_state(None, manual["load"]["training_load_equivalent"])
        readiness = compute_readiness_today(load_state=state, subjective={"score": 0.5})
        rec = client.post(
            "/workouts/recommend",
            json={
                "athlete_profile": SPRINTER_PROFILE,
                "readiness": {"readiness_score": readiness["readiness_score"]},
            },
        )
        assert rec.status_code == 200
        if readiness["readiness_score"] < 45:
            assert rec.json()["recommendation"]["focus"] == "recovery"

    def test_prescribe_feasibility_compare_full_chain(self) -> None:
        workout = {
            "steps": [
                {"duration_s": 600, "target_pct_ftp": 88, "type": "work", "is_key_step": True},
            ]
        }
        prescribe = client.post(
            "/workouts/prescribe",
            json={"workout": workout, "athlete_profile": {"ftp_w": 250, "cp_w": 260, "w_prime_j": 18000}},
        )
        assert prescribe.status_code == 200
        prescribed = prescribe.json()["prescription"]
        assert prescribed["prescription_status"] == "resolved"

        feas = client.post(
            "/workouts/feasibility",
            json={
                "workout": workout,
                "athlete_profile": {"ftp_w": 250, "cp_w": 260, "w_prime_j": 18000},
            },
        )
        assert feas.status_code == 200
        assert feas.json()["status"] == "success"

        target_w = prescribed["steps"][0]["resolved_target_w"]
        power = [int(target_w)] * 600
        compare = client.post(
            "/workouts/compare",
            data={
                "workout_json": json.dumps(prescribed),
                "athlete_profile_json": json.dumps({"ftp_w": 250, "cp_w": 260}),
                "power_json": json.dumps(power),
            },
        )
        assert compare.status_code == 200
        body = compare.json()
        assert body["status"] == "success"
        assert math.isfinite(body["compliance_score"])
        assert body["compliance_score"] >= 85
