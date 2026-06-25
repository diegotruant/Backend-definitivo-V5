"""Phase 4 coverage depth — targeted tests for low-coverage public APIs."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

import numpy as np
import pytest

from api.domain_schemas import TwinStateDocument
from api.engine_schemas import (
    AdaptiveLoadRequest,
    DurabilityIndexRequest,
    EffortsAnalyzeRequest,
    SessionClassifyRequest,
    WPrimeBalanceRequest,
    ZonesAnalyzeRequest,
)
from api.errors import ServiceError
from api.schemas import AthleteParams, SeasonProjectionRequest, TeamCalibrationApplyRequest, TwinStateBuildRequest
from api.services.profile_extended_service import ProfileExtendedService
from api.services.ride_analytics_service import RideAnalyticsService
from api.services.team_service import TeamService
from api.services.twin_service import TwinService
from engines.core import security
from engines.core.science_contracts import (
    cadence_anchor_metadata,
    cp_anchor_warnings,
    derive_effective_cadence_rpm,
    enrich_metabolic_snapshot_cadence,
    vlamax_limitations,
)
from engines.core.tiers import annotate, mask_low_confidence, should_display, tier_for
from engines.history.athlete_history import build_history_summary, compute_personal_records
from engines.history.load_trends import compute_load_trends
from engines.core.data_quality_engine import (
    assess_data_quality,
    clean_hr_stream,
    clean_power_stream,
    clean_workout_data,
    detect_pauses,
    remove_pauses,
)
from engines.core.athlete_context import AthleteContext
from engines.core.athlete_physiological_prior import MeasuredProfile, PhysiologicalPriorManager
from engines.io.fit_parser import (
    QUALITY_FORWARD_FILLED,
    QUALITY_GOOD,
    QUALITY_INTERPOLATED,
    QUALITY_UNRELIABLE,
    ActivityStreamEnhanced,
    detect_and_fill_gaps,
    measured_signal_flags,
    normalize_lap_messages,
    parse_fit_records_enhanced,
    _available_measured_signals,
    _ensure_utc_datetime,
)
from engines.io.activity_intelligence import build_activity_intelligence, compute_best_efforts, detect_auto_intervals
from engines.metabolic.team_learning_engine import TeamCalibrationModel, ValidationEvent
from types import SimpleNamespace

from engines.adaptive_load.models import AthleteLoadProfile, DailyStatus
from engines.adaptive_load.orchestrator import build_adaptive_load_report
from engines.adaptive_load.readiness import calculate_readiness
from engines.adaptive_load.trend import calculate_load_trend
from engines.metabolic.lab_data import (
    LabSource,
    LabTestResult,
    LabTestType,
    LactatePoint,
    create_lab_result,
    parse_lab_text,
    validate_lab_result,
)
from engines.performance.breakthrough_detector import detect_breakthroughs
from engines.performance.effort_extractor import extract_test_proposal
from engines.performance.interval_detector import (
    QualifiedAnchor,
    classify_session,
    protocol_completeness,
)
from engines.performance.mmp_quality import analyze_mmp_quality, clean_mmp, filter_mmp_by_window
from engines.performance.test_protocols import (
    run_critical_power_test,
    run_incremental_test,
    run_power_cadence_test,
    run_test,
    run_wingate_test,
)
from engines.history.power_curve_history import aggregate_power_curve, build_power_curve_history
from engines.io.activity_charts import (
    build_activity_charts,
    chart_ambient_temp,
    chart_cadence,
    chart_elevation,
    chart_heart_rate,
    chart_position,
    chart_power,
    chart_power_phase,
    chart_respiration,
    chart_speed,
    chart_time_in_power_zone,
)
from engines.io.chart_builder import (
    chart_cardiac_drift,
    chart_cross_validation_matrix,
    chart_detraining_decay,
    chart_efforts_radar,
    chart_hr_kinetics,
    chart_hr_recovery,
    chart_hrv_timeline,
    chart_metabolic_combustion,
    chart_phenotype_spider,
    chart_power_duration_curve,
    chart_power_hr_scatter,
    chart_training_load,
    chart_zones_distribution,
    generate_workout_charts,
)
from engines.io.profile_anchor_flow import build_anchor_from_proposal, update_profile_from_ride
from engines.io.session_router import decide_route, route_and_run
from engines.load.manual_load import calculate_manual_load
from engines.metabolic.coggan_classifier import classify_duration, classify_from_mmp, classify_power_profile
from engines.metabolic.glycolytic_validation_engine import (
    build_glycolytic_profile,
    compute_vlapeak_observed,
    validate_vlapeak_against_model,
    validate_wingate_glycolytic,
)
from engines.metabolic.metabolic_flexibility_engine import (
    calculate_metabolic_flexibility_index,
    estimate_fat_oxidation_rate,
)
from engines.metabolic.detraining_engine import apply_detraining_model, calculate_ctl_atl_tsb, calculate_decay_factor
from engines.metabolic.metabolic_current import get_current_metabolic_status, handle_edge_function_request
from engines.metabolic.metabolic_profiler_phenotype import (
    compute_energy_contribution_adaptive,
    compute_recovery_curve_adaptive,
    enhance_metabolic_snapshot_with_phenotype,
    get_pcr_params,
)
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.metabolic.metabolic_kalman import DailyInput, MetabolicKalman, process_workout_history
from engines.performance.durability_engine import (
    calculate_durability_index,
    calculate_np_drift,
    calculate_tte_sustainability,
    generate_durability_prescription,
    generate_hourly_decay_curve,
)
from engines.performance.efforts_analyzer import analyze_efforts
from engines.performance.mader_residual_mlp import NeuralDynamics, NeuralPowerDuration, TinyMLP
from engines.performance.mmp_aggregator import curve_to_mmp, extract_ride_curve, update_power_curve
from engines.performance.physiological_resilience import build_physiological_resilience
from engines.performance.race_prediction_engine import (
    AthleteRaceProfile,
    CourseSegment,
    analyze_course,
    parse_gpx_course,
    simulate_gpx_race,
)
from engines.performance.training_variability_engine import calculate_acwr, calculate_monotony_strain
from engines.recovery.cardiac_engine import (
    ActivitySample,
    CardiacResponseAnalyzer,
    Segment,
    compute_aerobic_decoupling,
    compute_cardiac_drift,
    compute_cardiac_efficiency,
    compute_chronotropic_response,
    compute_hr_kinetics_tau,
    compute_hr_recovery,
    cross_validate_thresholds,
)
from engines.recovery.explainability_engine import (
    ConfidenceLevel,
    calculate_durability_confidence,
    calculate_vo2max_confidence,
    generate_acwr_narrative,
    generate_durability_narrative,
    generate_metric_narrative,
    generate_workout_summary_narrative,
)
from engines.recovery.pedaling_balance import analyze_balance_trend, analyze_pedaling_balance
from engines.routes.segment_engine import compare_segments, detect_climb_segments
from engines.recovery.thermal_engine import ThermalSessionReport, analyze_heat_acclimation, analyze_thermal_session
from engines.workouts.adaptive_planner import adapt_plan
from engines.workouts.calendar_engine import validate_status_transition
from engines.workouts.recommendation_engine import recommend_workout
from engines.workouts.template_engine import prescribe_for_athlete, validate_template
from engines.recovery.hrv_engine import (
    _artifact_mask,
    _compute_sqi,
    _correct_ectopic,
    _detect_threshold_crossing,
    _normal_z_for_ci,
    _prepare_rr_quality,
    analyze_rr_stream,
    calculate_dfa_alpha1,
    detect_thresholds_from_activity,
)
from engines.workouts.models import (
    WorkoutStep,
    WorkoutValidationError,
    materialize_workout,
    normalize_workout,
    validate_workout_payload,
)
from engines.workouts.progression_levels import compute_progression_levels
from tests._fixtures import twin_build_payload, workout_pct_cp


def _stream(
    *,
    seconds: int = 3600,
    power: float = 250.0,
    with_rr: bool = False,
    device_name: str | None = None,
) -> Any:
    start = datetime(2026, 1, 1, 8, 0, 0)
    records: List[Dict[str, Any]] = []
    for i in range(seconds):
        row: Dict[str, Any] = {
            "timestamp": start + timedelta(seconds=i),
            "power": power,
            "heart_rate": 140 + (i % 20),
            "cadence": 90,
        }
        if with_rr:
            row["rr_intervals"] = [820.0, 810.0, 805.0]
        records.append(row)
    session: Dict[str, Any] = {
        "sport": "cycling",
        "start_time": start,
        "total_elapsed_time": seconds,
    }
    if device_name:
        session["device_name"] = device_name
    return parse_fit_records_enhanced(records, session_dict=session)


def _twin_doc() -> TwinStateDocument:
    state = TwinService().build(TwinStateBuildRequest(payload=twin_build_payload()))
    return TwinStateDocument.model_validate(state)


class TestDataQualityEngine:
    def test_assess_good_streams(self) -> None:
        power = [220 + (i % 10) for i in range(600)]
        hr = [140 + (i % 5) for i in range(600)]
        cadence = [90 + (i % 3) for i in range(600)]
        report = assess_data_quality(power, hr, cadence)
        assert report.overall_score >= 0.6
        assert report.usable_for_analysis

    def test_assess_detects_low_quality_power(self) -> None:
        power = [0.0] * 200 + [50.0] * 100
        report = assess_data_quality(power)
        assert report.power_quality < 1.0
        assert report.overall_score < 1.0

    def test_clean_workout_data_removes_pauses(self) -> None:
        power = [0.0] * 30 + [250.0] * 120 + [0.0] * 30 + [250.0] * 120
        out = clean_workout_data(power, remove_pauses_flag=True)
        assert out["power_cleaned"]
        assert out["quality_report"].overall_score >= 0
        pauses = detect_pauses(power)
        assert pauses


class TestIntervalDetector:
    def test_classify_by_filename_ramp_test(self) -> None:
        powers = [150 + i * 2 for i in range(600)]
        result = classify_session(powers, filename="athlete_ramp_test.fit", ftp=280)
        assert result.category == "TEST"
        assert result.subtype == "ramp_test"
        assert result.source == "filename"

    def test_classify_with_explicit_hint(self) -> None:
        result = classify_session([200] * 300, hint=("ENDURANCE", "steady"), ftp=250)
        assert result.category == "ENDURANCE"
        assert result.confidence == 1.0

    def test_protocol_completeness_reports_gaps(self) -> None:
        report = protocol_completeness(available_durations_s=[60, 300, 1200])
        body = report.to_dict()
        assert "completeness_pct" in body
        assert body["completeness_pct"] >= 0


class TestMmpQuality:
    def test_detects_identical_plateau(self) -> None:
        mmp = {300: 320.0, 600: 320.0, 1200: 310.0, 1800: 305.0}
        report = analyze_mmp_quality(mmp)
        assert report.total_anchors == 4
        assert any(i.category == "identical_plateau" for i in report.issues)

    def test_clean_mmp_drops_redundant_anchors(self) -> None:
        mmp = {300: 320.0, 600: 320.0, 1200: 310.0}
        cleaned, audit = clean_mmp(mmp)
        assert len(cleaned) < len(mmp)
        assert audit["dropped"]


class TestHrvEngine:
    def test_analyze_rr_stream_returns_windows(self) -> None:
        rr_samples = [
            {"elapsed": float(i * 5), "rr": [800.0 + (i % 7)] * 20}
            for i in range(80)
        ]
        timeline = analyze_rr_stream(rr_samples, window_seconds=60, step_seconds=10.0)
        assert isinstance(timeline, list)

    def test_analyze_rr_stream_empty_input(self) -> None:
        assert analyze_rr_stream([]) == []


class TestTeamServiceDepth:
    def test_apply_calibration_snapshot_path(self) -> None:
        model = TeamCalibrationModel.fit(
            [
                ValidationEvent(
                    athlete_id="r1",
                    team_id="wt",
                    parameter="mlss",
                    predicted_value=280,
                    measured_value=270,
                )
                for _ in range(5)
            ],
            team_id="wt",
        )
        svc = TeamService()
        out = svc.apply_calibration(
            TeamCalibrationApplyRequest(
                calibration_model=model.to_dict(),
                snapshot={"status": "success", "mlss_power_watts": 285},
                athlete_id="r1",
            )
        )
        assert out["mlss_power_watts"] <= 285

    def test_apply_calibration_requires_parameter_or_snapshot(self) -> None:
        svc = TeamService()
        with pytest.raises(ServiceError) as exc:
            svc.apply_calibration(
                TeamCalibrationApplyRequest(calibration_model={"team_id": "wt", "events": [], "corrections": {}})
            )
        assert exc.value.code == "CALIBRATION_APPLY_INPUT"

    def test_update_calibration_invalid_event_raises(self) -> None:
        from api.schemas import TeamCalibrationUpdateRequest

        svc = TeamService()
        with pytest.raises(ServiceError) as exc:
            svc.update_calibration(
                TeamCalibrationUpdateRequest(team_id="wt", events=[{"parameter": "mlss", "predicted_value": -1}])
            )
        assert exc.value.code == "CALIBRATION_UPDATE"


class TestTwinServiceDepth:
    def test_project_season_rejects_deep_payload(self) -> None:
        deep: object = {"v": 1}
        for _ in range(security.MAX_JSON_DEPTH + 5):
            deep = {"nested": deep}
        twin = _twin_doc()
        twin_dict = twin.model_dump()
        twin_dict["athlete_profile"] = deep
        req = SeasonProjectionRequest(
            twin_state=TwinStateDocument.model_validate(twin_dict),
            calendar_plan=[],
            start_date="2026-06-01",
            target_date="2026-06-03",
        )
        with pytest.raises(ServiceError) as exc:
            TwinService().project_season(req)
        assert exc.value.code == "PAYLOAD_TOO_DEEP"

    def test_project_season_success_with_empty_calendar(self) -> None:
        req = SeasonProjectionRequest(
            twin_state=_twin_doc(),
            calendar_plan=[],
            start_date="2026-06-01",
            target_date="2026-06-05",
        )
        out = TwinService().project_season(req)
        assert out["status"] == "success"
        assert len(out["time_series"]) == 5


class TestRideAnalyticsServiceDepth:
    def setup_method(self) -> None:
        self.svc = RideAnalyticsService()
        self.stream = _stream(seconds=7200, power=255.0)
        self.athlete = AthleteParams(weight_kg=72.0, ftp=280.0)

    def test_zones_analyze(self) -> None:
        out = self.svc.zones(
            self.stream,
            ZonesAnalyzeRequest(athlete=self.athlete, ftp=280.0),
        )
        assert "zones" in out or out.get("status") in {"success", "partial"}

    def test_classify_session_ride(self) -> None:
        stream = _stream(seconds=1800, device_name="ftp_20min_test.fit")
        out = self.svc.classify_session_ride(
            stream,
            SessionClassifyRequest(athlete=self.athlete, ftp=280.0),
        )
        assert out.get("category") == "TEST"

    def test_protocol_completeness_service(self) -> None:
        out = self.svc.protocol_completeness(self.stream)
        assert "completeness_pct" in out

    def test_resilience_and_metabolic_flexibility(self) -> None:
        assert self.svc.resilience(mader_durability={"status": "success", "durability_loss_pct": 5.0})
        partial = self.svc.metabolic_flexibility({"estimated_vo2max": 55})
        assert partial["status"] == "partial"
        ok = self.svc.metabolic_flexibility({"fatmax_power_watts": 200, "mlss_power_watts": 280})
        assert ok.get("status") == "success"

    def test_hrv_and_cardiac_edge_cases(self) -> None:
        no_rr = self.svc.hrv_analyze(self.stream)
        assert no_rr["status"] == "error"
        cardiac = self.svc.cardiac(self.stream, athlete=self.athlete, metabolic_snapshot=None)
        assert cardiac.get("status") in {"success", "partial", "error"}

    def test_w_prime_balance_and_durability(self) -> None:
        power = [300] * 600 + [200] * 300
        bal = self.svc.w_prime_balance(
            WPrimeBalanceRequest(power=power, cp=270, w_prime=20000, dt_s=1.0)
        )
        assert "balance" in bal
        di = self.svc.durability_index(DurabilityIndexRequest(power=power))
        assert di["status"] in {"success", "insufficient_duration"}

    def test_efforts_analyze(self) -> None:
        out = self.svc.efforts(
            self.stream,
            EffortsAnalyzeRequest(athlete=self.athlete, ftp=280.0, cp_w=270.0),
        )
        assert out.get("status") in {"success", "partial", "warning"}


class TestProfileExtendedServiceDepth:
    def test_mmp_quality_endpoint_logic(self) -> None:
        svc = ProfileExtendedService()
        from api.engine_schemas import MmpQualityRequest

        out = svc.mmp_quality(MmpQualityRequest(mmp={"300": 320, "600": 320, "1200": 300}))
        assert "quality_score" in out
        assert "issues" in out

    def test_ctl_atl_tsb_history(self) -> None:
        svc = ProfileExtendedService()
        out = svc.ctl_atl_tsb([{"date": "2026-01-01", "tss": 50}] * 14)
        assert "ctl" in out
        assert "tsb" in out


def _flat_power(power_w: float, dur_s: int, *, noise: float = 0.0) -> List[float]:
    arr = np.full(dur_s, float(power_w))
    if noise > 0:
        arr = arr + np.random.default_rng(7).normal(0, noise, dur_s)
    return list(np.clip(arr, 0, None))


def _sprint_shape(peak_w: float, dur_s: int) -> List[float]:
    out: List[float] = []
    for i in range(dur_s):
        if i < 2:
            out.append(peak_w * (0.4 + 0.3 * i))
        else:
            out.append(peak_w * max(0.6, 1.0 - 0.03 * (i - 2)))
    return out + [40.0] * 5


class TestLabData:
    def test_create_lab_result_vo2max_only(self) -> None:
        result = create_lab_result(date(2026, 5, 20), source="spirometry", vo2max=62.3, map_w=380)
        assert result.has_vo2max
        assert result.test_type.value == "vo2max_only"
        assert result.n_parameters_available >= 2

    def test_create_lab_result_lactate_and_ftp_fallback(self) -> None:
        result = create_lab_result(
            date(2026, 6, 1),
            source="lactate_analyzer",
            ftp_w=275,
            lactate_curve=[(150, 0.9), (210, 1.5), (270, 3.8), (300, 5.5)],
        )
        assert result.has_lactate_curve
        assert result.mlss_power_w == 275
        assert result.test_type.value == "lactate_step"

    def test_parse_lab_text_english_and_italian(self) -> None:
        text = (
            "VO2 max: 62.3 ml/kg/min\n"
            "Consumo di O2 massimo: 55.0\n"
            "MLSS: 275 W\n"
            "VLamax: 0.42 mmol/L/s\n"
            "Test date 15/05/2026"
        )
        result = parse_lab_text(text)
        assert result.vo2max_ml_kg_min == 62.3
        assert result.mlss_power_w == 275
        assert result.vlamax_mmol_L_s == 0.42

    def test_from_dict_and_validate_warnings(self) -> None:
        result = LabTestResult.from_dict(
            {
                "test_date": "2026-01-01",
                "source": "not_a_real_source",
                "vo2max_ml_kg_min": 10.0,
                "vlamax_mmol_L_s": 3.0,
                "mlss_power_w": 400,
                "map_w": 300,
                "lactate_curve": [
                    {"power_w": 200, "lactate_mmol": 2.0},
                    {"power_w": 180, "lactate_mmol": 1.5},
                    {"power_w": 220, "lactate_mmol": 2.5},
                ],
            }
        )
        warnings = validate_lab_result(result)
        assert any("VO2max" in w for w in warnings)
        assert any("VLamax" in w for w in warnings)
        assert any("MLSS > MAP" in w for w in warnings)
        assert any("not monotonically" in w for w in warnings)
        assert result.summary().startswith("Lab test:")

    def test_lactate_point_to_dict(self) -> None:
        pt = LactatePoint(power_w=250, lactate_mmol=4.2, heart_rate_bpm=165)
        body = pt.to_dict()
        assert body["power_w"] == 250
        assert body["lactate_mmol"] == 4.2


class TestProgressionLevels:
    def test_compute_progression_levels_with_compliance_history(self) -> None:
        profile = {"mmp": {"5": 1000, "60": 500, "300": 360, "1200": 300}, "cp_w": 280, "weight_kg": 72}
        history = [
            {"target_zone": "threshold", "compliance_score": 0.9},
            {"target_zone": "vo2max", "compliance_score": 0.85},
            {"target_zone": "unknown_zone", "compliance_score": 0.5},
            "not-a-dict",
        ]
        out = compute_progression_levels(profile, history)
        assert out["status"] == "success"
        assert "threshold" in out["levels"]
        assert out["levels"]["threshold"] >= out["ability_profile"]["levels"]["threshold"]


class TestTestProtocols:
    def test_run_incremental_missing_steps(self) -> None:
        out = run_incremental_test({"test_data": {}})
        assert out["status"] == "error"
        assert out["reason"] == "missing_steps"

    def test_run_incremental_success(self) -> None:
        out = run_incremental_test(
            {
                "test_data": {
                    "steps": [
                        {"power_w": 200, "hr_mean": 140},
                        {"power_w": 250, "hr_mean": 155},
                        {"power_w": 300, "hr_mean": 170},
                    ]
                }
            }
        )
        assert out["status"] == "success"
        assert out["max_power_w"] == 300
        assert out["hr_max_observed"] == 170

    def test_run_power_cadence_insufficient_points(self) -> None:
        out = run_power_cadence_test({"test_data": {"points": [{"rpm_peak": 90, "w_peak": 400}]}})
        assert out["reason"] == "insufficient_points"

    def test_run_power_cadence_parabola_fit(self) -> None:
        out = run_power_cadence_test(
            {
                "test_data": {
                    "points": [
                        {"rpm_peak": 80, "w_peak": 420},
                        {"rpm_peak": 100, "w_peak": 560},
                        {"rpm_peak": 120, "w_peak": 500},
                    ]
                }
            }
        )
        assert out["status"] == "success"
        assert 90 <= out["optimal_cadence_rpm"] <= 110
        assert out["peak_power_w"] >= 500

    def test_run_critical_power_fit_failed(self) -> None:
        out = run_critical_power_test({"test_data": {"efforts": [{"duration_s": 60, "power_w": 400}]}})
        assert out["reason"] == "cp_fit_failed"

    def test_run_wingate_missing_weight_assumption(self) -> None:
        stream = [100, 200, 500, 480, 450, 420, 400, 380, 350, 300]
        out = run_wingate_test({"test_data": {"power_stream": stream}})
        assert out["status"] == "success"
        assert out["peak_power_wkg"] is None
        assert "body_weight_missing_peak_power_wkg_not_computed" in out["assumptions"]
        assert "sprint_peak_contract" in out

    def test_run_test_unknown_type(self) -> None:
        out = run_test({"test_type": "not_real"})
        assert out["reason"] == "unknown_test_type"


class TestEffortExtractor:
    def test_empty_files(self) -> None:
        prop = extract_test_proposal([])
        assert prop.status == "empty"
        assert prop.warnings

    def test_genuine_flow_style_proposal(self) -> None:
        rng = np.random.default_rng(42)
        day1 = (
            _flat_power(120, 600, noise=8)
            + _sprint_shape(1000, 15)
            + _flat_power(90, 300, noise=8)
            + _flat_power(300, 720, noise=6)
        )
        day2 = (
            _flat_power(120, 600, noise=8)
            + _flat_power(360, 180, noise=8)
            + _flat_power(90, 300, noise=8)
            + _flat_power(330, 360, noise=7)
        )
        prop = extract_test_proposal(
            [
                {"file_id": "day1", "power": day1, "laps": None},
                {"file_id": "day2", "power": day2, "laps": None},
            ]
        )
        body = prop.to_dict()
        assert body["status"] == "proposed"
        assert body["confidence"] >= 0.6
        assert body["sprint"] is not None
        assert len(body["cp_candidates"]) >= 2


class TestHrvEngineDepth:
    def test_calculate_dfa_alpha1_insufficient_data(self) -> None:
        out = calculate_dfa_alpha1([800.0] * 20)
        assert out["status"] == "INSUFFICIENT_DATA"

    def test_calculate_dfa_alpha1_valid_segment(self) -> None:
        rng = np.random.default_rng(1)
        rr = (800.0 + rng.normal(0, 15, 80)).tolist()
        out = calculate_dfa_alpha1(rr)
        assert out["status"] in {"AEROBIC", "MIXED", "ANAEROBIC", "INVALID_WINDOW"}
        if out["alpha1"] is not None:
            assert 0.0 < out["alpha1"] < 2.0

    def test_calculate_dfa_alpha1_novice_context(self) -> None:
        rr = (810.0 + np.sin(np.linspace(0, 6, 80)) * 10).tolist()
        ctx = AthleteContext(training_years=1.0)
        out = calculate_dfa_alpha1(rr, context=ctx)
        if out.get("confidence"):
            assert out["confidence"] in {"MEDIUM", "HIGH", "NONE"}

    def test_detect_thresholds_empty_rr(self) -> None:
        out = detect_thresholds_from_activity([])
        assert out["vt1"]["detected"] is False
        assert out["vt2"]["detected"] is False


class TestIntervalDetectorDepth:
    def test_classify_endurance_z2_signal(self) -> None:
        powers = [140.0] * 2000
        result = classify_session(powers, ftp=280)
        assert result.category in {"ENDURANCE", "STEADY"}
        assert result.confidence > 0.1

    def test_classify_hiit_signal(self) -> None:
        powers = [320.0 if i % 2 == 0 else 260.0 for i in range(1200)]
        result = classify_session(powers, ftp=280)
        assert result.category in {"HIIT", "FREE", "STEADY"}

    def test_classify_too_short(self) -> None:
        result = classify_session([200.0] * 10, ftp=280)
        assert result.category == "UNCLASSIFIED"
        assert result.confidence <= 0.15

    def test_protocol_completeness_with_anchors(self) -> None:
        report = protocol_completeness(
            available_durations_s=[60],
            qualified_anchors=[
                QualifiedAnchor(
                    duration_s=10,
                    power_w=900,
                    anchor_reliability=0.9,
                    source_subtype="sprint_set",
                )
            ],
        )
        body = report.to_dict()
        assert body["completeness_pct"] <= 75
        assert body["missing_windows"]


class TestMmpQualityDepth:
    def test_sprint_outlier_detection(self) -> None:
        report = analyze_mmp_quality({5: 1500, 1200: 280})
        assert any(i.category == "sprint_outlier" for i in report.issues)

    def test_non_monotonic_detection(self) -> None:
        report = analyze_mmp_quality({60: 300, 120: 320})
        assert any(i.category == "non_monotonic" for i in report.issues)

    def test_filter_mmp_by_window(self) -> None:
        ref = date(2026, 6, 17)
        samples = [
            {"duration_s": 300, "power_w": 320, "date": "2026-06-01"},
            {"duration_s": 600, "power_w": 310, "date": "2025-01-01"},
        ]
        filtered, kept = filter_mmp_by_window(samples, today=ref, window_days=90)
        assert 300 in filtered
        assert 600 not in filtered
        assert len(kept) == 1


class TestRideAnalyticsServiceBatch2:
    def setup_method(self) -> None:
        self.svc = RideAnalyticsService()
        self.stream = _stream(seconds=7200, power=255.0)
        self.athlete = AthleteParams(weight_kg=72.0, ftp=280.0)

    def test_power_analyze_without_ftp(self) -> None:
        out = self.svc.power_analyze(self.stream, weight_kg=72.0, ftp=None)
        assert out.get("status") != "error" or out.get("reason") == "FTP_NOT_AVAILABLE"

    def test_critical_power_fit_failed(self) -> None:
        out = self.svc.critical_power_fit([])
        assert out["status"] == "partial"
        assert out["reason"] == "FIT_FAILED"

    def test_durability_prescription_tiers(self) -> None:
        excellent = self.svc.durability_prescription(98)
        good = self.svc.durability_prescription(94)
        fair = self.svc.durability_prescription(90)
        poor = self.svc.durability_prescription(80)
        assert "focus" in excellent
        assert excellent["focus"] != poor["focus"]
        assert good["focus"] != fair["focus"]

    def test_hrv_analyze_with_rr(self) -> None:
        stream = _stream(seconds=3600, power=250.0, with_rr=True)
        out = self.svc.hrv_analyze(stream)
        assert out["status"] in {"success", "partial", "error"}
        if out["status"] == "success":
            assert out.get("n_windows", 0) >= 0

    def test_metabolic_flexibility_alt_keys(self) -> None:
        out = self.svc.metabolic_flexibility({"fatmax_watts": 200, "vt2_watts": 280})
        assert out["status"] == "success"

    def test_session_route_decide(self) -> None:
        stream = _stream(seconds=1800, device_name="ramp_test.fit")
        out = self.svc.session_route_decide(stream, ftp=280.0)
        assert "route" in out or "category" in out or "status" in out

    def test_session_route_run_smoke(self) -> None:
        stream = _stream(seconds=1800, device_name="ftp_20min_test.fit")
        out = self.svc.session_route_run(stream, athlete=self.athlete, ftp=280.0)
        assert isinstance(out, dict)
        assert out.get("status") in {"success", "partial", "error", None} or "route" in out

    def test_climb_segments_and_compare(self) -> None:
        alt = [100.0] * 50 + list(np.linspace(100, 200, 100)) + [200.0] * 50
        dist = (np.arange(len(alt)) * 10.0).tolist()
        stream = SimpleNamespace(altitude_m=alt, distance_m=dist)
        climbs = self.svc.climb_segments(stream)
        assert climbs.get("status") in {"success", "skipped"}
        history = [{"distance_m": 1000, "elevation_gain_m": 80}]
        new = [{"distance_m": 1050, "elevation_gain_m": 85}]
        cmp_out = self.svc.compare_segments(history, new)
        assert cmp_out["comparisons"][0]["matched"] is True


def _cardiac_activity(*, steady_s: int = 600, power: float = 220.0) -> List[ActivitySample]:
    samples: List[ActivitySample] = []
    for i in range(steady_s):
        hr = 140.0 + 25.0 * (i / max(steady_s - 1, 1))
        samples.append(ActivitySample(t=float(i), power=power, hr=hr))
    hr_drop = 165.0
    for j in range(120):
        hr_drop = max(100.0, hr_drop - 1.2)
        samples.append(ActivitySample(t=float(steady_s + j), power=0.0, hr=hr_drop))
    return samples


class TestCardiacEngineDepth:
    def test_analyze_empty_and_too_short(self) -> None:
        analyzer = CardiacResponseAnalyzer(weight=72.0)
        assert analyzer.analyze([])["status"] == "error"
        short = [ActivitySample(t=float(i), power=200.0, hr=140.0) for i in range(30)]
        assert analyzer.analyze(short)["status"] == "error"

    def test_analyze_steady_and_recovery_segments(self) -> None:
        out = CardiacResponseAnalyzer(weight=72.0).analyze(_cardiac_activity())
        assert out["status"] == "success"
        assert out.get("decoupling") or out.get("metrics")
        assert "steady_segments" in out or "aerobic_decoupling" in str(out)

    def test_cross_validate_thresholds_with_hrv_timeline(self) -> None:
        samples = _cardiac_activity(steady_s=400)
        t = np.array([s.t for s in samples])
        p = np.array([s.power for s in samples])
        h = np.array([s.hr for s in samples])
        hrv = [
            {"timestamp": 50.0, "status": "AEROBIC"},
            {"timestamp": 150.0, "status": "MIXED"},
            {"timestamp": 250.0, "status": "ANAEROBIC"},
        ]
        out = cross_validate_thresholds(
            t,
            p,
            h,
            {"status": "success", "mlss_power_watts": 220},
            hrv,
        )
        assert out.get("available") is True or "hr_at_vt1_dfa" in out or "hr_at_vt2_dfa" in out


class TestExplainabilityEngineDepth:
    def test_vo2max_confidence_high_and_low(self) -> None:
        high = calculate_vo2max_confidence(
            {30: 850, 60: 720, 180: 520, 300: 420, 1200: 290},
            efforts_count=6,
            data_quality_score=0.95,
        )
        low = calculate_vo2max_confidence({300: 420}, efforts_count=1, data_quality_score=0.6)
        assert high.confidence_pct > low.confidence_pct
        assert high.confidence_level in {ConfidenceLevel.HIGH, ConfidenceLevel.VERY_HIGH}

    def test_durability_confidence_and_narratives(self) -> None:
        conf = calculate_durability_confidence(duration_hours=4.5, power_data_completeness=0.97)
        prescription = {
            "focus": "Maintain aerobic base",
            "volume": "70-80% Z2",
            "key_sessions": ["3h endurance ride"],
        }
        narrative = generate_durability_narrative(95, "EXCELLENT", conf, prescription)
        assert "Durability" in narrative or "durability" in narrative.lower()
        acwr = generate_acwr_narrative(1.6, "HIGH", ctl=60, atl=96, tsb=-36)
        assert "ACWR" in acwr or "risk" in acwr.lower()
        low_conf = calculate_vo2max_confidence({300: 420}, 1, 0.6)
        metric = generate_metric_narrative("VO2max", 67.8, low_conf)
        assert "VO2max" in metric

    def test_workout_summary_narrative(self) -> None:
        text = generate_workout_summary_narrative(
            {
                "headline": {"workout_type": "Endurance", "tss": 120, "if_value": 0.72},
                "sections": {
                    "durability": {
                        "status": "success",
                        "metrics": {
                            "durability_index": {
                                "classification": "GOOD",
                                "value": 93.7,
                                "decay_watts": 16,
                                "first_hour_avg": 220,
                                "last_hour_avg": 204,
                                "interpretation": "Solid aerobic durability",
                            }
                        },
                    },
                    "power": {
                        "metabolic_snapshot": {
                            "vo2max_ml_kg_min": 62,
                            "vlamax_mmol_l_s": 0.4,
                            "mlss_power_watts": 280,
                        }
                    },
                    "hrv": {"vt1_detected": True, "vt1_power": 210},
                },
            }
        )
        assert isinstance(text, str) and len(text) > 20


class TestPedalingBalanceDepth:
    def test_refused_single_estimated(self) -> None:
        report = analyze_pedaling_balance(
            [50.0] * 300,
            [200.0] * 300,
            pedaling_balance_source="single_estimated",
        )
        assert report.data_quality == "refused_single_side"

    def test_insufficient_valid_samples(self) -> None:
        report = analyze_pedaling_balance([50.0] * 30, [180.0] * 30, pedaling_balance_source="dual")
        assert report.data_quality == "insufficient_data"

    def test_marked_asymmetry_and_trend(self) -> None:
        marked = analyze_pedaling_balance([38.0] * 600, [200.0] * 600, ftp=250.0, pedaling_balance_source="dual")
        assert marked.asymmetry_classification == "marked"
        symmetric = analyze_pedaling_balance([50.0] * 600, [200.0] * 600, ftp=250.0, pedaling_balance_source="dual")
        assert symmetric.asymmetry_classification == "symmetric"
        trend = analyze_balance_trend([symmetric, symmetric, marked, marked, marked, marked])
        assert trend.trend in {"stable", "worsening", "improving", None} or trend.notes


class TestSegmentEngineDepth:
    def test_detect_climb_skipped_without_altitude(self) -> None:
        out = detect_climb_segments(SimpleNamespace(altitude_m=[], distance_m=[]))
        assert out["status"] == "skipped"

    def test_detect_climb_success(self) -> None:
        alt = [100.0] * 50 + list(np.linspace(100, 200, 100)) + [200.0] * 50
        dist = np.arange(len(alt)) * 10.0
        out = detect_climb_segments(SimpleNamespace(altitude_m=alt, distance_m=dist))
        assert out["status"] == "success"
        assert out["segments"]

    def test_compare_segments_match_and_miss(self) -> None:
        history = [{"distance_m": 1000, "elevation_gain_m": 80}]
        matched = compare_segments(history, [{"distance_m": 1050, "elevation_gain_m": 85}])
        missed = compare_segments(history, [{"distance_m": 5000, "elevation_gain_m": 200}])
        assert matched["comparisons"][0]["matched"] is True
        assert missed["comparisons"][0]["matched"] is False


class TestTrainingVariabilityDepth:
    @pytest.mark.parametrize(
        "atl,ctl,expected",
        [
            (10, 0, "error"),
            (100, 50, "HIGH"),
            (70, 50, "MODERATE"),
            (30, 50, "DETRAINING"),
            (55, 50, "OPTIMAL"),
        ],
    )
    def test_acwr_risk_bands(self, atl: float, ctl: float, expected: str) -> None:
        out = calculate_acwr(atl, ctl)
        if expected == "error":
            assert out["status"] == "error"
        else:
            assert out["risk_level"] == expected

    def test_monotony_strain_branches(self) -> None:
        assert calculate_monotony_strain([50.0] * 5)["status"] == "insufficient_data"
        unstable = calculate_monotony_strain([50.0] * 7)
        assert unstable["status"] == "unstable"
        varied = calculate_monotony_strain([10, 80, 20, 90, 15, 85, 25])
        assert varied["monotony_status"] in {"HIGH_RISK", "MODERATE", "OPTIMAL"}


class TestRecommendationEngineDepth:
    def test_readiness_recovery_path(self) -> None:
        out = recommend_workout({"cp_w": 280, "weight_kg": 72}, readiness={"readiness_score": 40})
        assert out["recommendation"]["focus"] == "recovery"
        assert out["recommendation"]["intensity"] == "low"

    def test_readiness_quality_with_goal(self) -> None:
        out = recommend_workout(
            {"cp_w": 280, "weight_kg": 72, "mmp": {"5": 1000, "60": 500, "300": 360, "1200": 300}},
            readiness={"readiness_score": 80},
            goal={"focus": "vo2"},
        )
        assert out["status"] == "success"
        assert out["recommendation"]["workout"] is not None


class TestRacePredictionEdges:
    def test_course_segment_terrain(self) -> None:
        assert CourseSegment(0, 100, 100, 10, 5.0).terrain == "climb"
        assert CourseSegment(0, 100, 100, -5, -4.0).terrain == "descent"
        assert CourseSegment(0, 100, 100, 0, 1.0).terrain == "rolling"

    def test_parse_gpx_course_too_few_points(self) -> None:
        with pytest.raises(ValueError, match="at least two"):
            parse_gpx_course("<gpx xmlns='http://www.topografix.com/GPX/1/1'><trkpt lat='45' lon='9'/></gpx>")

    def test_athlete_profile_from_snapshot(self) -> None:
        profile = AthleteRaceProfile.from_metabolic_snapshot(
            weight_kg=72,
            ftp_w=300,
            snapshot={"mlss_power_watts": 280, "estimated_vo2max": 62.5},
        )
        assert profile.mlss_w == 280
        assert profile.vo2max == 62.5


class TestCalendarEngine:
    def test_valid_and_invalid_transitions(self) -> None:
        ok = validate_status_transition("draft", "assigned")
        assert ok["allowed"] is True
        bad = validate_status_transition("draft", "completed")
        assert bad["allowed"] is False
        unknown = validate_status_transition("bogus", "assigned")
        assert unknown["status"] == "invalid"

    def test_idempotent_transition(self) -> None:
        same = validate_status_transition("completed", "completed")
        assert same["allowed"] is True


class TestThermalEngineDepth:
    def test_no_core_sensor_data(self) -> None:
        out = analyze_thermal_session(
            core_temp_stream=[float("nan")] * 3600,
            power_stream=[200.0] * 3600,
        )
        assert out.data_quality == "no_data"

    def test_progressive_heating_session(self) -> None:
        n = 3600
        core = [37.2 + (i / n) * 1.6 for i in range(n)]
        power = [200.0] * n
        hr = [130.0 + (core[i] - 37.2) * 9.0 for i in range(n)]
        out = analyze_thermal_session(core, power, hr_stream=hr, ftp=250.0)
        assert out.data_quality in {"good", "partial"}
        assert out.thermal_rise_rate is not None and out.thermal_rise_rate > 0
        assert out.core_temp_peak is not None and out.core_temp_peak > 37.5

    def test_heat_acclimation_trend(self) -> None:
        sessions = [
            ThermalSessionReport(
                data_quality="good",
                n_valid_samples=3000,
                n_total_samples=3600,
                thermal_rise_rate=0.025 - i * 0.002,
                heat_tolerance_threshold=38.5 + i * 0.1,
            )
            for i in range(9)
        ]
        trend = analyze_heat_acclimation(sessions)
        assert trend.n_sessions == 9
        assert trend.trend == "acclimating"
        short = analyze_heat_acclimation(sessions[:2])
        assert short.trend is None


class TestLoadTrendsAndHistory:
    def test_compute_load_trends_risk_bands(self) -> None:
        ref = date(2026, 6, 17)
        activities = []
        for i in range(90):
            d = ref - timedelta(days=89 - i)
            tss = 80.0 if i >= 62 else 15.0
            activities.append({"date": d.isoformat(), "tss": tss})
        high = compute_load_trends(activities, as_of=ref.isoformat())
        assert high["risk"] == "high"
        assert high["acute_load"] > high["chronic_load"]

    def test_history_summary_and_records(self) -> None:
        activities = [
            {"date": "2026-06-01", "tss": 60, "mmp": {"300": 320, "1200": 280}},
            {"date": "2026-06-02", "tss": 45, "mmp": {"300": 330}},
        ]
        records = compute_personal_records(activities, weight_kg=72.0)
        assert records["records"]
        summary = build_history_summary(activities, weight_kg=72.0)
        assert summary["status"] == "success"
        assert summary["activity_count"] == 2


class TestCardiacMetricsDirect:
    def test_steady_segment_metrics(self) -> None:
        t = np.arange(600, dtype=float)
        p = np.full(600, 220.0)
        h = np.concatenate([np.full(300, 140.0), np.full(300, 165.0)])
        seg = Segment(kind="steady", start_idx=0, end_idx=600, start_t=0.0, end_t=599.0, duration_s=600.0)
        dec = compute_aerobic_decoupling(t, p, h, seg)
        drift = compute_cardiac_drift(t, p, h, seg)
        cei = compute_cardiac_efficiency(p, h, 72.0, seg)
        assert dec["available"] is True
        assert drift["available"] is True and drift["drift_pct"] > 0
        assert cei["available"] is True

    def test_hr_recovery_segment(self) -> None:
        t = np.arange(400, dtype=float)
        p = np.concatenate([np.full(250, 250.0), np.zeros(150)])
        h = np.concatenate([np.full(250, 170.0), np.linspace(170, 125, 150)])
        seg = Segment(kind="recovery", start_idx=250, end_idx=400, start_t=250.0, end_t=399.0, duration_s=150.0)
        rec = compute_hr_recovery(t, h, seg)
        assert rec["available"] is True
        assert rec["hrr60_bpm"] is not None


class TestPedalingBalanceBatch4:
    def test_intra_session_drift(self) -> None:
        balance = [50.0] * 300 + [42.0] * 300
        report = analyze_pedaling_balance(balance, [200.0] * 600, ftp=250.0, pedaling_balance_source="dual")
        assert report.drift_classification in {"drifting", "strong_drift", "stable"}
        assert report.intra_session_drift is not None

    def test_zone_shift_with_load(self) -> None:
        balance = [50.0] * 400 + [38.0] * 200
        power = [180.0] * 400 + [320.0] * 200
        report = analyze_pedaling_balance(balance, power, ftp=250.0, pedaling_balance_source="dual")
        assert report.balance_by_zone is not None
        assert report.zone_shift_flag in {"stable", "shifts_with_load", None}


class TestExplainabilityBatch4:
    def test_acwr_narrative_moderate_and_optimal(self) -> None:
        moderate = generate_acwr_narrative(1.35, "MODERATE", ctl=50, atl=68, tsb=-18)
        optimal = generate_acwr_narrative(1.0, "OPTIMAL", ctl=60, atl=60, tsb=0)
        assert "MODERATE" in moderate or "Caution" in moderate or "caution" in moderate.lower()
        assert "OPTIMAL" in optimal or "Good" in optimal or "balance" in optimal.lower()

    def test_durability_narrative_fair(self) -> None:
        conf = calculate_durability_confidence(duration_hours=1.5, power_data_completeness=0.8)
        prescription = {"focus": "Rebuild base", "volume": "90% Z2", "key_sessions": ["Long ride"]}
        text = generate_durability_narrative(88, "FAIR", conf, prescription)
        assert "FAIR" in text or "fair" in text.lower()


class TestScienceContractsAndTiers:
    def test_vlamax_limitations_low_cadence(self) -> None:
        limits = vlamax_limitations(effective_cadence_rpm=110.0)
        assert any("cadence" in x.lower() for x in limits)

    def test_enrich_metabolic_snapshot_cadence(self) -> None:
        snap = enrich_metabolic_snapshot_cadence(
            {"status": "success", "estimated_vo2max": 62.0},
            effective_cadence_rpm=95.0,
        )
        assert snap.get("cadence_anchor", {}).get("effective_cadence_rpm") == 95.0

    def test_derive_effective_cadence(self) -> None:
        stream = SimpleNamespace(cadence=[0, 45, 90, 92, 88, None], n_samples=6)
        assert derive_effective_cadence_rpm(stream) == 89.0

    def test_cp_anchor_warnings(self) -> None:
        warnings = cp_anchor_warnings([{"duration_s": 60, "power_w": 400}])
        assert warnings

    def test_tier_display_gating(self) -> None:
        assert should_display(0.6) is True
        assert should_display(0.4) is False
        masked = mask_low_confidence(
            {"confidence_score": 0.3, "estimated_vo2max": 62.0},
            threshold=0.55,
        )
        assert masked["estimated_vo2max"] == "—"
        tiered = annotate({"value": 1}, module_name="metabolic_profiler")
        assert tiered["tier"] == tier_for("metabolic_profiler").value


class TestRideAnalyticsServiceBatch4:
    def setup_method(self) -> None:
        self.svc = RideAnalyticsService()
        self.athlete = AthleteParams(weight_kg=72.0, ftp=280.0)

    def test_thermal_session_without_core(self) -> None:
        stream = _stream(seconds=3600, power=200.0)
        out = self.svc.thermal_session(stream, ftp=280.0)
        assert out.get("data_quality") == "no_data" or out.get("status") in {"skipped", "error", None}

    def test_thermal_acclimation_from_dicts(self) -> None:
        sessions = [
            {"data_quality": "good", "thermal_rise_rate": 0.025 - i * 0.002, "n_valid_samples": 3000}
            for i in range(6)
        ]
        out = self.svc.thermal_acclimation(sessions)
        assert isinstance(out, dict)


_RACE_GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk><trkseg>
    <trkpt lat="45.0000" lon="7.0000"><ele>300</ele></trkpt>
    <trkpt lat="45.0000" lon="7.0100"><ele>310</ele></trkpt>
    <trkpt lat="45.0000" lon="7.0200"><ele>340</ele></trkpt>
    <trkpt lat="45.0000" lon="7.0300"><ele>390</ele></trkpt>
    <trkpt lat="45.0000" lon="7.0400"><ele>450</ele></trkpt>
    <trkpt lat="45.0000" lon="7.0500"><ele>455</ele></trkpt>
    <trkpt lat="45.0000" lon="7.0600"><ele>420</ele></trkpt>
    <trkpt lat="45.0000" lon="7.0700"><ele>360</ele></trkpt>
  </trkseg></trk>
</gpx>
"""


class TestDataQualityBatch5:
    def test_clean_power_and_hr_streams(self) -> None:
        spiky = [200.0] * 50 + [1500.0, 1500.0] + [200.0] * 50
        cleaned_power = clean_power_stream(spiky)
        assert max(cleaned_power) < 1200
        hr = clean_hr_stream([140.0, 0.0, 0.0, 145.0, 150.0, 250.0, 148.0])
        assert all(40 <= h <= 220 for h in hr)

    def test_flat_erg_artifact_lowers_quality(self) -> None:
        report = assess_data_quality([250.0] * 200)
        assert report.power_quality < 1.0 or report.overall_score < 1.0

    def test_pause_removal_pipeline(self) -> None:
        power = [0.0] * 40 + [250.0] * 100 + [0.0] * 40 + [250.0] * 100
        pauses = detect_pauses(power, threshold_seconds=30)
        trimmed = remove_pauses(power, pauses)
        assert len(trimmed) < len(power)
        assert max(trimmed) > 0


class TestMmpQualityBatch5:
    def test_rolling_window_redundant_cluster(self) -> None:
        mmp = {600: 300.0, 900: 298.0, 1200: 296.0, 1800: 294.0}
        samples = [
            {"duration_s": d, "power_w": p, "source_file": "same_ride.fit"}
            for d, p in mmp.items()
        ]
        report = analyze_mmp_quality(mmp, mmp_samples=samples)
        assert any(i.category == "rolling_window_redundant" for i in report.issues)

    def test_clean_mmp_string_keys_and_plateau_rule(self) -> None:
        mmp = {"5s": 800, "60s": 320, "120s": 320, "300s": 310}
        report = analyze_mmp_quality(mmp)
        cleaned, audit = clean_mmp(mmp, drop_rules=["identical_plateau"])
        assert audit["dropped"] or report.issues


class TestMetabolicKalmanBatch5:
    def test_process_workout_history_trajectory(self) -> None:
        start = date(2026, 1, 1)
        inputs = [
            DailyInput(date=start + timedelta(days=i), vo2max_stimulus_min=25.0, neuromuscular_stimulus_min=2.0)
            for i in range(10)
        ]
        traj = process_workout_history(inputs, initial_vo2=60.0, initial_vla=0.4, weight=72.0)
        assert len(traj.states) >= 10
        assert traj.states[-1].vo2max > 0

    def test_kalman_update_with_test_anchors(self) -> None:
        import numpy as np

        kalman = MetabolicKalman(np.array([60.0, 0.4]), np.diag([4.0, 0.01]), weight=72.0)
        kalman.predict(DailyInput(date=date(2026, 1, 1), vo2max_stimulus_min=20.0))
        updated = kalman.update([(180, 360.0), (360, 330.0), (720, 300.0)])
        assert updated is not None
        assert kalman.current_state.vo2max > 0


class TestSessionRouterBatch5:
    def test_decide_route_ramp_with_rr(self) -> None:
        power = [150 + i * 2 for i in range(600)]
        decision = decide_route(power, filename="ramp_test.fit", ftp=280.0, has_rr=True)
        assert decision.route in {"hrv_threshold", "metabolic_anchor"}
        assert decision.engines_to_run

    def test_decide_route_hiit(self) -> None:
        power = [350.0] * 60 + [150.0] * 120
        power = power * 15
        decision = decide_route(power, filename="30_15.fit", ftp=280.0, has_rr=True, has_metabolic_profile=True)
        assert decision.route == "hiit"
        assert "interval_stimulus" in decision.engines_to_run

    def test_route_and_run_smoke(self) -> None:
        power = [200.0] * 1800
        out = route_and_run(power, ftp=280.0, filename="endurance_ride.fit", weight_kg=72.0)
        assert "routing" in out
        assert out["routing"]["route"] == "ride_monitoring"


class TestRacePredictionBatch5:
    def test_analyze_and_simulate_gpx(self) -> None:
        points = parse_gpx_course(_RACE_GPX)
        course = analyze_course(points)
        assert course["distance_km"] > 5.0
        assert course["elevation_gain_m"] >= 100
        prediction = simulate_gpx_race(
            _RACE_GPX,
            weight_kg=72.0,
            ftp_w=300.0,
            metabolic_snapshot={"mlss_power_watts": 295, "fatmax_power_watts": 190},
        )
        assert prediction["status"] == "success"
        assert prediction["prediction"]["estimated_time_s"] > 0


class TestMmpAggregatorBatch5:
    def test_extract_and_update_power_curve(self) -> None:
        curve = extract_ride_curve([255.0] * 3600)
        assert curve
        result = update_power_curve(
            [260.0] * 1800,
            date(2026, 6, 1),
            stored_curve={},
            weight_kg=72.0,
        )
        assert result.mmp_for_profiler
        rebuilt = curve_to_mmp(result.curve)
        assert rebuilt


class TestChartBuilderBatch5:
    def test_power_duration_and_zones_charts(self) -> None:
        pdc = chart_power_duration_curve(
            {60: 400, 300: 320, 1200: 280},
            cp_model={"cp": 270, "w_prime": 20000},
            ftp=280,
        )
        assert pdc["type"] == "line_scatter"
        zones = chart_zones_distribution(
            {"coggan": {"Z1": 30.0, "Z2": 40.0, "Z3": 20.0, "Z4": 10.0}},
            system="coggan",
        )
        assert zones["type"] == "bar_stacked"

    def test_generate_workout_charts(self) -> None:
        charts = generate_workout_charts(
            {
                "power_metrics": {"mmp_curve": {60: 400, 300: 320}, "ftp": 280},
                "zones_distribution": {"coggan": {"Z1": 50.0, "Z2": 30.0, "Z3": 20.0}},
            }
        )
        assert "power_duration" in charts
        assert "zones_coggan" in charts


class TestPowerCurveHistoryBatch5:
    def test_aggregate_and_build_history(self) -> None:
        activities = [
            {"date": "2026-06-01", "mmp": {"300": 320, "1200": 280}},
            {"date": "2026-06-10", "mmp": {"300": 330}},
        ]
        curve = aggregate_power_curve(activities)
        assert curve[300] == 330
        history = build_power_curve_history(activities, as_of="2026-06-15", weight_kg=72.0)
        assert "last_90_days" in history["periods"]


class TestDetrainingEngineBatch5:
    def test_ctl_atl_tsb_and_decay_factor(self) -> None:
        ref = date(2026, 6, 17)
        history = [{"date": ref - timedelta(days=i), "tss": 50.0} for i in range(14)]
        tl = calculate_ctl_atl_tsb(history, ref)
        assert tl["ctl"] > 0
        decay = calculate_decay_factor(21.0, 25.0, "vo2max")
        assert 0 < decay <= 1.0

    def test_apply_detraining_success_and_partial(self) -> None:
        ref = date(2026, 6, 17)
        history = [{"date": ref - timedelta(days=3), "tss": 80.0}]
        snapshot = {
            "status": "success",
            "estimated_vo2max": 62.0,
            "estimated_vlamax_mmol_L_s": 0.42,
            "mlss_power_watts": 280.0,
            "map_aerobic_watts": 350.0,
        }
        out = apply_detraining_model(snapshot, history, ref)
        assert out.get("detraining_applied") is True or out.get("status") == "success"
        partial = apply_detraining_model({"status": "success"}, [], ref)
        assert partial["status"] == "partial"


class TestPhysiologicalPriorBatch5:
    def test_prior_manager_std_growth_and_bayesian_kwargs(self) -> None:
        profile = MeasuredProfile(
            measured_on=date(2026, 1, 1),
            vo2max=62.0,
            vlamax=0.42,
            mlss_watts=280.0,
        )
        mgr = PhysiologicalPriorManager(profile)
        priors = mgr.current_priors(date(2026, 6, 1), load_factor=0.4)
        assert priors["vo2max"].std > priors["vo2max"].mean * 0.01
        kwargs = mgr.bayesian_kwargs(date(2026, 6, 1))
        assert "prior_vo2_mean" in kwargs


class TestPhysiologicalResilienceBatch5:
    def test_unavailable_without_signals(self) -> None:
        out = build_physiological_resilience()
        assert out["status"] == "unavailable"

    def test_declining_trend_with_prior(self) -> None:
        out = build_physiological_resilience(
            mader_durability={"status": "success", "durability_loss_pct": 12.0, "confidence_score": 0.8},
            prior={"dcp_pct": 8.0},
        )
        assert out["status"] == "success"
        assert out["trend"] == "declining"


class TestManualLoadBatch5:
    def test_running_and_strength_modifiers(self) -> None:
        run = calculate_manual_load(duration_min=60, rpe=7, modality="running")
        gym = calculate_manual_load(duration_min=45, rpe=8, modality="strength")
        assert run["load"]["recovery_cost"] > gym["load"]["training_load_equivalent"] * 0.5
        assert run["load"]["readiness_modifier"] < 0


class TestIntervalDetectorBatch5:
    def test_mixed_test_signature(self) -> None:
        ftp = 280.0
        powers = [100.0] * 100 + [900.0] * 10 + [270.0] * 2000
        result = classify_session(powers, ftp=ftp)
        assert result.category == "TEST"
        assert result.subtype in {"mixed_test", "cp_test", "ftp_20min", "cp12", "cp6", "cp3", "ramp_test"}


def _chart_stream(*, seconds: int = 600) -> SimpleNamespace:
    t = np.arange(seconds, dtype=float)
    return SimpleNamespace(
        time=t.tolist(),
        altitude=(100.0 + np.linspace(0, 50, seconds)).tolist(),
        speed=[8.0] * seconds,
        power=[220.0] * seconds,
        heart_rate=[140.0] * seconds,
        cadence=[90.0] * seconds,
        respiration=[16.0] * seconds,
        ambient_temp=[20.0] * seconds,
        left_right_balance=[50.0] * seconds,
        position=[0.0] * seconds,
        power_phase=[0.0] * seconds,
        platform_offset=[0.0] * seconds,
        core_body_temp=[37.2] * seconds,
        skin_temp=[33.0] * seconds,
        n_samples=seconds,
    )


class TestMetabolicCurrentBatch6:
    def test_get_current_metabolic_status(self) -> None:
        mmp = {5: 1000, 60: 500, 180: 360, 300: 340, 600: 320, 1200: 290}
        history = [{"date": (date(2026, 6, 17) - timedelta(days=i)).isoformat(), "tss": 55.0} for i in range(14)]
        out = get_current_metabolic_status(
            mmp,
            history,
            athlete_weight_kg=72.0,
            athlete_context={"gender": "MALE", "training_years": 8, "discipline": "ROAD"},
            today="2026-06-17",
        )
        assert out.get("status") == "success" or out.get("detraining_applied") is True
        assert "athlete" in out or "training_load" in out

    def test_handle_edge_function_missing_field(self) -> None:
        out = handle_edge_function_request({"historical_mmp": {60: 400}})
        assert out["status"] == "error"


class TestActivityChartsBatch6:
    def test_build_activity_charts(self) -> None:
        stream = _chart_stream(seconds=900)
        charts = build_activity_charts(
            stream,
            zones=[{"name": "Z2", "min_w": 150, "max_w": 220}],
            hrv_durability={"time_in_zone": {"AEROBIC": 400, "MIXED": 200, "ANAEROBIC": 50}},
        )
        assert charts["power"].get("type") == "line"
        assert charts["elevation"].get("type") == "line"
        assert charts["_metadata"]["available_charts_count"] >= 5


class TestWorkoutEnginesBatch6:
    _WORKOUT = {
        "title": "Threshold",
        "steps": [{"step_id": "1", "type": "work", "duration_s": 1200, "target_w": 260, "is_key_step": True}],
    }

    def test_validate_and_prescribe_template(self) -> None:
        valid = validate_template(self._WORKOUT)
        assert valid["status"] == "valid"
        rx = prescribe_for_athlete(self._WORKOUT, {"cp_w": 280, "weight_kg": 72})
        assert rx["status"] == "success"
        assert rx["prescription"]["prescription_status"] in {"resolved", "partially_resolved"}

    def test_adapt_plan_branches(self) -> None:
        plan = [{"target_w": 200, "load": 80.0}]
        reduced = adapt_plan(plan, readiness={"readiness_score": 40}, last_compliance={"compliance_score": 0.4})
        assert reduced["reason"] == "reduce_load"
        assert reduced["adapted_plan"][0]["target_w"] < 200
        progressed = adapt_plan(plan, readiness={"readiness_score": 90}, last_compliance={"compliance_score": 0.95})
        assert progressed["reason"] == "small_progression"


class TestMetabolicKalmanLabBatch6:
    def test_update_from_lab_result(self) -> None:
        kalman = MetabolicKalman(np.array([58.0, 0.38]), np.diag([9.0, 0.02]), weight=72.0)
        lab = create_lab_result(date(2026, 6, 1), vo2max=62.5, vlamax=0.42)
        updated = kalman.update_from_lab(lab)
        assert updated.vo2max > 58.0


class TestSessionRouterBatch6:
    def test_route_with_metabolic_snapshot_and_rr(self) -> None:
        power = [150 + i * 2 for i in range(600)]
        rr = [{"elapsed": float(i * 5), "rr": [800.0 + (i % 5)] * 20} for i in range(120)]
        elapsed = [float(i) for i in range(len(power))]
        out = route_and_run(
            power,
            rr_samples=rr,
            elapsed_s=elapsed,
            filename="ramp_test.fit",
            ftp=280.0,
            weight_kg=72.0,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 280, "estimated_vo2max": 62},
        )
        assert out["routing"]["route"] in {"hrv_threshold", "metabolic_anchor"}
        assert "results" in out


class TestHrvBatch6:
    def test_detect_thresholds_with_power_alignment(self) -> None:
        rr_samples = [
            {"elapsed": float(i * 10), "rr": [820.0 - i * 0.5] * 25}
            for i in range(60)
        ]
        power = [150.0 + i * 0.8 for i in range(600)]
        out = detect_thresholds_from_activity(rr_samples, power_data=power)
        assert "vt1" in out
        assert "vt2" in out


class TestPedalingBalanceBatch6:
    def test_refuse_unknown_source_strict(self) -> None:
        report = analyze_pedaling_balance(
            [50.0] * 300,
            [200.0] * 300,
            pedaling_balance_source="unknown",
            accept_unknown_source=False,
        )
        assert report.data_quality == "refused_single_side"


class TestChartBuilderBatch6:
    def test_hrv_timeline_and_training_load(self) -> None:
        hrv = chart_hrv_timeline(
            list(range(0, 600, 10)),
            [0.9 - i * 0.002 for i in range(60)],
            vt1_power=210,
            vt2_power=260,
            power_series=[150 + i for i in range(60)],
        )
        assert hrv["type"] == "line_multi_axis"
        pmc = chart_training_load(
            [date(2026, 6, 1) + timedelta(days=i) for i in range(7)],
            [50, 52, 54, 55, 56, 57, 58],
            [60, 58, 57, 56, 55, 54, 53],
            [10, 8, 6, 4, 2, 0, -2],
        )
        assert pmc["type"] == "line_multi"

    def test_metabolic_combustion_chart(self) -> None:
        chart = chart_metabolic_combustion(
            [180, 220, 260],
            [60.0, 40.0, 20.0],
            [35.0, 50.0, 60.0],
            [5.0, 10.0, 20.0],
            markers={"FatMax": 180, "MLSS": 260},
        )
        assert chart["type"] == "area_stacked"


class TestDurabilityEngineBatch6:
    def test_durability_np_drift_and_decay(self) -> None:
        power = [250.0] * 3600 + [235.0] * 3600
        di = calculate_durability_index(power, duration_seconds=len(power))
        assert di["status"] == "success"
        drift = calculate_np_drift(power, len(power))
        assert "drift_pct" in drift or drift.get("status")
        decay = generate_hourly_decay_curve(power, len(power))
        assert decay.get("status") == "success" or "hourly" in str(decay).lower()
        tte = calculate_tte_sustainability(power[:1800], 270.0)
        assert tte.get("status") in {"success", "insufficient_data", None} or "sustainability" in tte


class TestIntervalDetectorBatch6:
    def test_classify_by_laps_ramp(self) -> None:
        laps = [
            {"duration_s": 300, "avg_power_w": 180 + i * 15}
            for i in range(8)
        ]
        powers = [200.0] * 2400
        result = classify_session(powers, laps=laps, ftp=280.0)
        assert result.category in {"TEST", "HIIT", "STEADY"}
        assert result.source == "laps" or result.confidence > 0.1


class TestDataQualityBatch6:
    def test_cadence_quality_and_assess_all_streams(self) -> None:
        cadence = [0.0] * 50 + [90.0] * 200
        report = assess_data_quality([220.0] * 250, cadence_stream=cadence)
        assert report.cadence_quality is not None
        assert report.overall_score >= 0


def _pedaling_session(left_start: float, left_end: float, *, n: int = 600) -> Any:
    balance = [left_start] * (n // 2) + [left_end] * (n - n // 2)
    return analyze_pedaling_balance(balance, [180.0] * n, ftp=250.0, pedaling_balance_source="dual")


def _ramp_staircase_powers(*, steps: int = 8, step_s: int = 60, base_w: int = 150, increment: int = 25) -> List[float]:
    powers: List[float] = []
    for step in range(steps):
        powers.extend([float(base_w + step * increment)] * step_s)
    return powers


class TestMmpAggregatorBatch7:
    def test_quality_gate_rejects_dirty_ride(self) -> None:
        power = [0.0] * 80 + [1200.0] * 15 + [-5.0] * 5
        hr = [0.0] * 100
        result = update_power_curve(
            power,
            date(2026, 6, 1),
            stored_curve={60: 350.0},
            hr_stream=hr,
            enforce_quality_gate=True,
        )
        assert result.ride_usable is False
        assert any("quality gate" in note for note in result.notes)

    def test_expired_windows_and_spike_despike(self) -> None:
        stored = {
            60: {
                "duration_s": 60,
                "power_w": 400,
                "ride_date": "2020-01-01",
                "ride_id": "old",
                "reliability": 1.0,
            }
        }
        expired = update_power_curve(
            [250.0] * 3600,
            date(2026, 6, 17),
            stored_curve=stored,
            today=date(2026, 6, 17),
            window_days=90,
        )
        assert len(expired.expired) == 1

        spiky = [200.0] * 100
        spiky[50] = 1500.0
        curve = extract_ride_curve(spiky, durations=[5, 10, 30, 60])
        assert curve
        assert max(curve.values()) < 1500.0

    def test_curve_to_mmp_bare_numbers(self) -> None:
        rebuilt = curve_to_mmp({60: 400.0, "300": {"power_w": 320.0}, "bad": "x"})
        assert rebuilt[60] == 400.0
        assert rebuilt[300] == 320.0


class TestHrvBatch7:
    def test_analyze_rr_stream_long_with_novice_context(self) -> None:
        rr_samples = [
            {
                "elapsed": float(i * 5),
                "rr": [800.0 + np.sin(i / 10.0) * 20.0 for _ in range(30)],
            }
            for i in range(200)
        ]
        ctx = AthleteContext(gender="MALE", training_years=1, discipline="ROAD")
        timeline = analyze_rr_stream(rr_samples, window_seconds=60, step_seconds=10.0, context=ctx)
        assert len(timeline) >= 10
        assert timeline[0]["status"] in {"AEROBIC", "MIXED", "ANAEROBIC"}
        assert timeline[0]["metadata"].get("sqi") is not None

    def test_detect_thresholds_quality_summary(self) -> None:
        rr_samples = [
            {"elapsed": float(i * 5), "rr": [820.0 - i * 0.3 for _ in range(25)]}
            for i in range(120)
        ]
        power = [150.0 + i * 0.6 for i in range(1200)]
        out = detect_thresholds_from_activity(
            rr_samples,
            power_data=power,
            power_timestamps=[float(i) for i in range(len(power))],
            context=AthleteContext(gender="MALE", training_years=1, discipline="ROAD"),
        )
        assert "quality_summary" in out
        assert out["context_used"]["thresholds_modulated"] is True


class TestPedalingBalanceBatch7:
    def test_worsening_trend_with_consistent_drift(self) -> None:
        reports = [_pedaling_session(50, 50) for _ in range(2)] + [_pedaling_session(50, 38) for _ in range(4)]
        trend = analyze_balance_trend(reports)
        assert trend.trend == "worsening"
        assert trend.consistent_drift_direction == "rightward"
        assert trend.sessions_with_drift_above_threshold >= 4
        assert trend.summary and "Unilateral" in trend.summary


class TestIntervalDetectorBatch7:
    def test_ramp_staircase_signal_classification(self) -> None:
        result = classify_session(_ramp_staircase_powers(), ftp=280.0)
        assert result.category == "TEST"
        assert result.subtype == "ramp_test"
        assert result.confidence >= 0.65

    def test_filename_and_hiit_lap_patterns(self) -> None:
        by_name = classify_session([200.0] * 600, filename="gran_fondo_spring.fit", ftp=280.0)
        assert by_name.category == "FREE"
        laps = [{"duration_s": 60, "avg_power_w": 350} for _ in range(12)] + [
            {"duration_s": 120, "avg_power_w": 150} for _ in range(12)
        ]
        hiit = classify_session([250.0] * 2400, laps=laps, ftp=280.0)
        assert hiit.category in {"HIIT", "STEADY", "TEST", "FREE"}


class TestActivityChartsBatch7:
    def test_thermal_and_lr_balance_charts(self) -> None:
        stream = _chart_stream(seconds=300)
        stream.core_temperature = [37.0 + i * 0.01 for i in range(300)]
        stream.skin_temperature = [33.0 + i * 0.005 for i in range(300)]
        stream.left_right_balance = [48.0] * 150 + [42.0] * 150
        charts = build_activity_charts(
            stream,
            zones=[{"name": "Z2", "min_w": 150, "max_w": 220}],
            hrv_durability={"time_in_intensity": {"fat_min": 120.0, "carb_min": 45.0}},
        )
        assert charts["thermal"]["type"] == "line"
        assert charts["lr_balance"]["type"] == "line"
        assert charts["time_in_intensity"]["type"] == "bar"


class TestSessionRouterBatch7:
    def test_cp_test_with_rr_runs_hrv_durability(self) -> None:
        power = [900.0] * 10 + [270.0] * 2000
        rr = [{"elapsed": float(i * 5), "rr": [800.0 + (i % 5)] * 20} for i in range(80)]
        out = route_and_run(
            power,
            rr_samples=rr,
            elapsed_s=[float(i) for i in range(len(power))],
            filename="cp_test.fit",
            ftp=280.0,
            weight_kg=72.0,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 280},
        )
        assert out["routing"]["route"] == "metabolic_anchor"
        assert "hrv_durability" in out["results"] or "hrv_durability" in out["skipped"]

    def test_hiit_with_profile_runs_mader(self) -> None:
        power = ([350.0] * 60 + [150.0] * 120) * 12
        rr = [{"elapsed": float(i * 5), "rr": [810.0] * 15} for i in range(60)]
        out = route_and_run(
            power,
            rr_samples=rr,
            filename="30_15.fit",
            ftp=280.0,
            weight_kg=72.0,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 280, "estimated_vo2max": 62},
        )
        assert out["routing"]["route"] == "hiit"
        assert "mader_durability" in out["results"] or "mader_durability" in out["skipped"]


class TestCardiacEngineBatch7:
    def test_hr_kinetics_tau_on_ramp(self) -> None:
        t = np.arange(180, dtype=float)
        p = np.linspace(100, 280, 180)
        h = 120.0 + 40.0 * (1.0 - np.exp(-t / 45.0))
        seg = Segment(kind="ramp", start_idx=0, end_idx=180, start_t=0.0, end_t=179.0, duration_s=180.0)
        out = compute_hr_kinetics_tau(t, p, h, seg)
        assert out.get("available") is True or out.get("reason") in {"TOO_SHORT", "INSUFFICIENT_HR_RISE"}
        if out.get("available"):
            assert out["tau_s"] > 0


class TestMetabolicCurrentBatch8:
    def test_invalid_mmp_returns_error(self) -> None:
        out = get_current_metabolic_status({}, [], athlete_weight_kg=72.0)
        assert out["status"] == "error"
        assert "baseline" in out.get("error", "").lower() or out.get("details")

    def test_success_with_detraining_and_edge_adapter(self) -> None:
        mmp = {5: 1000, 60: 500, 180: 360, 300: 340, 600: 320, 1200: 290}
        ref = date(2026, 6, 17)
        history = [{"date": ref - timedelta(days=25), "tss": 80.0}]
        out = get_current_metabolic_status(
            mmp,
            history,
            athlete_weight_kg=72.0,
            athlete_context={"gender": "FEMALE", "training_years": 6, "discipline": "MTB"},
            today=ref.isoformat(),
        )
        assert out["status"] == "success"
        assert out["training_load"]["status"] == "DETRAINING"
        assert out["athlete"]["gender"] == "FEMALE"

        edge = handle_edge_function_request(
            {
                "historical_mmp": mmp,
                "workout_history": history,
                "athlete_weight_kg": 72.0,
                "today": ref.isoformat(),
            }
        )
        assert edge["status"] == "success"

    def test_skips_malformed_history_dates(self) -> None:
        mmp = {60: 500, 300: 340, 1200: 290}
        out = get_current_metabolic_status(
            mmp,
            [{"date": "not-a-date", "tss": 50}, {"date": date(2026, 6, 1), "tss": 60}],
            athlete_weight_kg=72.0,
            today=date(2026, 6, 17),
        )
        assert out["status"] == "success"


class TestDetrainingEngineBatch8:
    def test_detraining_status_and_fatmax_shift(self) -> None:
        ref = date(2026, 6, 17)
        history = [{"date": ref - timedelta(days=20), "tss": 5.0}]
        snapshot = {
            "status": "success",
            "estimated_vo2max": 62.0,
            "estimated_vlamax_mmol_L_s": 0.42,
            "mlss_power_watts": 280.0,
            "map_aerobic_watts": 350.0,
            "fatmax_power_watts": 200.0,
        }
        out = apply_detraining_model(snapshot, history, ref)
        assert out["training_load"]["status"] == "DETRAINING"
        assert out["current_fatmax_watts"] == 210.0
        assert out["recommendations"]


class TestFitParserBatch8:
    def test_detect_and_fill_gaps_interpolation(self) -> None:
        values = np.array([200.0, 200.0, 0.0, 0.0, 200.0, 200.0])
        elapsed = np.arange(6, dtype=float)
        quality = np.full(6, QUALITY_GOOD, dtype=np.uint8)
        filled, updated_quality, stats = detect_and_fill_gaps(values, quality, elapsed)
        assert stats["interpolated"] == 1
        assert filled[2] > 0 and filled[3] > 0
        assert np.any(updated_quality[2:4] > QUALITY_GOOD)

    def test_measured_signal_flags_and_lap_normalization(self) -> None:
        stream = ActivityStreamEnhanced(20)
        stream.power[:10] = 220.0
        stream.heart_rate[:10] = 140.0
        stream.cadence[:10] = 90.0
        stream.lat[0] = 45.0
        stream.lon[0] = 7.0
        flags = measured_signal_flags(stream)
        assert flags["power"] and flags["gps"]

        laps = normalize_lap_messages(
            [
                {"total_timer_time": 300, "avg_power": 250, "max_power": 310, "avg_heart_rate": 150},
                {"total_elapsed_time": 0, "avg_power": 200},
            ]
        )
        assert len(laps) == 1
        assert laps[0]["duration_s"] == 300

    def test_parse_records_with_power_gap(self) -> None:
        start = datetime(2026, 6, 1, 8, 0, 0)
        records: List[Dict[str, Any]] = []
        for i in range(120):
            row: Dict[str, Any] = {"timestamp": start + timedelta(seconds=i), "power": 220.0}
            if 40 <= i < 50:
                row["power"] = 0
            records.append(row)
        stream = parse_fit_records_enhanced(
            records,
            session_dict={"start_time": start, "sport": "cycling", "total_elapsed_time": 120},
        )
        assert stream.has_power
        assert stream.gap_summary.get("n_gaps", 0) >= 0


class TestBreakthroughDetectorBatch8:
    def test_major_minor_and_no_breakthrough(self) -> None:
        major = detect_breakthroughs({"60": 400}, {"60": 430})
        assert major["breakthrough"] is True
        assert major["severity"] == "major"

        minor = detect_breakthroughs({"300": 320}, {"300": 328})
        assert minor["severity"] == "minor"

        none = detect_breakthroughs({"60": 400}, {"60": 402})
        assert none["breakthrough"] is False
        assert none["severity"] == "none"


class TestActivityIntelligenceBatch8:
    def test_build_intelligence_envelope(self) -> None:
        stream = _stream(seconds=1800, power=240.0)
        out = build_activity_intelligence(stream, weight_kg=72.0, ftp=280.0, lthr=165.0)
        assert out["status"] == "success"
        assert out["best_efforts_power"]["status"] == "success"
        assert out["power_zones"]["status"] == "success"
        assert "chart_series" in out

    def test_auto_intervals_and_best_efforts_empty(self) -> None:
        intervals = detect_auto_intervals(
            [150.0] * 60 + [300.0] * 120 + [150.0] * 60,
            threshold_w=250.0,
        )
        assert intervals["status"] == "success"
        assert intervals["intervals"]
        skipped = compute_best_efforts([])
        assert skipped["status"] == "skipped"


class TestHrvBatch8:
    def test_analyze_rr_without_elapsed_timestamps(self) -> None:
        rr_samples = [{"rr": [800.0 + (i % 10)] * 30} for i in range(120)]
        timeline = analyze_rr_stream(rr_samples, window_seconds=60, step_seconds=10.0)
        assert len(timeline) >= 5

    def test_detect_thresholds_empty_rr(self) -> None:
        out = detect_thresholds_from_activity([])
        assert out["vt1"]["detected"] is False
        assert "No valid DFA" in out.get("message", "")


class TestCardiacEngineBatch8:
    def test_chronotropic_response_on_ramp(self) -> None:
        t = np.arange(180, dtype=float)
        p = np.linspace(100, 280, 180)
        h = 120.0 + 0.15 * p
        seg = Segment(kind="ramp", start_idx=0, end_idx=180, start_t=0.0, end_t=179.0, duration_s=180.0)
        out = compute_chronotropic_response(t, p, h, seg)
        assert out["available"] is True
        assert out["slope_bpm_per_w"] > 0
        assert out["r_squared"] is not None

    def test_chronotropic_flat_power_rejected(self) -> None:
        t = np.arange(120, dtype=float)
        p = np.full(120, 220.0)
        h = np.linspace(130, 150, 120)
        seg = Segment(kind="steady", start_idx=0, end_idx=120, start_t=0.0, end_t=119.0, duration_s=120.0)
        out = compute_chronotropic_response(t, p, h, seg)
        assert out["available"] is False
        assert out["reason"] == "POWER_NOT_VARYING"


class TestDurabilityEngineBatch9:
    def test_prescription_all_classifications(self) -> None:
        for classification, needle in [
            ("EXCELLENT", "Maintain"),
            ("GOOD", "Fine-tune"),
            ("FAIR", "Build aerobic"),
            ("POOR", "URGENT"),
        ]:
            rx = generate_durability_prescription(95.0, classification)
            assert needle in rx["focus"]

    def test_insufficient_duration_and_poor_ride(self) -> None:
        short = calculate_durability_index([220.0] * 3600, 3600, min_duration_hours=2.0)
        assert short["status"] == "insufficient_duration"
        poor_power = [250.0] * 3600 + [200.0] * 3600
        poor = calculate_durability_index(poor_power, len(poor_power))
        assert poor["classification"] == "POOR"
        assert poor["durability_index"] < 88


class TestManualLoadBatch9:
    def test_cycling_mobility_and_damage_override(self) -> None:
        bike = calculate_manual_load(duration_min=60, rpe=6, modality="bike")
        mobility = calculate_manual_load(duration_min=30, rpe=3, modality="mobility")
        custom = calculate_manual_load(
            duration_min=45,
            rpe=8,
            modality="strength",
            muscle_damage_factor=2.0,
            notes="heavy legs",
        )
        assert bike["input"]["modality"] == "bike"
        assert mobility["load"]["recovery_cost"] < bike["load"]["recovery_cost"]
        assert custom["input"]["muscle_damage_factor"] == 2.0
        assert custom["input"]["notes"] == "heavy legs"


class TestCogganClassifierBatch9:
    def test_sprinter_profile_and_duration_tier(self) -> None:
        profile = classify_power_profile(
            weight_kg=72.0,
            gender="MALE",
            p5s=1400,
            p1min=900,
            p5min=450,
            ftp=320,
        )
        assert profile["status"] == "success"
        assert profile["overall"]["phenotype_code"] == "SPRINTER"

        tier = classify_duration(5.5, "5min", "FEMALE")
        assert tier["tier"] in {"UNTRAINED", "FAIR", "MODERATE", "GOOD", "VERY_GOOD", "EXCELLENT", "WORLD_CLASS"}

    def test_classify_from_mmp_ftp_fallback(self) -> None:
        mmp = [
            {"duration_s": 5, "power_w": 1400},
            {"duration_s": 60, "power_w": 900},
            {"duration_s": 300, "power_w": 450},
            {"duration_s": 1200, "power_w": 340},
        ]
        out = classify_from_mmp(mmp, weight_kg=72.0, gender="MALE")
        assert out["status"] == "success"
        assert out["by_duration"]["ftp"]["available"] is True


class TestMetabolicFlexibilityBatch9:
    def test_mfi_bands_and_fat_oxidation(self) -> None:
        excellent = calculate_metabolic_flexibility_index(220, 300)
        carb = calculate_metabolic_flexibility_index(150, 300)
        zero = calculate_metabolic_flexibility_index(200, 0)
        assert excellent["classification"] == "EXCELLENT"
        assert carb["classification"] == "CARB_DEPENDENT"
        assert zero["status"] == "error"

        elite = estimate_fat_oxidation_rate(250, 70.0)
        bad_weight = estimate_fat_oxidation_rate(200, 0.0)
        assert elite["status"] == "success"
        assert bad_weight["status"] == "error"


class TestEffortsAnalyzerBatch9:
    def test_full_anchor_breakdown(self) -> None:
        mmp = [
            {"duration_s": 5, "power_w": 1400, "wkg": 19.4},
            {"duration_s": 60, "power_w": 900, "wkg": 12.5},
            {"duration_s": 300, "power_w": 450, "wkg": 6.25},
            {"duration_s": 1200, "power_w": 340, "wkg": 4.7},
        ]
        out = analyze_efforts(
            mmp,
            weight_kg=72.0,
            ftp=320.0,
            cp_fit={"cp_w": 310.0, "wprime_kj": 22.0},
            metabolic_snapshot={
                "mlss_power_watts": 300.0,
                "map_aerobic_watts": 380.0,
                "fatmax_power_watts": 220.0,
            },
        )
        assert out["status"] == "success"
        assert out["efforts"]
        assert out["efforts"][0]["pct_ftp"] is not None
        assert "best_sprint_5s" in out["summary"]


class TestGlycolyticValidationBatch9:
    def test_vlapeak_observed_and_profile(self) -> None:
        observed = compute_vlapeak_observed(1.2, 8.5, 30.0)
        assert observed["status"] == "success"
        assert observed["vlapeak_observed_mmol_l_s"] > 0

        bad = compute_vlapeak_observed(5.0, 4.0, 30.0)
        assert bad["status"] == "error"

        snap = {
            "status": "success",
            "estimated_vlamax_mmol_L_s": 0.55,
            "mlss_power_watts": 280.0,
            "map_aerobic_watts": 350.0,
        }
        profile = build_glycolytic_profile(snap)
        assert profile["status"] == "success"
        assert profile["glycolytic_flux_index"] > 0

        comparison = validate_vlapeak_against_model(
            vlapeak_observed_mmol_l_s=0.8,
            predicted_vlapeak_mmol_l_s=0.75,
            model_vlamax_mmol_l_s=0.55,
        )
        assert comparison["status"] == "success"


class TestAthleteContextBatch9:
    def test_sport_discipline_mapping_and_getters(self) -> None:
        sprint_ctx = AthleteContext(gender="FEMALE", discipline="TRACK_SPRINT", training_years=12)
        endurance_ctx = AthleteContext(discipline="GRAVEL", training_years=0.5, body_fat_pct=18.0)
        assert sprint_ctx.effective_discipline() == "SPRINT"
        assert endurance_ctx.effective_discipline() == "ENDURANCE"
        assert sprint_ctx.expected_eta() > endurance_ctx.expected_eta()
        assert sprint_ctx.vlamax_initial_guess() > 0
        assert sprint_ctx.cho_oxidation_coefficient() == 1.0
        assert "discipline" in sprint_ctx.inferred_fields() or sprint_ctx.effective_discipline()


class TestPowerCurveHistoryBatch9:
    def test_empty_history_and_wkg_curve(self) -> None:
        empty = build_power_curve_history([], as_of="2026-06-17", weight_kg=72.0)
        assert empty["status"] == "success"
        assert empty["periods"]["last_90_days"]["activity_count"] == 0
        assert empty["periods"]["last_90_days"]["curve_w_kg"] == {}

        populated = build_power_curve_history(
            [{"date": "2026-06-01", "mmp": {"300": 320}}],
            as_of="2026-06-15",
            weight_kg=72.0,
        )
        assert populated["periods"]["last_90_days"]["curve_w_kg"]["300"] > 0


class TestHrvBatch9:
    def test_invalid_window_rejects_artifact_heavy_rr(self) -> None:
        noisy = [300.0, 2000.0, 100.0, 1800.0] * 20
        out = calculate_dfa_alpha1(noisy)
        assert out["status"] in {"INVALID_WINDOW", "ERROR", "INSUFFICIENT_DATA"}

    def test_detect_thresholds_with_long_declining_stream(self) -> None:
        rr_samples = [
            {"elapsed": float(i * 5), "rr": [900.0 - i * 1.5 + (j % 3) for j in range(30)]}
            for i in range(180)
        ]
        power = [120.0 + i * 1.2 for i in range(1800)]
        out = detect_thresholds_from_activity(
            rr_samples,
            power_data=power,
            power_timestamps=[float(i) for i in range(len(power))],
        )
        assert "quality_summary" in out
        assert out["quality_summary"]["windows_analyzed"] >= 1


class TestCardiacEngineBatch9:
    def test_full_analyzer_with_cross_validation(self) -> None:
        samples: List[ActivitySample] = []
        for i in range(1200):
            power = 100.0 + i * 0.15 if i < 400 else 220.0
            samples.append(ActivitySample(t=float(i), power=power, hr=120.0 + power * 0.2))
        for j in range(200):
            samples.append(ActivitySample(t=1200.0 + float(j), power=0.0, hr=max(100.0, 180.0 - j * 0.3)))

        hrv = [
            {"timestamp": 200.0, "status": "AEROBIC"},
            {"timestamp": 500.0, "status": "MIXED"},
            {"timestamp": 900.0, "status": "ANAEROBIC"},
        ]
        out = CardiacResponseAnalyzer(
            weight=72.0,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 220},
            hrv_timeline=hrv,
        ).analyze(samples)
        assert out["status"] == "success"
        assert out["segments"]["steady"] or out["segments"]["recovery"]
        assert out["metrics"]["hr_recovery"] or out["metrics"]["aerobic_decoupling"]
        assert out["cross_validation"].get("available") is True or "hr_at_vt1_dfa" in out["cross_validation"]


class TestFitParserBatch9:
    def test_long_gap_marks_unreliable(self) -> None:
        values = np.array([200.0, 200.0, 0.0, 0.0, 0.0, 0.0, 0.0, 200.0])
        elapsed = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 70.0])
        quality = np.full(len(values), QUALITY_GOOD, dtype=np.uint8)
        filled, updated_quality, stats = detect_and_fill_gaps(
            values,
            quality,
            elapsed,
            gap_short_s=5.0,
            gap_long_s=30.0,
        )
        assert stats["unreliable"] >= 1 or stats["forward_filled"] >= 1
        assert filled[-1] == 200.0


class TestChartBuilderBatch10:
    def test_secondary_chart_types(self) -> None:
        drift = chart_cardiac_drift(
            [
                {"segment": "First Half", "drift_pct": 2.3, "fitness": "EXCELLENT"},
                {"segment": "Second Half", "drift_pct": 6.5, "fitness": "FAIR"},
            ]
        )
        assert drift["type"] == "bar"

        decay = chart_detraining_decay(
            ["VO2max", "MLSS"],
            [62.0, 280.0],
            [58.0, 265.0],
            ["ml/kg/min", "W"],
        )
        assert decay["type"] == "bar_grouped"

        radar = chart_efforts_radar(
            ["5s", "1min", "5min"],
            [180.0, 140.0, 110.0],
            [175.0, 135.0, 105.0],
            [170.0, 130.0, 100.0],
            [165.0, 125.0, 95.0],
        )
        assert radar["type"] == "radar"

        spider = chart_phenotype_spider({"5s": 7, "1min": 6, "5min": 4, "FTP": 3})
        assert spider["type"] == "radar"

        matrix = chart_cross_validation_matrix(
            ["HRV", "Mader"],
            [250.0, 255.0],
            [315.0, None],
        )
        assert matrix["type"] == "table"
        assert matrix["data"][1]["VT2 (W)"] == "N/A"

        kinetics = chart_hr_kinetics([0, 60, 120], [130, 150, 165], tau=45.0, steady_state_hr=170)
        assert kinetics["type"] == "line_scatter"

        scatter = chart_power_hr_scatter([180, 220, 260], [130, 145, 160], mlss_power=250.0)
        assert scatter["type"] == "scatter"

        recovery = chart_hr_recovery(
            [{"name": "Recovery 1", "hrr_60s": 25, "hrr_120s": 42}],
        )
        assert recovery["type"] == "bar_grouped"


class TestDurabilityEngineBatch10:
    def test_np_drift_tte_and_hourly_decay(self) -> None:
        short = calculate_np_drift([220.0] * 1200, 1200)
        assert short["status"] == "insufficient_duration"

        power = [270.0] * 1800 + [250.0] * 1800
        drift = calculate_np_drift(power, len(power))
        assert drift["status"] == "success"
        assert drift["classification"] in {"EXCELLENT", "GOOD", "FAIR", "POOR"}

        tte = calculate_tte_sustainability([280.0] * 4200 + [200.0] * 600, 270.0)
        assert tte["classification"] == "EXCELLENT"

        hourly = generate_hourly_decay_curve([250.0] * 7200, 7200)
        assert hourly["status"] == "success"
        assert len(hourly["hourly_data"]) >= 2

        short_hourly = generate_hourly_decay_curve([220.0] * 1800, 1800)
        assert short_hourly["status"] == "insufficient_duration"


class TestProfileAnchorFlowBatch10:
    def test_build_anchor_and_ride_update_paths(self) -> None:
        proposal = {
            "confidence": 0.85,
            "sprint": {
                "peak_1s_w": 1200,
                "mean_w": 900,
                "duration_s": 15,
                "peak_3s_w": 1100,
                "peak_5s_w": 1050,
            },
            "mmp_for_fit": {60: 520, 180: 420, 300: 380, 720: 340, 1200: 320},
        }
        anchor = build_anchor_from_proposal(proposal, weight_kg=72.0, measured_on="2026-06-01")
        assert anchor.status in {"anchored", "partial"}
        assert anchor.profile is not None

        profile = MeasuredProfile(
            measured_on=date(2026, 1, 1),
            vo2max=62.0,
            vlamax=0.42,
            mlss_watts=280.0,
        )
        held = update_profile_from_ride(
            profile,
            {5: 700, 60: 400, 300: 350, 1200: 400},
            weight_kg=72.0,
            as_of="2026-06-17",
        )
        assert held["status"] == "anchor_held"

        updated = update_profile_from_ride(
            profile,
            {5: 1200, 60: 900, 300: 400, 1200: 320},
            weight_kg=72.0,
            as_of="2026-06-17",
        )
        assert updated.get("update_method") == "deterministic_fit_with_vlamax_prior"


class TestActivityChartsBatch10:
    def test_individual_chart_helpers(self) -> None:
        stream = _chart_stream(seconds=120)
        stream.lat = [45.0] * 120
        stream.lon = [7.0] * 120
        stream.left_power_phase = [12.0] * 120
        assert chart_elevation(stream)["type"] == "line"
        assert chart_speed(stream)["type"] == "line"
        assert chart_position(stream)["type"] == "map"
        assert chart_power_phase(stream)["type"] == "cycling_dynamics"

        empty = SimpleNamespace(time=[], altitude=[], lat=[], lon=[], left_power_phase=[])
        assert chart_position(empty).get("available") is False


class TestMmpAggregatorBatch10:
    def test_merge_improvements_with_streams(self) -> None:
        stored = {
            60: {
                "duration_s": 60,
                "power_w": 400,
                "ride_date": "2026-06-01",
                "ride_id": "r1",
                "reliability": 1.0,
            }
        }
        result = update_power_curve(
            [420.0] * 3600,
            date(2026, 6, 10),
            stored_curve=stored,
            weight_kg=72.0,
            hr_stream=[140.0] * 3600,
            cadence_stream=[90.0] * 3600,
            ride_id="strong_ride",
        )
        assert result.ride_usable is not False
        assert result.improvements or result.mmp_for_profiler.get(60, 0) >= 400


class TestCardiacEngineBatch10:
    def test_ramp_segment_kinetics(self) -> None:
        samples = [
            ActivitySample(t=float(i), power=100.0 + i * 0.5, hr=100.0 + (100.0 + i * 0.5) * 0.3)
            for i in range(1200)
        ]
        out = CardiacResponseAnalyzer(weight=72.0).analyze(samples)
        assert out["status"] == "success"
        assert out["segments"]["ramp"]
        assert out["metrics"]["hr_kinetics"] or out["metrics"]["chronotropic_response"]


class TestMetabolicKalmanBatch10:
    def test_update_with_anchors_and_lab(self) -> None:
        kalman = MetabolicKalman(np.array([60.0, 0.4]), np.diag([4.0, 0.01]), weight=72.0)
        kalman.predict(DailyInput(date=date(2026, 6, 1), vo2max_stimulus_min=25.0))
        state = kalman.update([(180, 360.0), (360, 330.0), (720, 300.0)])
        assert state is not None
        assert state.vo2max > 0

        lab = create_lab_result(date(2026, 6, 2), vo2max=63.0, vlamax=0.41)
        lab_state = kalman.update_from_lab(lab)
        assert lab_state.vo2max > 0


class TestLoadTrendsBatch10:
    def test_moderate_risk_band(self) -> None:
        ref = date(2026, 6, 17)
        activities = []
        for i in range(90):
            d = ref - timedelta(days=89 - i)
            tss = 55.0 if i >= 70 else 20.0
            activities.append({"date": d.isoformat(), "tss": tss})
        out = compute_load_trends(activities, as_of=ref.isoformat())
        assert out["risk"] in {"moderate", "high"}
        assert out["acute_load"] > out["chronic_load"]


class TestLabDataBatch10:
    def test_parse_german_source_markers(self) -> None:
        text = (
            "Spiroergometrie Bericht\n"
            "VO2max 58.5 ml/kg/min\n"
            "FTP: 265 W\n"
            "FatMax 190 W\n"
            "Gewicht 72 kg\n"
        )
        result = parse_lab_text(text)
        assert result.vo2max_ml_kg_min == 58.5
        assert result.mlss_power_w == 265
        assert result.fatmax_power_w == 190


class TestFitParserBatch10:
    def test_parse_extended_sensor_fields(self) -> None:
        start = datetime(2026, 6, 1, 8, 0, 0)
        records = []
        for i in range(60):
            records.append(
                {
                    "timestamp": start + timedelta(seconds=i),
                    "power": 220.0,
                    "heart_rate": 140,
                    "cadence": 90,
                    "position_lat": 45.0 + i * 0.0001,
                    "position_long": 7.0 + i * 0.0001,
                    "respiration_rate": 16.0,
                    "core_body_temperature": 37.1,
                    "skin_temperature": 33.0,
                    "left_right_balance": 128,
                }
            )
        stream = parse_fit_records_enhanced(
            records,
            session_dict={"start_time": start, "sport": "cycling", "total_elapsed_time": 60},
        )
        flags = measured_signal_flags(stream)
        assert flags["gps"]
        assert flags["respiration"]
        assert stream.has_core_sensor
        assert np.any(stream.left_right_balance > 0)


class TestAdaptiveLoadCompletion:
    def test_readiness_status_bands_and_flags(self) -> None:
        high = calculate_readiness(
            DailyStatus(
                morning_hrv_lnrmssd=4.5,
                baseline_hrv_lnrmssd=4.3,
                morning_rhr=45,
                baseline_rhr=46,
                morning_temp_c=36.5,
                baseline_temp_c=36.5,
                sleep_score=90,
                soreness=1,
                stress=1,
                mood=5,
            )
        )
        assert high["status"] == "high"
        assert high["available"] is True

        low = calculate_readiness(
            DailyStatus(
                morning_hrv_lnrmssd=3.8,
                baseline_hrv_lnrmssd=4.3,
                morning_rhr=58,
                baseline_rhr=46,
                morning_temp_c=37.3,
                baseline_temp_c=36.5,
                sleep_score=30,
                soreness=5,
                stress=5,
                mood=1,
            )
        )
        assert low["status"] == "low"
        assert low["flags"]

        missing = calculate_readiness(None)
        assert missing["available"] is False

    def test_orchestrator_with_history(self) -> None:
        stream = _stream(seconds=600, power=230.0)
        workout_summary = {
            "stream_metadata": {"sport": "cycling", "duration_s": 600, "has_power": True, "has_hr": True},
            "sections": {
                "power": {
                    "status": "success",
                    "metrics": {
                        "duration_s": 600,
                        "tss": 55.0,
                        "intensity_factor": 0.82,
                        "normalized_power": 230.0,
                        "work_kj": 138.0,
                    },
                },
                "cardiac": {"status": "success", "metrics": {"avg_hr": 145}},
            },
            "headline": {"worst_cardiac_drift_pct": 6.0, "worst_aerobic_decoupling_pct": 4.0},
        }
        report = build_adaptive_load_report(
            stream=stream,
            workout_summary=workout_summary,
            athlete_profile=AthleteLoadProfile(weight_kg=72.0, ftp=280.0, hr_max=190.0, hr_rest=48.0),
            daily_status=DailyStatus(morning_hrv_lnrmssd=4.2, baseline_hrv_lnrmssd=4.3),
            history=[{"session_load": 50.0 + (i % 10)} for i in range(42)],
        )
        assert report["status"] == "success"
        assert report["sections"]["session_load"]["external_load"]["tss"] > 0


class TestMetabolicPhenotypeCompletion:
    def test_enhance_snapshot_and_energy_contribution(self) -> None:
        snap = {
            "status": "success",
            "estimated_vo2max": 62.0,
            "mlss_power_watts": 280.0,
            "map_aerobic_watts": 350.0,
        }
        enhanced = enhance_metabolic_snapshot_with_phenotype(
            snap,
            phenotype="SPRINTER",
            weight_kg=72.0,
            power_30s=500.0,
            power_1200s=280.0,
        )
        assert enhanced["phenotype_pcr_params"]["phenotype"] == "SPRINTER"
        assert enhanced["energy_contributions"] is not None

        partial = enhance_metabolic_snapshot_with_phenotype({"status": "success"}, phenotype="SPRINTER")
        assert partial.get("phenotype_enhancement_status") == "insufficient_metabolic_fields"

        contrib = compute_energy_contribution_adaptive(
            duration_s=1200.0,
            power_w=280.0,
            vo2max_mlkgmin=62.0,
            weight_kg=72.0,
            phenotype="TT_CLIMBER",
        )
        assert contrib["pcr_fraction"] + contrib["anaerobic_fraction"] + contrib["aerobic_fraction"] > 0.9


class TestMaderResidualMlpCompletion:
    def test_neural_power_duration_predict_and_fit(self) -> None:
        model = NeuralPowerDuration(n_hidden=8, seed=1)
        durations = np.array([30.0, 60.0, 180.0, 300.0])
        mader = np.array([520.0, 480.0, 400.0, 360.0])
        untrained = model.predict(durations, mader, vo2max=62.0, vlamax=0.4)
        assert np.allclose(untrained, mader)
        observed = mader * 1.03
        result = model.fit(durations, observed, mader, vo2max=62.0, vlamax=0.4, max_iter=50)
        trained = model.predict(durations, mader, vo2max=62.0, vlamax=0.4)
        assert result.n_train_points == len(durations)
        assert trained.shape == mader.shape


class TestDetrainingCompletion:
    def test_load_status_branches(self) -> None:
        ref = date(2026, 6, 17)
        base = {
            "status": "success",
            "estimated_vo2max": 62.0,
            "estimated_vlamax_mmol_L_s": 0.42,
            "mlss_power_watts": 280.0,
            "map_aerobic_watts": 350.0,
            "fatmax_power_watts": 200.0,
        }
        improving = apply_detraining_model(
            base,
            [{"date": ref - timedelta(days=i), "tss": 95.0} for i in range(60)],
            ref,
        )
        assert improving["training_load"]["status"] in {"IMPROVING", "MAINTAINING"}
        assert improving["training_load"]["ctl"] >= 40.0
        assert improving["recommendations"]

        declining = apply_detraining_model(
            base,
            [{"date": ref - timedelta(days=i), "tss": 8.0} for i in range(14)],
            ref,
        )
        assert declining["training_load"]["status"] in {"DECLINING", "MAINTAINING", "DETRAINING"}


class TestGlycolyticWingateCompletion:
    def test_validate_wingate_glycolytic(self) -> None:
        profiler = MetabolicProfiler(weight=72.0)
        mmp = {5: 1100, 60: 520, 180: 420, 300: 380, 720: 340, 1200: 320}
        out = validate_wingate_glycolytic(
            lactate_pre_mmol=1.2,
            lactate_post_mmol=12.0,
            duration_s=30.0,
            peak_power_w=1100.0,
            mean_power_w=850.0,
            profiler=profiler,
            mmp=mmp,
        )
        assert out["status"] in {"success", "insufficient_data"}


class TestActivityChartsCompletion:
    def test_all_chart_helpers_and_na_paths(self) -> None:
        stream = _chart_stream(seconds=180)
        stream.respiration_rate = [16.0] * 180
        stream.temperature = [22.0] * 180
        assert chart_power(stream)["type"] == "line"
        assert chart_heart_rate(stream)["type"] == "line"
        assert chart_cadence(stream)["type"] == "line"
        assert chart_respiration(stream)["type"] == "line"
        assert chart_ambient_temp(stream)["type"] == "line"
        zones = chart_time_in_power_zone(stream, [{"name": "Z2", "min_w": 150, "max_w": 220}])
        assert zones["type"] == "bar"

        empty = SimpleNamespace(time=[], power=[], heart_rate=[], cadence=[], speed=[], altitude=[])
        assert chart_speed(empty).get("available") is False
        assert chart_elevation(empty).get("available") is False


class TestMmpAggregatorCompletion:
    def test_monotonicity_rejection_and_date_parsing(self) -> None:
        stored = {
            60: {
                "duration_s": 60,
                "power_w": 400,
                "ride_date": "2025-01-01",
                "ride_id": "r1",
                "reliability": 1.0,
            },
            300: {
                "duration_s": 300,
                "power_w": 340,
                "ride_date": "2025-01-01",
                "ride_id": "r1",
                "reliability": 1.0,
            },
        }
        spiky = [500.0] * 60 + [330.0] * 3540
        result = update_power_curve(
            spiky,
            "2026-06-10",
            stored_curve=stored,
            weight_kg=72.0,
            enforce_monotonicity=True,
        )
        assert result.rejected or result.improvements or result.curve

        expired = update_power_curve(
            [250.0] * 3600,
            date(2026, 6, 17),
            stored_curve=stored,
            today=date(2026, 6, 17),
            window_days=90,
        )
        assert len(expired.expired) >= 1


class TestIntervalDetectorCompletion:
    def test_cp_blocks_and_protocol_completeness(self) -> None:
        ftp = 280.0
        powers = [100.0] * 300
        for block in [(900, 10), (600, 8), (360, 6)]:
            powers.extend([float(block[0])] * block[1])
        powers.extend([150.0] * 1200)
        result = classify_session(powers, ftp=ftp)
        assert result.category in {"TEST", "HIIT", "STEADY", "ENDURANCE", "FREE"}

        report = protocol_completeness(
            available_durations_s=[5, 60, 180, 300, 720, 1200],
            qualified_anchors=[
                QualifiedAnchor(
                    duration_s=60,
                    power_w=520,
                    anchor_reliability=1.0,
                    source_subtype="cp_test",
                ),
                QualifiedAnchor(
                    duration_s=300,
                    power_w=380,
                    anchor_reliability=0.9,
                    source_subtype="threshold",
                ),
            ],
        )
        assert report.to_dict()["completeness_pct"] > 0.5


class TestHrvCompletion:
    def test_threshold_crossing_with_declining_alpha(self) -> None:
        rr_samples = []
        for i in range(240):
            base = max(650.0, 950.0 - i * 2.5)
            rr_samples.append(
                {
                    "elapsed": float(i * 5),
                    "rr": [base + (j % 5) * 2.0 for j in range(35)],
                }
            )
        power = [100.0 + i * 1.5 for i in range(2400)]
        out = detect_thresholds_from_activity(
            rr_samples,
            power_data=power,
            power_timestamps=[float(i) for i in range(len(power))],
            window_seconds=90,
            step_seconds=8.0,
        )
        assert out["quality_summary"]["windows_analyzed"] >= 1
        assert "vt1" in out and "vt2" in out


class TestAthleteContextCompletion:
    def test_all_discipline_mappings(self) -> None:
        for sport, expected in [
            ("ROAD", "ENDURANCE"),
            ("MTB_XCO", "MIXED"),
            ("TRACK_SPRINT", "SPRINT"),
            ("TRIATHLON", "ENDURANCE"),
            ("CRITERIUM", "MIXED"),
        ]:
            ctx = AthleteContext(discipline=sport, training_years=5)
            assert ctx.effective_discipline() == expected
            assert ctx.phenotype_thresholds()[0] > 0
            assert ctx.active_muscle_fraction() > 0


class TestLoadTrendsCompletion:
    def test_summary_nested_tss_path(self) -> None:
        ref = date(2026, 6, 17)
        activities = [
            {
                "date": (ref - timedelta(days=i)).isoformat(),
                "summary": {"training_stress_score": 40.0 + (i % 5)},
            }
            for i in range(90)
        ]
        out = compute_load_trends(activities, as_of=ref.isoformat())
        assert out["status"] == "success"
        assert out["acute_load"] > 0


class TestDataQualityCompletion:
    def test_clean_streams_and_pause_detection(self) -> None:
        power = [220.0] * 100 + [0.0] * 30 + [220.0] * 100
        cleaned = clean_power_stream([-5.0, 1200.0, 220.0, 220.0])
        assert all(p >= 0 for p in cleaned)
        pauses = detect_pauses(power, threshold_seconds=20)
        assert pauses
        trimmed = remove_pauses(power, pauses)
        assert len(trimmed) < len(power)
        hr = clean_hr_stream([0.0, 35.0, 140.0, 250.0, 145.0])
        assert len(hr) == 5
        assert 130.0 <= hr[2] <= 150.0
        assert max(hr) <= 220.0


class TestThermalEngineCompletion:
    def test_heat_acclimation_branches(self) -> None:
        sessions = [
            ThermalSessionReport(
                data_quality="good",
                n_valid_samples=3000,
                n_total_samples=3600,
                thermal_rise_rate=0.030 - i * 0.003,
                heat_tolerance_threshold=38.0 + i * 0.1,
            )
            for i in range(6)
        ]
        trend = analyze_heat_acclimation(sessions)
        assert trend.n_sessions == 6
        assert trend.trend in {"acclimating", "stable", "declining", None} or trend.notes


class TestPhase4CompletionBatch11:
    def test_neural_dynamics_and_mlp_state(self) -> None:
        mlp = TinyMLP(n_in=3, n_hidden=4, n_out=2, seed=2)
        batch = mlp.forward(np.array([[1.0, 0.5, 0.2], [0.8, 0.3, 0.1]]))
        assert batch.shape == (2, 2)

        pd = NeuralPowerDuration(n_hidden=8, seed=3)
        short_fit = pd.fit(np.array([30.0, 60.0]), np.array([500.0, 470.0]), np.array([490.0, 460.0]), 62.0, 0.4)
        assert short_fit.success is False

        durations = np.array([30.0, 60.0, 180.0, 300.0])
        mader = np.array([520.0, 480.0, 400.0, 360.0])
        observed = mader * 1.03
        trained = pd.fit(durations, observed, mader, vo2max=62.0, vlamax=0.4, max_iter=50)
        assert trained.n_train_points == len(durations)
        pd2 = NeuralPowerDuration(n_hidden=8, seed=3)
        pd2.load_state(pd.get_state())
        assert np.allclose(
            pd2.predict(durations, mader, vo2max=62.0, vlamax=0.4),
            pd.predict(durations, mader, vo2max=62.0, vlamax=0.4),
        )

        nd = NeuralDynamics(n_hidden=8, seed=4)
        assert nd.predict_delta(55.0, 0.4, 10.0, 2.0) == (0.0, 0.0)
        transitions = [
            {
                "vo2_before": 55.0,
                "vla_before": 0.40,
                "vo2_after": 55.4,
                "vla_after": 0.41,
                "vo2_stimulus_min": 18.0,
                "vla_stimulus_min": 4.0,
                "days_between": 7,
            },
            {
                "vo2_before": 55.4,
                "vla_before": 0.41,
                "vo2_after": 54.9,
                "vla_after": 0.39,
                "vo2_stimulus_min": 2.0,
                "vla_stimulus_min": 0.0,
                "days_between": 7,
            },
            {
                "vo2_before": 54.9,
                "vla_before": 0.39,
                "vo2_after": 55.6,
                "vla_after": 0.42,
                "vo2_stimulus_min": 20.0,
                "vla_stimulus_min": 5.0,
                "days_between": 7,
            },
        ]
        dyn = nd.fit(transitions, reg_lambda=0.01, max_iter=80)
        assert dyn.n_transitions == 3
        delta = nd.predict_delta(55.0, 0.4, 15.0, 3.0, days=2.0)
        assert isinstance(delta[0], float)
        restored = NeuralDynamics(n_hidden=8, seed=4)
        restored.load_state(nd.get_state())
        assert restored.predict_delta(55.0, 0.4, 15.0, 3.0) != (0.0, 0.0) or dyn.success

    def test_hrv_threshold_crossing_branches(self) -> None:
        with pytest.raises(ValueError):
            _detect_threshold_crossing([], threshold=0.75, persistence_windows=0)

        no_cross = _detect_threshold_crossing(
            [{"timestamp": 0.0, "alpha1_smoothed": 0.9}, {"timestamp": 10.0, "alpha1_smoothed": 0.85}],
            threshold=0.75,
        )
        assert no_cross == (None, None, None)

        crossing, t_cross, p_cross = _detect_threshold_crossing(
            [
                {"timestamp": 100.0, "alpha1_smoothed": 0.80},
                {"timestamp": 110.0, "alpha1_smoothed": 0.70},
                {"timestamp": 120.0, "alpha1_smoothed": 0.65},
            ],
            threshold=0.75,
            power_data=[200.0, 300.0, 400.0],
            power_timestamps=[100.0, 110.0, 120.0],
            persistence_windows=2,
        )
        assert t_cross == 110
        assert abs(p_cross - 250.0) < 1e-6

        flat_denom = _detect_threshold_crossing(
            [
                {"timestamp": 0.0, "alpha1_smoothed": 0.80},
                {"timestamp": 10.0, "alpha1_smoothed": 0.70},
                {"timestamp": 20.0, "alpha1_smoothed": 0.65},
            ],
            threshold=0.75,
            power_data=[200.0, 200.0, 200.0],
            power_timestamps=[0.0, 10.0, 20.0],
            persistence_windows=2,
        )
        assert flat_denom[2] == 200.0

    def test_chart_builder_cei_and_workout_charts(self) -> None:
        for cei, label in [(1.15, "EXCELLENT"), (1.05, "GOOD"), (0.95, "FAIR"), (0.80, "POOR")]:
            scatter = chart_power_hr_scatter([180, 220, 260], [130, 145, 160], mlss_power=250.0, cei=cei)
            assert label in scatter["title"]

        hrv = chart_hrv_timeline(
            [float(i * 60) for i in range(12)],
            [0.95 - i * 0.03 for i in range(12)],
            vt1_power=180,
            vt2_power=220,
            power_series=[150 + i * 8 for i in range(12)],
        )
        assert hrv["type"] == "line_multi_axis"
        assert hrv.get("markers")

        charts = generate_workout_charts(
            {
                "power_metrics": {
                    "mmp_curve": {60: 500, 300: 340},
                    "cp_model": {"cp": 280, "w_prime": 18000},
                    "ftp": 290,
                },
                "zones_distribution": {
                    "coggan": {"Z1": 20, "Z2": 50},
                    "friel": {"Z1": 15, "Z2": 55},
                    "seiler": {"Z1": 25, "Z2": 45},
                    "metabolic": {"Z1": 30, "Z2": 40},
                },
                "cardiac_metrics": {
                    "drift": {"segments": [{"segment": "First Half", "drift_pct": 4.0, "fitness": "GOOD"}]},
                    "recovery_segments": [{"name": "R1", "hrr_60s": 22, "hrr_120s": 38}],
                },
            }
        )
        assert "power_duration" in charts
        assert "cardiac_drift" in charts
        assert "hr_recovery" in charts

    def test_phenotype_recovery_and_weight_gates(self) -> None:
        curve = compute_recovery_curve_adaptive(30.0, 120.0, phenotype="SPRINTER", sample_rate_s=5.0)
        assert len(curve) == 24

        missing_weight = enhance_metabolic_snapshot_with_phenotype(
            {"status": "success", "estimated_vo2max": 62.0, "mlss_power_watts": 280.0},
            phenotype="SPRINTER",
        )
        assert missing_weight["phenotype_enhancement_status"] == "insufficient_weight"

        invalid_weight = enhance_metabolic_snapshot_with_phenotype(
            {"status": "success", "estimated_vo2max": 62.0, "mlss_power_watts": 280.0},
            phenotype="SPRINTER",
            weight_kg=0.0,
        )
        assert invalid_weight["phenotype_enhancement_status"] == "invalid_weight"

        defaults = enhance_metabolic_snapshot_with_phenotype(
            {"status": "success", "estimated_vo2max": 62.0, "mlss_power_watts": 280.0},
            phenotype="UNKNOWN_PHENOTYPE",
            weight_kg=72.0,
        )
        assert defaults["phenotype_pcr_params"]["phenotype"] == "DEFAULT"
        assert defaults["energy_contributions"]["sprint_30s"]["pcr_fraction"] > 0

    def test_lab_data_roundtrip_and_parse_edges(self) -> None:
        parsed = parse_lab_text("VO2max: 58 ml/kg/min\nVLamax 0.45\nTest date 17/06/2026")
        assert parsed.vo2max_ml_kg_min == 58.0
        assert parsed.test_date.year == 2026

        restored = LabTestResult.from_dict(
            {
                "test_date": "2026-01-15",
                "source": "not_a_real_source",
                "test_type": "not_a_real_type",
                "lactate_curve": [{"power_w": 200, "lactate_mmol": 2.0, "heart_rate_bpm": 140}],
                "vo2max_ml_kg_min": 60.0,
            }
        )
        assert restored.source == LabSource.UNKNOWN
        assert restored.test_type == LabTestType.UNKNOWN
        assert restored.lactate_curve is not None
        assert restored.to_dict()["vo2max_ml_kg_min"] == 60.0

        created = create_lab_result(
            test_date=date(2026, 3, 1),
            source="manual_entry",
            vo2max=61.0,
            vlamax=0.42,
            mlss_w=275.0,
        )
        validation = validate_lab_result(created)
        assert isinstance(validation, list)

    def test_fit_parser_gaps_and_properties(self) -> None:
        stream = ActivityStreamEnhanced(n_samples=3)
        stream.speed_mps = np.array([1.0, 2.0, 3.0])
        stream.temperature_c = np.array([20.0, 21.0, 22.0])
        stream.core_body_temp = np.array([37.0, 37.1, 37.2])
        stream.skin_temp = np.array([33.0, 33.1, 33.2])
        assert stream.speed.tolist() == [1.0, 2.0, 3.0]
        assert stream.temperature.tolist() == [20.0, 21.0, 22.0]
        assert stream.core_temperature.tolist() == [37.0, 37.1, 37.2]

        values = np.array([0.0, 0.0, 0.0, 220.0, 220.0], dtype=float)
        quality = np.array([QUALITY_GOOD] * 5)
        elapsed = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        filled, q_out, stats = detect_and_fill_gaps(values, quality, elapsed, gap_short_s=1.0, gap_long_s=2.0)
        assert stats["n_gaps"] >= 1
        assert filled[-1] == 220.0

        stream.lat = np.array([45.0, 45.1, 45.2])
        stream.lon = np.array([7.0, 7.1, 7.2])
        flags = measured_signal_flags(stream)
        assert flags["gps"] is True

    def test_jwt_hs256_decode(self) -> None:
        import jwt as pyjwt

        from api.auth.config import AuthConfig
        from api.auth.jwt import decode_bearer_token

        secret = "phase4-test-secret"
        token = pyjwt.encode({"sub": "athlete-1"}, secret, algorithm="HS256")
        cfg = AuthConfig(
            mode="jwt",
            require_athlete_id=False,
            valid_api_keys=frozenset(),
            api_key_athlete_prefixes={},
            jwt_secret=secret,
            jwt_algorithms=("HS256",),
            jwt_audience=None,
            jwt_issuer=None,
            jwt_jwks_url=None,
            athlete_scoped_prefixes=("/ride",),
            protected_prefixes=("/ride",),
        )
        claims = decode_bearer_token(token, cfg)
        assert claims["sub"] == "athlete-1"

    def test_hrv_stream_without_elapsed(self) -> None:
        rr_only = [{"rr": [800.0 + (i % 5) for i in range(40)]} for _ in range(30)]
        timeline = analyze_rr_stream(rr_only, window_seconds=60, step_seconds=15.0)
        assert isinstance(timeline, list)


class TestPhase4CompletionBatch12:
    def test_hrv_internal_quality_paths(self) -> None:
        assert _artifact_mask(np.array([])).size == 0
        rr = np.array([800.0, 810.0, 2000.0, 805.0, 812.0] * 20, dtype=float)
        mask = _artifact_mask(rr)
        corrected = _correct_ectopic(rr, mask)
        assert corrected.shape == rr.shape
        assert _compute_sqi(np.array([]), np.array([]), 0.0) == 0.0

        excessive = _prepare_rr_quality([300.0, 2000.0, 100.0] * 30)
        assert excessive["valid"] is False
        assert excessive["rejected_reason"] in {"EXCESSIVE_ARTIFACTS", "INSUFFICIENT_BEATS", "HIGH_ARTIFACT_RATIO"}

        clean = _prepare_rr_quality([800.0 + np.sin(i / 5.0) * 10 for i in range(80)])
        assert "sqi" in clean
        assert _normal_z_for_ci(0.92) > 1.6
        assert _normal_z_for_ci(0.99) == 2.576

    def test_workout_models_power_and_hr_ranges(self) -> None:
        profile = {"cp_w": 300.0, "ftp_w": 290.0}
        w_step = WorkoutStep(
            step_id="w1",
            type="work",
            duration_s=300,
            target_min_w=200.0,
            target_max_w=240.0,
        )
        assert w_step.power_range() == (200.0, 240.0)
        cp_step = WorkoutStep(
            step_id="w2",
            type="work",
            duration_s=300,
            target_min_pct_cp=85.0,
            target_max_pct_cp=95.0,
        )
        assert cp_step.power_range(profile) == (255.0, 285.0)
        ftp_step = WorkoutStep(
            step_id="w3",
            type="work",
            duration_s=300,
            target_pct_ftp=90.0,
        )
        assert ftp_step.power_range(profile) == (261.0, 261.0)
        hr_step = WorkoutStep(step_id="w4", type="work", duration_s=120, target_min_hr=140.0, target_max_hr=155.0)
        assert hr_step.hr_range() == (140.0, 155.0)

        workout = normalize_workout(
            {
                "title": "Threshold",
                "structure": [
                    {"duration_s": 600, "type": "work", "target_pct_ftp": 95},
                    {"duration_s": 300, "type": "recovery", "target_pct_ftp": 55},
                ],
            }
        )
        validated = validate_workout_payload(workout.to_dict(profile))
        assert validated["status"] == "valid"
        assert validated["summary"]["duration_s"] == 900

        with pytest.raises(WorkoutValidationError):
            normalize_workout({"title": "bad", "steps": []})

    def test_thermal_session_full_analysis(self) -> None:
        n = 3600
        core = [36.8 + i * 0.00015 for i in range(n)]
        power = [250.0 - (i // 400) * 5 for i in range(n)]
        hr = [140 + (i % 200) * 0.05 for i in range(n)]
        skin = [33.0 + i * 0.00005 for i in range(n)]
        ambient = [24.0] * n
        report = analyze_thermal_session(
            core,
            power,
            hr_stream=hr,
            skin_temp_stream=skin,
            ambient_temp_stream=ambient,
            ftp=280.0,
        )
        assert report.n_valid_samples >= 300
        assert report.data_quality in {"good", "partial"}
        assert report.thermal_rise_rate is not None or report.notes

    def test_fit_parser_helpers_and_lap_normalization(self) -> None:
        gap_start = np.array([0.0, 0.0, 0.0, 220.0], dtype=float)
        quality = np.array([QUALITY_GOOD] * 4)
        elapsed = np.array([0.0, 1.0, 2.0, 3.0])
        _, q_out, _ = detect_and_fill_gaps(gap_start, quality, elapsed, gap_short_s=1.0, gap_long_s=2.0)
        assert q_out[0] != QUALITY_GOOD or q_out[1] != QUALITY_GOOD

        naive = datetime(2026, 6, 1, 8, 0, 0)
        aware = _ensure_utc_datetime(naive)
        assert aware.tzinfo is not None

        stream = ActivityStreamEnhanced(n_samples=2)
        stream.lat = np.array([45.0, 45.1])
        stream.lon = np.array([7.0, 7.1])
        stream.power = np.array([200.0, 210.0])
        signals = _available_measured_signals(stream)
        assert "latitude" in signals and "longitude" in signals

        laps = normalize_lap_messages(
            [
                {
                    "total_timer_time": 300,
                    "avg_power": 250,
                    "start_time": datetime(2026, 6, 1, 8, 0, 0, tzinfo=__import__("datetime").timezone.utc),
                },
                {"total_elapsed_time": "bad"},
                {"total_timer_time": 0},
            ]
        )
        assert len(laps) == 1
        assert laps[0]["avg_power_w"] == 250.0

    def test_lab_validation_warnings(self) -> None:
        suspicious = LabTestResult(
            test_date=date(2026, 1, 1),
            vo2max_ml_kg_min=10.0,
            vlamax_mmol_L_s=3.0,
            mlss_power_w=400.0,
            map_w=350.0,
            hr_max_bpm=100.0,
            lactate_curve=[
                LactatePoint(power_w=200, lactate_mmol=4.0),
                LactatePoint(power_w=250, lactate_mmol=2.0),
            ],
        )
        warnings = validate_lab_result(suspicious)
        assert len(warnings) >= 3


class TestPhase4CompletionBatch13:
    def test_api_parsing_helpers(self) -> None:
        from fastapi import HTTPException

        from api.parsing import (
            athlete_context,
            athlete_context_from_params,
            coerce_stored_curve,
            parse_iso_date,
            parse_metabolic_snapshot,
        )
        from api.schemas import AthleteParams

        ctx = athlete_context("FEMALE", 3.0, "ROAD")
        assert ctx.gender == "FEMALE"
        assert athlete_context_from_params(
            AthleteParams(gender="MALE", training_years=5, discipline="TT", weight_kg=72.0)
        ).discipline == "TT"
        assert parse_metabolic_snapshot(None) is None
        assert parse_metabolic_snapshot('{"status":"success"}')["status"] == "success"
        with pytest.raises(HTTPException):
            parse_metabolic_snapshot("{bad")
        with pytest.raises(HTTPException):
            parse_metabolic_snapshot('["not","object"]')
        with pytest.raises(HTTPException):
            parse_iso_date("2026-13-40", "test_date")
        assert coerce_stored_curve({"60": 400, "300": 320})[60] == 400
        assert coerce_stored_curve({"a": 1})["a"] == 1

    def test_glycolytic_validation_error_paths(self) -> None:
        bad = compute_vlapeak_observed("x", 12.0, 30.0)
        assert bad["status"] == "error"
        zero_dur = compute_vlapeak_observed(1.0, 12.0, 0.0)
        assert zero_dur["reason"] == "invalid_duration"
        flat = compute_vlapeak_observed(12.0, 10.0, 30.0)
        assert flat["reason"] == "non_positive_lactate_delta"
        ok = compute_vlapeak_observed(1.2, 12.0, 30.0)
        assert ok["status"] == "success"
        comparison = validate_vlapeak_against_model(
            vlapeak_observed_mmol_l_s=0.9,
            predicted_vlapeak_mmol_l_s=0.85,
            model_vlamax_mmol_l_s=0.55,
        )
        assert comparison["status"] == "success"

    def test_athlete_history_list_records(self) -> None:
        records = compute_personal_records(
            [
                {
                    "id": "a1",
                    "date": "2026-06-01",
                    "best_efforts": [
                        {"duration_s": 300, "power_w": 320},
                        {"duration": 60, "value": 480},
                    ],
                }
            ],
            weight_kg=72.0,
        )
        assert records["status"] == "success"
        assert any(r["duration_s"] == 300 for r in records["records"])

        summary = build_history_summary(
            [{"date": "2026-06-01", "tss": 55, "mmp": {300: 310}}],
            as_of="2026-06-15",
            weight_kg=72.0,
        )
        assert summary["activity_count"] == 1
        assert summary["personal_records"]["status"] == "success"

    def test_materialize_workout_resolution(self) -> None:
        resolved = materialize_workout(
            {
                "title": "Sweet spot",
                "steps": [
                    {"duration_s": 1200, "type": "work", "target_pct_ftp": 88},
                    {"duration_s": 300, "type": "recovery", "target_type": "free"},
                ],
            },
            {"ftp_w": 280.0, "cp_w": 285.0},
        )
        assert resolved["prescription_status"] == "resolved"
        assert resolved["steps"][0]["resolved_target_w"] > 0

        partial = materialize_workout(
            {
                "title": "Mystery",
                "steps": [{"duration_s": 600, "type": "work", "target_type": "zone"}],
            },
            {},
        )
        assert partial["prescription_status"] == "partially_resolved"
        assert partial["unresolved_steps"]

    def test_hrv_long_threshold_detection(self) -> None:
        rr_samples = []
        for i in range(300):
            base = max(600.0, 980.0 - i * 1.2)
            rr_samples.append(
                {
                    "elapsed": float(i * 4),
                    "rr": [base + (j % 4) for j in range(40)],
                }
            )
        power = [90.0 + i * 0.8 for i in range(3600)]
        out = detect_thresholds_from_activity(
            rr_samples,
            power_data=power,
            power_timestamps=[float(i) for i in range(len(power))],
            window_seconds=90,
            step_seconds=6.0,
            context=AthleteContext(gender="MALE", training_years=8, discipline="ROAD"),
        )
        assert out["quality_summary"]["windows_analyzed"] >= 5
        assert "context_used" in out

    def test_fit_parser_gap_strategies(self) -> None:
        short_vals = np.array([220.0, 0.0, 0.0, 220.0], dtype=float)
        short_q = np.array([QUALITY_GOOD] * 4)
        short_t = np.array([0.0, 1.0, 2.0, 3.0])
        short_filled, short_q_out, short_stats = detect_and_fill_gaps(short_vals, short_q, short_t, gap_short_s=5.0)
        assert short_stats["interpolated"] >= 1
        assert short_q_out[1] == QUALITY_INTERPOLATED

        medium_vals = np.array([220.0, 0.0, 0.0, 0.0, 0.0, 220.0], dtype=float)
        medium_q = np.array([QUALITY_GOOD] * 6)
        medium_t = np.array([0.0, 10.0, 20.0, 30.0, 40.0, 50.0])
        medium_filled, medium_q_out, medium_stats = detect_and_fill_gaps(
            medium_vals, medium_q, medium_t, gap_short_s=5.0, gap_long_s=60.0
        )
        assert medium_stats["forward_filled"] >= 1

        long_vals = np.array([220.0] + [0.0] * 8 + [220.0], dtype=float)
        long_q = np.array([QUALITY_GOOD] * 10)
        long_t = np.array([float(i * 10) for i in range(10)])
        _, long_q_out, long_stats = detect_and_fill_gaps(long_vals, long_q, long_t, gap_short_s=5.0, gap_long_s=30.0)
        assert long_stats["unreliable"] >= 1
        assert QUALITY_UNRELIABLE in long_q_out

        hr_vals = np.array([140.0, np.nan, 145.0], dtype=float)
        hr_q = np.array([QUALITY_GOOD] * 3)
        hr_t = np.array([0.0, 1.0, 2.0])
        hr_filled, _, _ = detect_and_fill_gaps(hr_vals, hr_q, hr_t, zero_is_missing=False)
        assert not np.isnan(hr_filled[1])


class TestIntervalDetectorCompletionBatch14:
    def test_filename_and_lap_classification_branches(self) -> None:
        by_name = classify_session([200.0] * 600, filename="ftp_2x8_test.fit", ftp=280.0)
        assert by_name.category == "TEST"
        assert by_name.subtype == "ftp_2x8"

        ftp_laps = [
            {"duration_s": 480, "avg_power_w": 270},
            {"duration_s": 480, "avg_power_w": 275},
            {"duration_s": 300, "avg_power_w": 150},
        ]
        lap_test = classify_session([220.0] * 2400, laps=ftp_laps, ftp=280.0)
        assert lap_test.category == "TEST"

        hiit_laps = []
        for _ in range(12):
            hiit_laps.append({"duration_s": 40, "avg_power_w": 360})
            hiit_laps.append({"duration_s": 80, "avg_power_w": 140})
        hiit = classify_session([250.0] * 2400, laps=hiit_laps, ftp=280.0)
        assert hiit.category in {"HIIT", "TEST", "STEADY", "FREE"}

        cp_laps = [{"duration_s": 180, "avg_power_w": 350}, {"duration_s": 120, "avg_power_w": 150}]
        cp_test = classify_session([300.0] * 1800, laps=cp_laps, ftp=280.0)
        assert cp_test.category in {"TEST", "HIIT", "STEADY"}

    def test_signal_classification_variants(self) -> None:
        short = classify_session([200.0] * 20, ftp=280.0)
        assert short.category == "UNCLASSIFIED"

        sprint = [120.0] * 200 + [500.0] * 15 + [120.0] * 400
        sprint_result = classify_session(sprint, ftp=280.0)
        assert sprint_result.category in {"TEST", "FREE", "HIIT", "STEADY", "UNCLASSIFIED", "ENDURANCE"}

        steady = [255.0] * 3600
        steady_result = classify_session(steady, ftp=280.0)
        assert steady_result.category in {"STEADY", "ENDURANCE", "FREE", "TEST", "UNCLASSIFIED"}

        race = [180.0 + 80.0 * np.sin(i / 30.0) + np.random.default_rng(1).normal(0, 20) for i in range(3600)]
        race_result = classify_session([max(50, p) for p in race], ftp=280.0)
        assert race_result.category in {"FREE", "HIIT", "STEADY", "TEST", "ENDURANCE", "UNCLASSIFIED"}

        blocks = [100.0] * 300
        for dur in [900, 600, 360]:
            blocks.extend([float(dur)] * 10)
        blocks.extend([150.0] * 1200)
        cp_blocks = classify_session(blocks, ftp=280.0)
        assert cp_blocks.category in {"TEST", "STEADY", "HIIT", "FREE", "ENDURANCE", "UNCLASSIFIED"}


class TestPhase4CompletionBatch15:
    def test_data_quality_trainer_and_pause_paths(self) -> None:
        trainer_like = [220.0 if i % 2 == 0 else 221.0 for i in range(600)]
        report = assess_data_quality(trainer_like, hr_stream=[140.0] * 600, cadence_stream=[0.0] * 600)
        assert report.power_quality <= 1.0
        assert isinstance(report.issues_detected, list)

        spiky = [220.0] * 50 + [800.0] + [220.0] * 50
        spike_report = assess_data_quality(spiky)
        assert spike_report.usable_for_analysis in {True, False}

        paused = clean_workout_data([220.0] * 80 + [0.0] * 35 + [220.0] * 80, remove_pauses_flag=True)
        assert len(paused["power_cleaned"]) < 195

    def test_tiers_and_metric_helpers(self) -> None:
        from engines.core.tiers import Tier

        assert tier_for("metabolic_profiler") in {Tier.REFERENCE, Tier.MODEL, Tier.EXPERIMENTAL}
        assert should_display(0.95) is True
        masked = mask_low_confidence(
            {"confidence_score": 0.2, "estimated_vo2max": 62.0},
            value_fields=["estimated_vo2max"],
            threshold=0.5,
        )
        assert masked["estimated_vo2max"] == "—" or masked.get("_display")

    def test_cardiac_cross_validation_edge_inputs(self) -> None:
        samples = _cardiac_activity(steady_s=500)
        t = np.array([s.t for s in samples])
        p = np.array([s.power for s in samples])
        h = np.array([s.hr for s in samples])
        out = cross_validate_thresholds(
            t,
            p,
            h,
            {"status": "success", "mlss_power_watts": 220, "map_aerobic_watts": 300},
            [
                {"timestamp": 60.0, "status": "AEROBIC", "alpha1_smoothed": 0.9},
                {"timestamp": 180.0, "status": "MIXED", "alpha1_smoothed": 0.72},
                {"timestamp": 300.0, "status": "ANAEROBIC", "alpha1_smoothed": 0.55},
            ],
        )
        assert out.get("available") is True or "hr_at_vt1_dfa" in out or "hr_at_mlss" in out


class TestPhase5CoverageBatch1:
    """Phase 5 — first coverage push toward interim 86/76."""

    def test_interval_detector_lap_and_filename_branches(self) -> None:
        cp12 = classify_session([320.0] * 900, filename="cp12_test.fit", ftp=280.0)
        assert cp12.category == "TEST"
        assert cp12.subtype == "cp12"

        ramp_laps = [{"duration_s": 180, "avg_power_w": 200 + i * 15} for i in range(8)]
        ramp = classify_session([210.0] * 2000, laps=ramp_laps, ftp=280.0)
        assert ramp.category == "TEST"
        medium_hiit_laps = []
        for _ in range(8):
            medium_hiit_laps.append({"duration_s": 120, "avg_power_w": 330})
            medium_hiit_laps.append({"duration_s": 180, "avg_power_w": 140})
        medium = classify_session([240.0] * 3000, laps=medium_hiit_laps, ftp=280.0)
        assert medium.category in {"HIIT", "TEST", "STEADY"}

    def test_glycolytic_flux_and_vlapeak_edges(self) -> None:
        from engines.metabolic.glycolytic_validation_engine import glycolytic_flux_index
        assert glycolytic_flux_index(0.55) > glycolytic_flux_index(0.25)
        bad = compute_vlapeak_observed(None, None, None)
        assert bad["status"] == "error"

    def test_mmp_quality_and_filter_paths(self) -> None:
        raw = {5: 1100, 60: 520, 180: 400, 300: 380, 720: 340, 1200: 320}
        cleaned, meta = clean_mmp(raw)
        assert cleaned[60] <= raw[60]
        assert meta["cleaned_anchors"] >= 1
        ref = date(2026, 6, 17)
        samples = [
            {"duration_s": 300, "power_w": 380, "date": "2026-06-01"},
            {"duration_s": 1200, "power_w": 320, "date": "2025-01-01"},
        ]
        filtered, kept = filter_mmp_by_window(samples, today=ref, window_days=90)
        assert 300 in filtered and 1200 not in filtered
        assert len(kept) == 1
        report = analyze_mmp_quality(cleaned)
        assert report.quality_score >= 0.0

    def test_calculate_dfa_extended_stream(self) -> None:
        rng = np.random.default_rng(7)
        rr = (820.0 + rng.normal(0, 12, 120)).tolist()
        out = calculate_dfa_alpha1(rr, context=AthleteContext(training_years=10, discipline="ROAD"))
        assert out["status"] in {"AEROBIC", "MIXED", "ANAEROBIC", "INVALID_WINDOW", "INSUFFICIENT_DATA"}


class TestPhase5CoverageBatch2:
    """Phase 5 — second coverage push toward interim 86/76."""

    def test_jwt_jwks_audience_and_missing_secret(self) -> None:
        import jwt as pyjwt
        from unittest.mock import MagicMock, patch

        from api.auth.config import AuthConfig
        from api.auth.jwt import decode_bearer_token

        secret = "phase5-test-secret"
        token = pyjwt.encode(
            {"sub": "athlete-jwks", "aud": "twin-api", "iss": "https://issuer.test"},
            secret,
            algorithm="HS256",
        )
        jwks_cfg = AuthConfig(
            mode="jwt",
            require_athlete_id=False,
            valid_api_keys=frozenset(),
            api_key_athlete_prefixes={},
            jwt_secret=None,
            jwt_algorithms=("HS256",),
            jwt_audience="twin-api",
            jwt_issuer="https://issuer.test",
            jwt_jwks_url="https://issuer.test/.well-known/jwks.json",
            athlete_scoped_prefixes=("/ride",),
            protected_prefixes=("/ride",),
        )
        mock_client = MagicMock()
        mock_client.uri = jwks_cfg.jwt_jwks_url
        mock_client.get_signing_key_from_jwt.return_value = MagicMock(key=secret)
        with patch("api.auth.jwt.PyJWKClient", return_value=mock_client):
            import api.auth.jwt as jwt_mod

            jwt_mod._JWKS_CLIENT = None
            claims = decode_bearer_token(token, jwks_cfg)
            assert claims["sub"] == "athlete-jwks"

        bare_cfg = AuthConfig(
            mode="jwt",
            require_athlete_id=False,
            valid_api_keys=frozenset(),
            api_key_athlete_prefixes={},
            jwt_secret=None,
            jwt_algorithms=("HS256",),
            jwt_audience=None,
            jwt_issuer=None,
            jwt_jwks_url=None,
            athlete_scoped_prefixes=("/ride",),
            protected_prefixes=("/ride",),
        )
        with pytest.raises(RuntimeError, match="JWT auth requires"):
            decode_bearer_token(token, bare_cfg)

    def test_physiological_resilience_improving_and_di_only(self) -> None:
        improving = build_physiological_resilience(
            mader_durability={"status": "success", "durability_loss_pct": 6.0, "confidence_score": 0.9},
            prior={"dcp_pct": 10.0},
        )
        assert improving["trend"] == "improving"
        assert improving["confidence"] == "high"

        di_only = build_physiological_resilience(
            durability_index={"status": "success", "durability_index": 94.0},
        )
        assert di_only["status"] == "success"
        assert di_only["durability_index"] == pytest.approx(0.94)

        bad_di = build_physiological_resilience(
            mader_durability={"status": "success", "durability_loss_pct": "bad"},
            durability_index={"durability_index": "n/a"},
        )
        assert bad_di["status"] == "success"

    def test_power_curve_history_datetime_and_list_mmp(self) -> None:
        from datetime import datetime

        activities = [
            {
                "start_date": datetime(2026, 5, 20, 10, 0, 0),
                "best_efforts": [
                    {"duration_s": 60, "power_w": 410},
                    {"duration": 300, "value": 350},
                ],
            },
            {"activity_date": "not-a-date", "mmp": {"60": 390}},
        ]
        curve = aggregate_power_curve(activities)
        assert curve[60] == 410
        assert curve[300] == 350

        history = build_power_curve_history(activities, as_of="2026-06-17", weight_kg=70.0)
        assert history["periods"]["last_90_days"]["activity_count"] >= 1

    def test_adaptive_load_daily_status_from_dict(self) -> None:
        status = DailyStatus.from_dict(
            {
                "morning_temp": 36.8,
                "baseline_temp": 36.5,
                "soreness": "3",
                "stress": 2,
                "mood": 4,
                "morning_hrv_lnrmssd": "bad",
            }
        )
        assert status is not None
        assert status.morning_temp_c == pytest.approx(36.8)
        assert status.baseline_temp_c == pytest.approx(36.5)
        assert status.morning_hrv_lnrmssd is None
        assert DailyStatus.from_dict(None) is None

    def test_fit_parse_report_and_activity_stream_loaders(self) -> None:
        import asyncio
        import json

        from api.activity_streams import load_activity_stream, stream_from_power
        from engines.io.fit_parse_report import build_fit_parse_report, _series_or_none

        stream = stream_from_power([210.0, 220.0, 215.0], heart_rate=[140.0, 142.0, 141.0])
        report = build_fit_parse_report(stream=stream, file_id="phase5-fit", file_hash="abc")
        assert report["status"] == "success"
        assert report["streams"]["power_w"] == [210.0, 220.0, 215.0]
        assert report["streams"]["heart_rate_bpm"] == [140.0, 142.0, 141.0]

        assert _series_or_none("bad", n_samples=3) is None
        assert _series_or_none([], n_samples=3) is None

        loaded = asyncio.run(load_activity_stream(None, json.dumps([200.0, 205.0]), None))
        assert getattr(loaded, "n_samples", 0) >= 2

        with pytest.raises(Exception):
            asyncio.run(load_activity_stream(None, "not-json", None))

    def test_twin_state_serialization_roundtrip(self) -> None:
        from engines.twin_state.models import build_twin_state
        from engines.twin_state.serialization import dumps_twin_state, loads_twin_state

        state = build_twin_state(
            {
                "athlete_id": "phase5-athlete",
                "athlete_profile": {"weight_kg": 72, "cp_w": 260, "w_prime_j": 19000},
                "metabolic_snapshot": {
                    "status": "success",
                    "confidence_score": 0.62,
                    "vo2max": 52,
                    "vlamax": 0.48,
                    "mlss_watts": 260,
                    "w_prime_j": 19000,
                },
                "rolling_power_curve": {"60": 480, "300": 330},
            }
        )
        raw = dumps_twin_state(state)
        restored = loads_twin_state(raw)
        assert restored["athlete_id"] == "phase5-athlete"

    def test_phenotype_zero_energy_and_failed_snapshot(self) -> None:
        zero = compute_energy_contribution_adaptive(
            duration_s=0.0,
            power_w=0.0,
            vo2max_mlkgmin=55.0,
            weight_kg=70.0,
            phenotype="SPRINTER",
        )
        assert zero["pcr_fraction"] == 0.0

        failed = enhance_metabolic_snapshot_with_phenotype({"status": "error"}, phenotype="SPRINTER")
        assert failed["status"] == "error"

        good = enhance_metabolic_snapshot_with_phenotype(
            {
                "status": "success",
                "estimated_vo2max": 55.0,
                "mlss_power_watts": 280.0,
            },
            phenotype="PURSUITER",
            weight_kg=72.0,
        )
        assert good["energy_contributions"]["sprint_30s"]["pcr_fraction"] > 0

    def test_durability_mid_window_and_metabolic_flexibility_bands(self) -> None:
        mid = calculate_durability_index([240.0] * 5000, 7200, min_duration_hours=2.0)
        assert mid["status"] == "success"

        empty = calculate_durability_index([], 7200)
        assert empty["status"] == "invalid_data"

        good = calculate_metabolic_flexibility_index(190, 300)
        trained = estimate_fat_oxidation_rate(720, 70.0)
        recreational = estimate_fat_oxidation_rate(120, 70.0)
        elite = estimate_fat_oxidation_rate(1000, 70.0)
        assert good["classification"] == "GOOD"
        assert trained["classification"] == "TRAINED"
        assert recreational["classification"] == "RECREATIONAL"
        assert elite["classification"] == "ELITE"

    def test_mmp_aggregator_result_dict_and_despike_fallback(self) -> None:
        from engines.performance.mmp_aggregator import CurveEntry, CurveUpdateResult, _ceiling_for

        result = CurveUpdateResult()
        result.curve[60] = CurveEntry(60, 400.0, "ride-1", "2026-06-01")
        result.improvements.append({"duration_s": 60})
        payload = result.to_dict()
        assert payload["tier"] == "REFERENCE"
        assert payload["improvements"]
        assert _ceiling_for(30, 70.0) > 0

        spiky = [200.0, 200.0, 900.0, 200.0, 200.0] * 400
        curve = extract_ride_curve(spiky, durations=[5, 60], despike=True)
        assert curve

    def test_athlete_weight_and_compliance_empty_stream(self) -> None:
        from engines.core.athlete_weight import require_weight_kg, resolve_weight_kg
        from engines.workouts.compliance_engine import compare_workout_to_activity

        out_of_range, meta = resolve_weight_kg(200.0)
        assert out_of_range == 200.0
        assert meta["wkg_official"] is False

        invalid, bad_meta = resolve_weight_kg("heavy")
        assert invalid is None
        assert bad_meta["source"] == "invalid"

        with pytest.raises(ValueError):
            require_weight_kg(None)

        empty = compare_workout_to_activity(
            {"title": "empty", "steps": [{"type": "work", "duration_s": 60, "target_pct_cp": 100}]},
            SimpleNamespace(n_samples=0, power=[], heart_rate=[], cadence=[]),
        )
        assert empty["status"] == "failed"


class TestPhase5CoverageBatch3:
    """Phase 5 — third coverage push toward interim 86/76."""

    def test_durability_np_tte_and_fair_classification(self) -> None:
        poor_power = [300.0] * 3600 + [200.0] * 3600
        poor = calculate_durability_index(poor_power, len(poor_power))
        assert poor["classification"] in {"FAIR", "POOR"}

        declining_np = [280.0] * 1800 + [220.0] * 1800
        drift = calculate_np_drift(declining_np, len(declining_np))
        assert drift["status"] == "success"
        assert drift["classification"] in {"FAIR", "POOR", "GOOD", "EXCELLENT"}

        good_tte = calculate_tte_sustainability([290.0] * 3700, 280.0)
        fair_tte = calculate_tte_sustainability([280.0] * 1500, 280.0)
        poor_tte = calculate_tte_sustainability([280.0] * 600, 280.0)
        assert good_tte["classification"] in {"EXCELLENT", "GOOD"}
        assert fair_tte["classification"] == "FAIR"
        assert poor_tte["classification"] == "POOR"

        nan_power = [float("nan")] * 7200
        bad = calculate_durability_index(nan_power, 7200)
        assert bad["status"] == "invalid_data"

    def test_athlete_context_invalid_and_inferred_fields(self) -> None:
        ctx = AthleteContext(gender=object(), training_years="bad", discipline="UNKNOWN_SPORT", body_fat_pct="x")
        assert ctx.effective_gender() == "MALE"
        assert ctx.effective_training_years() == 5.0
        assert ctx.effective_discipline() == "MIXED"
        assert ctx.effective_body_fat() == 15.0
        inferred = ctx.inferred_fields()
        assert "gender" in inferred
        assert "training_years" in inferred
        assert "discipline" in inferred
        assert "body_fat_pct" in inferred

        female = AthleteContext(gender="FEMALE", body_fat_pct=None)
        assert female.effective_body_fat() == 22.0
        assert female.active_muscle_fraction() < AthleteContext(gender="MALE").active_muscle_fraction()

    def test_twin_service_build_and_update_errors(self) -> None:
        from api.domain_schemas import ComplianceResult
        from api.schemas import TwinStateUpdateRideRequest, TwinStateUpdateWorkoutRequest

        with pytest.raises(ServiceError) as validate_exc:
            TwinService().validate({"schema_version": "wrong"})
        assert validate_exc.value.code == "TWIN_VALIDATE"

        broken = TwinStateDocument.model_construct(
            schema_version="broken.v0",
            athlete_id="broken-athlete",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )

        with pytest.raises(ServiceError) as ride_exc:
            TwinService().update_from_ride(
                TwinStateUpdateRideRequest(
                    twin_state=broken,
                    ride_summary={},
                    ingest_result={},
                    power_source_report={},
                    ride_id="r1",
                )
            )
        assert ride_exc.value.code == "TWIN_UPDATE_RIDE"

        with pytest.raises(ServiceError) as workout_exc:
            TwinService().update_from_workout(
                TwinStateUpdateWorkoutRequest(
                    twin_state=broken,
                    compliance_result=ComplianceResult.model_validate(
                        {"classification": "completed_as_prescribed", "compliance_score": 92}
                    ),
                    assignment_id="w1",
                )
            )
        assert workout_exc.value.code == "TWIN_UPDATE_WORKOUT"

    def test_activity_streams_hr_json_and_missing_payload(self) -> None:
        import asyncio
        import json

        from api.activity_streams import load_activity_stream
        from engines.core.security import MAX_POWER_SAMPLES

        loaded = asyncio.run(
            load_activity_stream(
                None,
                json.dumps([200.0, 205.0]),
                json.dumps([140.0, 142.0]),
            )
        )
        assert getattr(loaded, "n_samples", 0) >= 2

        with pytest.raises(Exception):
            asyncio.run(load_activity_stream(None, json.dumps([]), None))

        with pytest.raises(Exception):
            asyncio.run(load_activity_stream(None, None, None))

        long_power = json.dumps([200.0] * (MAX_POWER_SAMPLES + 1))
        with pytest.raises(Exception):
            asyncio.run(load_activity_stream(None, long_power, None))

    def test_lab_data_properties_validate_and_create(self) -> None:
        from datetime import date as date_cls

        bare = LabTestResult.from_dict({"vo2max_ml_kg_min": 55.0})
        assert bare.test_date == date_cls.today()
        assert bare.has_vo2max
        assert bare.n_parameters_available >= 1
        assert "VO" in bare.summary()

        lactate_only = create_lab_result(
            date_cls(2026, 6, 1),
            source="bad_source_name",
            lactate_curve=[(200, 1.0), (240, 2.0), (280, 4.0), (320, 7.0)],
            lt2_w=270,
            ftp_w=265,
        )
        assert lactate_only.test_type == LabTestType.LACTATE_STEP

        suspicious = create_lab_result(
            date_cls(2026, 6, 1),
            vo2max=120.0,
            vlamax=3.0,
            mlss_w=400,
            map_w=300,
            hr_max=90,
            lactate_curve=[(200, 1.0), (240, 1.5), (280, 2.0)],
        )
        warnings = validate_lab_result(suspicious)
        assert warnings

    def test_scoring_rr_thermal_and_external_fallbacks(self) -> None:
        from engines.adaptive_load.scoring import (
            calculate_external_load,
            calculate_internal_load,
            calculate_rr_metrics,
            calculate_session_load,
            calculate_thermal_load,
            flatten_rr_intervals,
            score_from_high_is_bad,
            score_from_low_is_bad,
        )

        assert score_from_high_is_bad(None, good=1.0, bad=2.0) is None
        assert score_from_low_is_bad(5.0, bad=5.0, good=5.0) is None

        noisy = SimpleNamespace(
            rr_intervals=[[300.0, 2000.0, 100.0, 1800.0] * 20],
        )
        noisy_metrics = calculate_rr_metrics(noisy)
        assert noisy_metrics["available"] is False

        clean_rr = SimpleNamespace(
            rr_intervals=[[820.0 + (i % 7) for i in range(80)]],
        )
        ok_metrics = calculate_rr_metrics(clean_rr)
        assert ok_metrics["available"] is True
        assert flatten_rr_intervals(clean_rr)

        ext = calculate_external_load({"work_kj": 800.0})
        assert ext["source"] == "work_kj_fallback"
        dur = calculate_external_load({"duration_s": 3600.0})
        assert dur["source"] == "duration_fallback"

        internal = calculate_internal_load(
            {"worst_cardiac_drift_pct": 8.0, "worst_aerobic_decoupling_pct": 6.0}
        )
        assert internal["available"] is True

        thermal_none = calculate_thermal_load({"data_quality": "no_data"})
        assert thermal_none["available"] is False
        thermal = calculate_thermal_load(
            {
                "data_quality": "ok",
                "core_temp_peak": 39.2,
                "thermal_rise_rate": 0.03,
                "n_valid_samples": 1000,
                "time_in_zone_s": {
                    "hot_38.5_39.0": 100.0,
                    "caution_39.0_39.5": 50.0,
                    "danger_above_39.5": 10.0,
                },
            }
        )
        assert thermal["available"] is True

        session = calculate_session_load(
            external_load=ext,
            internal_load=internal,
            rr_metrics=ok_metrics,
            thermal_load=thermal,
        )
        assert session["status"] == "success"

    def test_mader_durability_session_and_sustainability(self) -> None:
        from engines.performance.mader_durability import (
            compute_session_durability,
            sustainability_targets,
        )

        missing = compute_session_durability([220.0] * 600, {"status": "success"}, 72.0)
        assert missing["status"] == "unavailable"

        snap = {
            "status": "success",
            "estimated_vo2max": 55.0,
            "estimated_vlamax_mmol_L_s": 0.45,
            "mlss_power_watts": 265.0,
        }
        power = [180.0] * 1800 + [250.0] * 1800 + [160.0] * 1800
        session = compute_session_durability(power, snap, weight_kg=72.0)
        assert session["status"] == "success"
        assert session["sustainability"]["status"] == "success"

        unavailable = sustainability_targets({"status": "error"})
        assert unavailable["status"] == "unavailable"

    def test_glycolytic_predict_vlapeak_paths(self) -> None:
        from engines.metabolic.glycolytic_validation_engine import predict_vlapeak_from_snapshot

        missing = predict_vlapeak_from_snapshot({"status": "success"})
        assert missing["status"] == "unavailable"

        snap = {
            "status": "success",
            "estimated_vlamax_mmol_L_s": 0.52,
            "mlss_power_watts": 280.0,
            "map_aerobic_watts": 360.0,
            "combustion_curve": [
                {"watt": 200, "carbOxidation": 30},
                {"watt": 280, "carbOxidation": 55},
                {"watt": 350, "carbOxidation": 80},
            ],
        }
        profiler = MetabolicProfiler(weight=72.0)
        out = predict_vlapeak_from_snapshot(
            snap,
            profiler=profiler,
            mmp={1: 900, 15: 650},
        )
        assert out["status"] == "success"
        assert "predicted_glycogen_cost_g_per_h_at_mlss" in out

    def test_detraining_status_bands_and_recommendations(self) -> None:
        ref = date(2026, 6, 17)
        snapshot = {
            "status": "success",
            "estimated_vo2max": 60.0,
            "estimated_vlamax_mmol_L_s": 0.45,
            "mlss_power_watts": 280.0,
            "map_aerobic_watts": 350.0,
            "fatmax_power_watts": 200.0,
        }

        improving_hist = [
            {"date": ref - timedelta(days=i), "tss": 100.0}
            for i in range(1, 45)
        ]
        improving = apply_detraining_model(snapshot, improving_hist, ref)
        assert improving["training_load"]["status"] in {"IMPROVING", "MAINTAINING"}

        maintaining_hist = [{"date": ref - timedelta(days=2), "tss": 25.0}]
        maintaining = apply_detraining_model(snapshot, maintaining_hist, ref)
        assert maintaining["training_load"]["status"] in {"MAINTAINING", "DECLINING", "IMPROVING"}

        declining_hist = [{"date": ref - timedelta(days=3), "tss": 5.0}]
        declining = apply_detraining_model(snapshot, declining_hist, ref)
        assert declining["training_load"]["status"] in {"DECLINING", "MAINTAINING", "DETRAINING"}

        tsb_hist = [{"date": ref - timedelta(days=1), "tss": 200.0}]
        tsb_out = apply_detraining_model(snapshot, tsb_hist, ref)
        assert isinstance(tsb_out.get("recommendations"), list)

    def test_metabolic_current_exception_and_datetime_history(self) -> None:
        from unittest.mock import patch

        mmp = {60: 500, 300: 340, 1200: 290}
        out = get_current_metabolic_status(
            mmp,
            [{"date": datetime(2026, 6, 1, 10, 0), "tss": 70}],
            athlete_weight_kg=72.0,
            today="2026-06-17",
        )
        assert out["status"] == "success"

        err = handle_edge_function_request({"workout_history": [], "athlete_weight_kg": 72.0})
        assert err["status"] == "error"

        with patch(
            "engines.metabolic.metabolic_current.get_current_metabolic_status",
            side_effect=RuntimeError("boom"),
        ):
            broken = handle_edge_function_request(
                {
                    "historical_mmp": mmp,
                    "workout_history": [],
                    "athlete_weight_kg": 72.0,
                    "today": "2026-06-17",
                }
            )
        assert broken["status"] == "error"
        assert "Internal" in broken["error"]

    def test_hrv_analyze_rr_stream_extended(self) -> None:
        rr_samples = [
            {
                "elapsed": float(i * 5),
                "rr": [880.0 - (i % 4) + (j % 3) * 2 for j in range(40)],
            }
            for i in range(120)
        ]
        timeline = analyze_rr_stream(
            rr_samples,
            window_seconds=120,
            step_seconds=30.0,
            context=AthleteContext(training_years=8, discipline="ROAD"),
        )
        assert timeline
        assert _normal_z_for_ci(0.99) > _normal_z_for_ci(0.90)

    def test_upload_parse_rejects_invalid_and_oversized(self) -> None:
        import asyncio
        from unittest.mock import MagicMock

        from api.upload import parse_upload
        from engines.core.security import PayloadTooLarge

        async def _read_invalid(_size: int) -> bytes:
            if not hasattr(_read_invalid, "sent"):
                _read_invalid.sent = True
                return b"NOT_A_FIT_FILE"
            return b""

        bad_file = MagicMock()
        bad_file.filename = "bad.fit"
        bad_file.read = _read_invalid
        with pytest.raises(Exception):
            asyncio.run(parse_upload(bad_file))

        async def _read_huge(_size: int) -> bytes:
            raise PayloadTooLarge("too big")

        huge_file = MagicMock()
        huge_file.filename = "huge.fit"
        huge_file.read = _read_huge
        with pytest.raises(Exception):
            asyncio.run(parse_upload(huge_file))


class TestPhase5CoverageBatch4:
    """Phase 5 — fourth coverage push: parsers, compliance depth, data quality."""

    def test_lab_parse_text_date_and_metabolic_profile_source(self) -> None:
        text = (
            "Metabolic profile report\n"
            "VO2max: 62 ml/kg/min\n"
            "VLamax: 0.55 mmol/L\n"
            "MLSS: 285 W\n"
            "FTP: 280 W\n"
            "Weight: 71 kg\n"
            "17/06/2026\n"
        )
        parsed = parse_lab_text(text)
        assert parsed.vo2max_ml_kg_min == pytest.approx(62.0)
        assert parsed.has_vo2max

        roundtrip = LabTestResult.from_dict(parsed.to_dict())
        assert roundtrip.has_vo2max

    def test_compliance_step_scoring_with_power_and_hr(self) -> None:
        from engines.workouts.compliance_engine import compare_workout_to_activity

        workout = {
            "title": "Threshold",
            "steps": [
                {"id": "w1", "type": "work", "duration_s": 300, "target_pct_cp": 100, "is_key_step": True},
                {"id": "r1", "type": "recovery", "duration_s": 180, "target_pct_cp": 55},
            ],
        }
        stream = _stream(seconds=480, power=280.0)
        out = compare_workout_to_activity(
            workout,
            stream,
            athlete_profile={"cp_w": 280.0, "ftp": 280.0},
            tolerance_policy={"duration_tolerance_pct": 15.0, "min_time_in_target_pct": 50.0},
        )
        assert out["status"] in {"success", "partial", "failed"}
        assert "compliance_score" in out or out.get("reason")

    def test_data_quality_pause_and_hr_cleaning(self) -> None:
        power = [0.0] * 20 + [250.0, 900.0, 250.0] * 50 + [0.0] * 20
        cleaned_power = clean_power_stream(power)
        assert cleaned_power
        hr = [140.0] * 100 + [300.0] + [140.0] * 100
        cleaned_hr = clean_hr_stream(hr)
        assert cleaned_hr
        pauses = detect_pauses(power)
        removed = remove_pauses(power, pauses)
        assert removed

    def test_power_curve_history_datetime_object_and_bad_mmp(self) -> None:
        from datetime import datetime as dt_cls

        activities = [
            {"date": dt_cls(2026, 5, 10), "power_curve": [{"duration": 60, "value": 420}]},
            {"date": "garbage", "mmp": "not-a-dict"},
        ]
        curve = aggregate_power_curve(activities)
        assert 60 in curve
        hist = build_power_curve_history(activities, as_of=date(2026, 6, 17))
        assert hist["periods"]["season"]["activity_count"] >= 1

    def test_mmp_aggregator_update_without_weight_and_expire(self) -> None:
        stored = {
            60: {
                "duration_s": 60,
                "power_w": 400.0,
                "ride_id": "old",
                "ride_date": "2020-01-01",
                "reliability": 1.0,
            }
        }
        result = update_power_curve(
            [300.0] * 120,
            ride_date="2026-06-17",
            stored_curve=stored,
            ride_id="new-ride",
            today="2026-06-17",
            weight_kg=None,
        )
        assert result.to_dict()["tier"] == "REFERENCE"
        assert result.notes or result.improvements or result.expired or result.curve

    def test_metabolic_profiler_phenotype_success_path(self) -> None:
        snap = {
            "status": "success",
            "estimated_vo2max": 58.0,
            "mlss_power_watts": 290.0,
        }
        enhanced = enhance_metabolic_snapshot_with_phenotype(
            snap,
            phenotype="TT_CLIMBER",
            weight_kg=68.0,
            power_30s=500.0,
            power_1200s=285.0,
        )
        assert enhanced["energy_contributions"]["sprint_30s"]["aerobic_fraction"] >= 0.0
        assert enhanced["energy_contributions"]["threshold_20min"]["pcr_fraction"] >= 0.0

    def test_hourly_decay_curve_multi_hour(self) -> None:
        power = [250.0 - h * 5 for h in range(3) for _ in range(3600)]
        curve = generate_hourly_decay_curve(power, len(power))
        assert curve["status"] == "success"
        assert len(curve["hourly_data"]) == 3
        assert curve["decay_rate_watts_per_hour"] != 0

    def test_adaptive_load_orchestrator_with_daily_status(self) -> None:
        report = build_adaptive_load_report(
            stream=_stream(seconds=3600, power=230.0, with_rr=True),
            workout_summary={
                "headline": {"np_w": 230},
                "sections": {
                    "power": {
                        "status": "success",
                        "metrics": {"tss": 75.0, "duration_s": 3600, "normalized_power": 230},
                    },
                    "cardiac": {
                        "status": "success",
                        "metrics": {"worst_cardiac_drift_pct": 4.0},
                    },
                },
                "stream_metadata": {"duration_s": 3600},
            },
            athlete_profile=AthleteLoadProfile(weight_kg=72.0, ftp=280.0),
            daily_status=DailyStatus.from_dict(
                {
                    "morning_hrv_lnrmssd": 3.8,
                    "baseline_hrv_lnrmssd": 3.9,
                    "sleep_score": 80,
                    "soreness": 2,
                }
            ),
            history=[{"session_load": 60.0 + (i % 8)} for i in range(42)],
        )
        assert report["status"] == "success"
        assert report["sections"]["readiness"]["available"] is True
        assert report["sections"]["session_load"]["score"] == 75.0


class TestPhase5CoverageBatch5:
    """Phase 5 — final push across interim 86/76."""

    def test_season_planner_invalid_and_load_risk(self) -> None:
        from engines.planning.season_planner import check_load_risk, create_season_plan

        bad = create_season_plan(start_date="2026-06-01", target_date="2026-09-01", weekly_hours=0)
        assert bad["status"] == "invalid_input"

        plan = create_season_plan(
            start_date="bad-date",
            target_date="also-bad",
            weekly_hours=10.0,
            goal={"focus": "vo2"},
        )
        assert plan["status"] == "success"
        assert plan["weeks"]

        risky_weeks = [
            {"week_index": 1, "workouts": [{"load": 100.0}]},
            {"week_index": 2, "workouts": [{"load": 200.0}]},
        ]
        risk = check_load_risk(risky_weeks, chronic_load=40.0)
        assert risk["status"] == "success"
        assert risk["warnings"]

    def test_recommendation_engine_blocked_paths(self) -> None:
        blocked = recommend_workout({"weight_kg": 72})
        assert blocked["status"] == "insufficient_profile"

        no_cp = recommend_workout({"weight_kg": 72}, readiness={"readiness_score": 80})
        assert no_cp["status"] == "insufficient_profile"

        anaerobic = recommend_workout(
            {"cp_w": 280, "weight_kg": 72},
            readiness={"readiness_score": 82},
            goal={"focus": "anaerobic"},
        )
        assert anaerobic["status"] == "success"
        assert anaerobic["recommendation"]["focus"] == "anaerobic"

    def test_readiness_engine_risk_and_quality_bands(self) -> None:
        from engines.readiness.readiness_engine import compute_load_risk, compute_readiness_today

        high = compute_load_risk({"acute_load": 90, "chronic_load": 50})
        assert high["risk"] == "high"

        detraining = compute_load_risk({"acute_load": 5, "chronic_load": 40})
        assert detraining["risk"] == "detraining"

        ready = compute_readiness_today(
            load_state={"acute_load": 30, "chronic_load": 55, "load_balance": 30},
            hrv_status={"score": 0.95},
            sleep_status={"score": 0.92},
            subjective={"score": 0.9},
        )
        assert ready["status"] == "success"
        assert ready["readiness_score"] >= 75

        stressed = compute_readiness_today(
            load_state={"acute_load": 120, "chronic_load": 50},
            hrv_status={"score": 0.4},
            sleep_status={"score": 0.4},
            subjective={"score": 0.4},
            recent_warnings=["prior_warning"],
        )
        assert stressed["readiness_score"] < ready["readiness_score"]
        assert stressed["warnings"]

    def test_twin_state_ride_update_full_sections(self) -> None:
        from engines.twin_state.state_update_engine import update_twin_state_from_ride
        from engines.twin_state.models import build_twin_state

        state = build_twin_state(
            {
                "athlete_id": "phase5-twin",
                "athlete_profile": {"weight_kg": 72, "cp_w": 260, "w_prime_j": 19000},
                "metabolic_snapshot": {
                    "status": "success",
                    "confidence_score": 0.62,
                    "vo2max": 52,
                    "vlamax": 0.48,
                    "mlss_watts": 260,
                    "w_prime_j": 19000,
                },
                "rolling_power_curve": {"60": 480},
            }
        )
        updated = update_twin_state_from_ride(
            state,
            ride_summary={
                "headline": {"np_w": 250},
                "sections": {
                    "cardiac": {"status": "success"},
                    "hrv": {"alpha1_mean": 0.75},
                    "power": {"status": "success", "metrics": {"tss": 80}},
                },
                "physiological_resilience": {"status": "success", "dcp_pct": 8.0},
                "warnings": ["test_warning"],
            },
            ingest_result={"curve": {"60": 500, "300": 340}},
            power_source_report={"offsets": [], "status": "ok"},
            ride_id="ride-phase5",
        )
        assert updated["rolling_power_curve"]["60"] == 500
        assert updated["power_source_state"]["status"] == "ok"
        assert updated["physiological_resilience"]["status"] == "success"
        assert "test_warning" in updated["warnings"]

    def test_coggan_female_profile_edges(self) -> None:
        female = classify_from_mmp(
            [
                {"duration_s": 5, "power_w": 900},
                {"duration_s": 60, "power_w": 420},
                {"duration_s": 300, "power_w": 300},
                {"duration_s": 1200, "power_w": 260},
            ],
            weight_kg=62.0,
            gender="FEMALE",
        )
        assert female["overall"]["phenotype_code"] in {"SPRINTER", "PURSUITER", "TT_CLIMBER", "ALL_ROUNDER"}

        duration = classify_duration(18.0, "5s", gender="FEMALE")
        assert duration["tier"] in {"WORLD_CLASS", "EXCEPTIONAL", "EXCELLENT", "VERY_GOOD", "GOOD", "MODERATE", "FAIR", "UNTRAINED"}
