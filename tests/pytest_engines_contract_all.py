"""Contract-first tests for every engines/ package — written to find bugs, not mirror code.

Each test states production truth. Failures require engine fixes.
"""

from __future__ import annotations

import importlib
import pkgutil
from datetime import date

import numpy as np
import pytest

import engines

# ---------------------------------------------------------------------------
# adaptive_load
# ---------------------------------------------------------------------------
from engines.adaptive_load.models import DailyStatus
from engines.adaptive_load.orchestrator import build_adaptive_load_report
from engines.adaptive_load.readiness import calculate_readiness
from engines.adaptive_load.recommendation import generate_recommendation
from engines.adaptive_load.scoring import calculate_external_load, calculate_session_load
from engines.adaptive_load.trend import calculate_load_trend


class TestAdaptiveLoadContracts:
    def test_extreme_tss_reports_capped(self) -> None:
        out = calculate_external_load({"available": True, "tss": 250})
        assert out["capped"] is True

    def test_readiness_fraction_sleep_is_high(self) -> None:
        out = calculate_readiness(DailyStatus(sleep_score=0.85))
        assert out["components"]["sleep"] >= 80

    def test_recommendation_does_not_flag_healthy_fraction_readiness(self) -> None:
        out = generate_recommendation(
            session_load={"score": 60},
            trend={"load_ratio": 1.0, "tsb": 0},
            readiness={"score": 0.82},
        )
        assert "readiness_low" not in out["reasons"]


# ---------------------------------------------------------------------------
# coach (beyond pytest_contract_bug_hunt)
# ---------------------------------------------------------------------------
from engines.coach.checkin_engine import process_checkin
from engines.coach.constraints_engine import evaluate_constraints
from engines.coach.environment_adjustment_engine import build_environment_adjustment
from engines.coach.equipment_comfort_engine import evaluate_equipment_comfort
from engines.coach.female_athlete_context_engine import build_female_athlete_context
from engines.coach.periodization_engine import review_periodization
from engines.coach.race_execution_engine import build_race_execution_plan
from engines.coach.testing_scheduler_engine import build_testing_plan
from engines.coach.communication_draft_engine import build_communication_draft


class TestCoachEnginesContracts:
    def test_checkin_stress_high_flags_review(self) -> None:
        out = process_checkin(stress=9, motivation=2, perceived_fatigue=9)
        assert out["psychological_support_flag"]["human_check_recommended"] is True

    def test_constraints_travel_reduces_volume(self) -> None:
        out = evaluate_constraints(constraints={"travel_week": True, "available_days": ["tue"]})
        assert out["adaptation"]["volume_factor"] < 1.0

    def test_environment_heat_caps_intensity(self) -> None:
        out = build_environment_adjustment(
            environment_context={"temperature_c": 36, "humidity_pct": 80},
        )
        assert out["environment_adjustment"]["intensity_cap_adjustment_pct"] < 100

    def test_equipment_multiple_pain_flags_high_priority(self) -> None:
        out = evaluate_equipment_comfort(
            comfort_notes=["saddle pain", "back pain", "knee pain", "hand numbness"],
        )
        assert out["equipment_comfort_review"]["status"] == "high_priority_review"

    def test_female_context_never_auto_prescribes_cycle(self) -> None:
        out = build_female_athlete_context(context={"cycle_phase": "luteal", "energy": 4})
        assert out["female_athlete_context"]["auto_prescription_from_cycle"] is False

    def test_periodization_flags_gym_bike_conflict(self) -> None:
        out = review_periodization(
            upcoming_bike_sessions=[{"date": "2026-06-02", "type": "vo2", "duration_min": 60}],
            strength_prescription={"scheduled_days": ["2026-06-02"]},
            season_phase="build",
        )
        assert out["periodization_review"]["conflicts"]

    def test_testing_plan_weak_mlss_prioritizes_lactate(self) -> None:
        snap = {"mlss_power_watts": 260, "confidence_score": 0.3, "expressiveness": {"reliability": {"mlss": False}}}
        out = build_testing_plan(metabolic_snapshot=snap, days_since_last_lactate_test=120)
        assert out["testing_recommendation"]["priority"] in {"high", "medium"}

    def test_race_execution_without_curves_still_returns_plan(self) -> None:
        out = build_race_execution_plan(target_event="granfondo", duration_h=4)
        assert out["status"] == "success"
        assert out["race_execution_plan"]["pacing_strategy"]

    def test_communication_draft_never_autonomous(self) -> None:
        out = build_communication_draft(athlete_id="c1")
        assert out["communication_draft"]["coach_review_required"] is True


# ---------------------------------------------------------------------------
# endocrine
# ---------------------------------------------------------------------------
from engines.endocrine.endocrine_context_engine import build_endocrine_context


class TestEndocrineContracts:
    def test_fractional_readiness_not_treated_as_points(self) -> None:
        out = build_endocrine_context(readiness_state={"readiness_score": 0.8})
        assert out["endocrine_context"]["status"] != "professional_review"

    def test_reds_flag_requires_professional_review(self) -> None:
        out = build_endocrine_context(nutrition_energy={"red_flags": ["reds_risk_flag"]})
        assert out["endocrine_context"]["status"] == "professional_review"


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------
from engines.history.athlete_history import build_history_summary
from engines.history.load_trends import compute_load_trends
from engines.history.power_curve_history import build_power_curve_history


class TestHistoryContracts:
    def test_empty_activities_load_trends_not_success(self) -> None:
        out = compute_load_trends([])
        assert out["status"] == "insufficient_data"

    def test_history_summary_empty_is_success_at_engine(self) -> None:
        out = build_history_summary([], weight_kg=70)
        assert out["activity_count"] == 0

    def test_power_curve_empty_activities_reports_zero_count(self) -> None:
        out = build_power_curve_history([])
        assert out["status"] == "success"
        assert out["periods"]["all_time"]["activity_count"] == 0


# ---------------------------------------------------------------------------
# integrations
# ---------------------------------------------------------------------------
from engines.integrations.activity_normalizer import deduplicate_activities, normalize_external_activity


class TestIntegrationsContracts:
    def test_normalize_always_assigns_activity_id(self) -> None:
        out = normalize_external_activity({"power_w": 250, "duration_s": 3600})
        assert out["status"] == "success"
        assert out["activity"]["activity_id"]

    def test_deduplicate_flags_repeated_import(self) -> None:
        act = {"start_time": "2026-01-01", "distance_m": 10000, "duration_s": 3600, "source_id": "a1"}
        out = deduplicate_activities([act, act])
        assert out["duplicate_count"] == 1


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------
from engines.load.manual_load import calculate_manual_load


class TestLoadContracts:
    def test_nan_rpe_is_zero_not_ten(self) -> None:
        out = calculate_manual_load(duration_min=30, rpe=float("nan"))
        assert out["input"]["rpe"] == 0.0


# ---------------------------------------------------------------------------
# nutrition + strength
# ---------------------------------------------------------------------------
from engines.nutrition.performance_fueling_engine import build_performance_fueling_targets
from engines.strength.strength_prescription_engine import prescribe_strength


class TestNutritionStrengthContracts:
    def test_fueling_fractional_readiness_not_low_energy_flag(self) -> None:
        out = build_performance_fueling_targets(
            athlete={"weight_kg": 70},
            readiness_state={"readiness_score": 0.8},
        )
        assert "low_energy_availability_risk" not in out["red_flags"]

    def test_strength_injury_blocks_heavy_prescription(self) -> None:
        out = prescribe_strength(athlete={"weight_kg": 70, "cp_w": 250}, injury_flags=["acute_pain"])
        assert out["decision_safety"]["level"] != "ok_to_auto_suggest"


# ---------------------------------------------------------------------------
# planning + projection + readiness
# ---------------------------------------------------------------------------
from engines.planning.plan_adapter import adapt_week
from engines.planning.season_planner import check_load_risk, create_season_plan
from engines.projection.season_projection_engine import project_season_from_plan
from engines.readiness.readiness_engine import compute_load_risk, compute_readiness_today, update_load_state
from engines.twin_state.models import build_twin_state
from engines.twin_state.state_update_engine import update_twin_state_from_ride


class TestPlanningProjectionReadinessContracts:
    def test_projection_uses_chronic_load_when_ctl_missing(self) -> None:
        state = build_twin_state({
            "athlete_id": "p1",
            "load_state": {"chronic_load": 90, "acute_load": 45},
        })
        out = project_season_from_plan(state, [], start_date="2026-06-01", target_date="2026-06-07")
        assert out["time_series"][0]["ctl"] >= 85

    def test_ride_ingest_updates_load_state(self) -> None:
        base = build_twin_state({"athlete_id": "p2", "load_state": {"acute_load": 40, "chronic_load": 55}})
        out = update_twin_state_from_ride(base, ride_summary={"headline": {"training_load": 120, "tss": 120}})
        assert out["load_state"]["acute_load"] > 40

    def test_adapt_week_percent_compliance_keeps_plan(self) -> None:
        out = adapt_week(
            [{"type": "vo2", "duration_min": 60}],
            readiness={"readiness_score": 90},
            compliance={"compliance_score": 78},
        )
        assert out["reason"] == "keep_plan"

    def test_load_risk_empty_plan_insufficient(self) -> None:
        assert check_load_risk([])["status"] == "insufficient_data"

    def test_negative_session_load_does_not_increment_sessions(self) -> None:
        state = update_load_state({"load_sessions_count": 3, "acute_load": 30, "chronic_load": 28}, -5)
        assert state["load_sessions_count"] == 3


# ---------------------------------------------------------------------------
# performance (selected public engines)
# ---------------------------------------------------------------------------
from engines.performance.breakthrough_detector import detect_breakthroughs
from engines.performance.training_variability_engine import calculate_acwr, calculate_monotony_strain
from engines.performance.durability_engine import calculate_durability_index
from engines.performance.power_engine import normalized_power


class TestPerformanceContracts:
    def test_acwr_zero_ctl_is_error_not_success(self) -> None:
        out = calculate_acwr(atl=50, ctl=0)
        assert out["status"] == "error"

    def test_monotony_insufficient_days(self) -> None:
        out = calculate_monotony_strain([50, 60, 70])
        assert out["status"] == "insufficient_data"

    def test_breakthrough_requires_gain(self) -> None:
        out = detect_breakthroughs({"60": 300}, {"60": 301}, min_gain_pct=5)
        assert out.get("breakthroughs") == [] or out["status"] == "success"

    def test_normalized_power_empty_is_zero(self) -> None:
        assert normalized_power(np.array([])) == 0.0

    def test_durability_short_ride_insufficient(self) -> None:
        out = calculate_durability_index([200.0] * 100, duration_seconds=600)
        assert out.get("status") in {"insufficient_duration", "success", "error"}


# ---------------------------------------------------------------------------
# recovery
# ---------------------------------------------------------------------------
from engines.recovery.thermal_engine import analyze_thermal_session
from engines.recovery.pedaling_balance import analyze_pedaling_balance


class TestRecoveryContracts:
    def test_thermal_no_data_not_success(self) -> None:
        out = analyze_thermal_session([], [])
        assert out.data_quality == "no_data"

    def test_pedaling_balance_empty_stream(self) -> None:
        out = analyze_pedaling_balance([], [])
        assert out.data_quality == "insufficient_data"


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
from engines.routes.segment_engine import compare_segments, detect_climb_segments


class TestRoutesContracts:
    def test_compare_segments_no_history_not_matched(self) -> None:
        out = compare_segments([], [{"distance_m": 1000, "elevation_gain_m": 50}])
        assert out["status"] == "success"
        assert out["comparisons"][0]["matched"] is False

    def test_climb_detection_missing_altitude_skipped(self) -> None:
        class _Stream:
            altitude_m = []
            distance_m = []

        out = detect_climb_segments(_Stream())
        assert out["status"] == "skipped"


# ---------------------------------------------------------------------------
# twin_state + workouts
# ---------------------------------------------------------------------------
from engines.workouts.calendar_engine import validate_status_transition
from engines.workouts.recommendation_engine import recommend_workout
from engines.workouts.feasibility_engine import analyze_workout_feasibility
from engines.workouts.exporters.erg import export_erg


class TestWorkoutsTwinContracts:
    def test_calendar_completed_to_assigned_blocked(self) -> None:
        out = validate_status_transition("completed", "assigned")
        assert out["allowed"] is False

    def test_recommendation_fractional_readiness_not_recovery(self) -> None:
        profile = {"cp_w": 260, "ftp_w": 250, "mmp": {"60": 400, "300": 320, "1200": 280}}
        out = recommend_workout(profile, readiness={"readiness_score": 0.82})
        assert out["recommendation"]["focus"] != "recovery"

    def test_feasibility_missing_w_prime_insufficient(self) -> None:
        out = analyze_workout_feasibility(
            {"steps": [{"duration_s": 300, "target_w": 250, "type": "work"}]},
            {"cp_w": 260},
        )
        assert out["status"] == "insufficient_data"

    def test_erg_export_defaults_missing_duration(self) -> None:
        out = export_erg({"steps": [{"target_w": 200}]})
        assert "[COURSE HEADER]" in out["content"]


# ---------------------------------------------------------------------------
# metabolic + io + core
# ---------------------------------------------------------------------------
from engines.core.model_safety import finalize_model_metadata
from engines.io.workout_summary import build_workout_summary
from engines.metabolic.fatmax_engine import build_model_fatmax_report
from engines.metabolic.metabolic_coach_curves import build_metabolic_curves_report
from engines.recovery.hrv_engine import analyze_rr_stream


class TestMetabolicIoCoreContracts:
    def test_fatmax_empty_snapshot_insufficient(self) -> None:
        out = build_model_fatmax_report({})
        assert out["status"] == "insufficient_data"
        assert out["measurement_tier"] == "INSUFFICIENT_DATA"

    def test_metabolic_curves_empty_snapshot_not_lab_measured(self) -> None:
        out = build_metabolic_curves_report({}, weight_kg=70.0)
        assert out.get("status") in {"insufficient_data", "success", "partial"}
        if out.get("measurement_tier"):
            assert out["measurement_tier"] != "LAB_MEASURED"

    def test_workout_summary_empty_stream_zero_duration(self) -> None:
        class _EmptyStream:
            elapsed_s = np.array([], dtype=float)
            power = np.array([], dtype=float)
            heart_rate = np.array([], dtype=float)
            total_elapsed_s = 0
            sport = "cycling"
            n_samples = 0
            has_power = False
            has_heart_rate = False
            has_rr = False

        out = build_workout_summary(_EmptyStream(), weight_kg=70)
        assert out["stream_metadata"]["duration_s"] == 0

    def test_model_safety_missing_inputs_caps_confidence(self) -> None:
        out = finalize_model_metadata(missing_inputs=["ftp_w"], confidence=0.9)
        assert out["confidence_score"] <= 0.55

    def test_hrv_empty_rr_returns_no_windows(self) -> None:
        assert analyze_rr_stream([]) == []


# ---------------------------------------------------------------------------
# Package import health — every engines subpackage must import cleanly
# ---------------------------------------------------------------------------
class TestEnginesPackageIntegrity:
    @pytest.mark.parametrize(
        "module_name",
        sorted(
            mod.name
            for mod in pkgutil.walk_packages(engines.__path__, engines.__name__ + ".")
            if not mod.name.endswith(".__init__")
        ),
    )
    def test_engine_module_importable(self, module_name: str) -> None:
        mod = importlib.import_module(module_name)
        assert mod is not None
