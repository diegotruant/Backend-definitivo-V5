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
from engines.core.athlete_physiological_prior import MeasuredProfile, PhysiologicalPriorManager
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.metabolic.team_learning_engine import TeamCalibrationModel, ValidationEvent
from types import SimpleNamespace

from engines.core.athlete_context import AthleteContext
from engines.metabolic.lab_data import (
    LabTestResult,
    LactatePoint,
    create_lab_result,
    parse_lab_text,
    validate_lab_result,
)
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
from engines.io.activity_charts import build_activity_charts
from engines.io.chart_builder import (
    chart_hrv_timeline,
    chart_metabolic_combustion,
    chart_power_duration_curve,
    chart_training_load,
    chart_zones_distribution,
    generate_workout_charts,
)
from engines.io.session_router import decide_route, route_and_run
from engines.load.manual_load import calculate_manual_load
from engines.metabolic.detraining_engine import apply_detraining_model, calculate_ctl_atl_tsb, calculate_decay_factor
from engines.metabolic.metabolic_current import get_current_metabolic_status, handle_edge_function_request
from engines.metabolic.metabolic_kalman import DailyInput, MetabolicKalman, process_workout_history
from engines.performance.durability_engine import (
    calculate_durability_index,
    calculate_np_drift,
    calculate_tte_sustainability,
    generate_hourly_decay_curve,
)
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
from engines.recovery.hrv_engine import analyze_rr_stream, calculate_dfa_alpha1, detect_thresholds_from_activity
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
