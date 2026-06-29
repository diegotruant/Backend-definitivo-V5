"""Contract-first bug hunt — tests encode product truth, not current engine code.

Each test states what MUST happen in production. Failures indicate real bugs to fix.
"""

from __future__ import annotations

import pytest

from engines.adaptive_load.models import DailyStatus
from engines.adaptive_load.readiness import calculate_readiness
from engines.adaptive_load.scoring import calculate_external_load
from engines.coach.adherence_engine import evaluate_adherence
from engines.coach.attention_engine import evaluate_athlete_attention
from engines.coach.decision_safety_engine import evaluate_decision_safety
from engines.coach.prescription_safety import evaluate_prescription_safety
from engines.planning.season_planner import check_load_risk, create_season_plan
from engines.twin_state.models import build_twin_state, validate_twin_state
from engines.workouts.adaptive_planner import adapt_plan


class TestScaleContracts:
    def test_adaptive_plan_keeps_vo2_when_readiness_sent_as_fraction(self) -> None:
        out = adapt_plan(
            [{"type": "vo2", "duration_min": 60}],
            readiness={"readiness_score": 0.75},
            last_compliance={"compliance_score": 90},
        )
        assert out["reason"] == "keep_plan"
        assert out["adapted_plan"][0]["type"] == "vo2"

    def test_adaptive_plan_honors_readiness_score_alias(self) -> None:
        out = adapt_plan(
            [{"type": "vo2", "duration_min": 60}],
            readiness={"score": 40},
            last_compliance={"compliance_score": 90},
        )
        assert out["reason"] == "reduce_load"

    def test_attention_does_not_flag_fractional_compliance_as_low(self) -> None:
        out = evaluate_athlete_attention(athlete_id="a1", last_compliance={"compliance_score": 0.65})
        reasons = out["athlete_attention"]["reasons"]
        assert "high_fatigue_low_compliance" not in reasons

    def test_decision_safety_does_not_escalate_acceptable_fractional_compliance(self) -> None:
        out = evaluate_decision_safety(last_compliance={"compliance_score": 0.72})
        assert "low_compliance" not in out["decision_safety"]["reasons"]

    def test_decision_safety_escalates_low_percent_compliance(self) -> None:
        out = evaluate_decision_safety(last_compliance={"compliance_score": 0.55})
        assert "low_compliance" in out["decision_safety"]["reasons"]

    def test_prescription_safety_accepts_fractional_readiness_as_high(self) -> None:
        out = evaluate_prescription_safety(readiness_state={"readiness_score": 0.85})
        assert "readiness_very_low" not in out["reasons"]
        assert "readiness_low" not in out["reasons"]
        assert out["level"] == "ok_to_auto_suggest"

    def test_adaptive_load_sleep_fraction_means_percent(self) -> None:
        out = calculate_readiness(DailyStatus(sleep_score=0.85))
        assert out["components"]["sleep"] is not None
        assert out["components"]["sleep"] >= 80


class TestTwinComplianceWrapping:
    def test_decision_safety_reads_wrapped_twin_compliance(self) -> None:
        out = evaluate_decision_safety(
            twin_state={
                "last_compliance_results": [{
                    "assignment_id": "w1",
                    "result": {"compliance_score": 35, "missed_key_work": True},
                }]
            }
        )
        reasons = out["decision_safety"]["reasons"]
        assert "low_compliance" in reasons
        assert "missed_key_work" in reasons

    def test_attention_reads_wrapped_missed_key_work(self) -> None:
        out = evaluate_athlete_attention(
            athlete_id="a1",
            twin_state={
                "last_compliance_results": [{
                    "result": {"compliance_score": 50, "missed_key_work": True},
                }]
            },
        )
        assert "missed_key_work" in out["athlete_attention"]["reasons"]

    def test_adherence_trend_from_wrapped_history(self) -> None:
        out = evaluate_adherence(
            performed_compliance={"compliance_score": 80},
            compliance_history=[
                {"result": {"compliance_score": 50}},
                {"result": {"compliance_score": 48}},
                {"result": {"compliance_score": 45}},
            ],
        )
        assert out["compliance"]["trend"] == "declining"


class TestTwinStateContracts:
    def test_w_prime_kj_converted_to_joules(self) -> None:
        state = build_twin_state({"athlete_id": "a1", "metabolic_snapshot": {"w_prime_kj": 20}})
        assert state["metabolic_metrics"]["w_prime_j"] >= 15000

    def test_validate_rejects_impossible_readiness_score(self) -> None:
        with pytest.raises(ValueError, match="readiness_score"):
            build_twin_state({"athlete_id": "a1", "readiness_state": {"readiness_score": 500}})


class TestPlanningContracts:
    def test_inverted_season_dates_are_invalid(self) -> None:
        out = create_season_plan(start_date="2026-06-01", target_date="2026-01-01", weekly_hours=8)
        assert out["status"] == "invalid_input"
        assert out["error"] == "target_date_before_start_date"

    def test_empty_plan_load_risk_is_not_silent_success(self) -> None:
        out = check_load_risk([])
        assert out["status"] == "insufficient_data"
        assert out["risk"] == "unknown"

    def test_load_risk_sensitive_to_chronic_baseline(self) -> None:
        plan = create_season_plan(start_date="2026-06-01", target_date="2026-08-01", weekly_hours=8)["weeks"]
        stricter = check_load_risk(plan, chronic_load=100.0)
        looser = check_load_risk(plan, chronic_load=350.0)
        assert stricter["risk"] == "high"
        assert looser["risk"] in {"low", "moderate"}


class TestAdaptiveLoadContracts:
    def test_extreme_tss_marks_capped_flag(self) -> None:
        out = calculate_external_load({"available": True, "tss": 250})
        assert out["score"] == 100.0
        assert out["capped"] is True
        assert out["tss"] == 250.0


class TestCoachInputSafety:
    def test_attention_ignores_unknown_checkin_keys(self) -> None:
        out = evaluate_athlete_attention(
            athlete_id="a1",
            checkin={"athlete_id": "a1", "motivation": 3, "stress": 9},
        )
        assert out["status"] == "success"
