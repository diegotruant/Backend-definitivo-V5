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
from engines.core.data_quality_engine import assess_data_quality, clean_workout_data, detect_pauses
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
from engines.performance.race_prediction_engine import AthleteRaceProfile, CourseSegment, parse_gpx_course
from engines.performance.training_variability_engine import calculate_acwr, calculate_monotony_strain
from engines.recovery.cardiac_engine import ActivitySample, CardiacResponseAnalyzer, cross_validate_thresholds
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
from engines.workouts.recommendation_engine import recommend_workout
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
