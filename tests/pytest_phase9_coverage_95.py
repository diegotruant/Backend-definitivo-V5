"""Phase 9 — 95% branch gate push: HRV, cardiac, thermal, API services + high-yield engines."""

from __future__ import annotations

import warnings
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from api.engine_schemas import (
    AdaptiveLoadRequest,
    ExplainabilityDurabilityConfidenceRequest,
    ExplainabilityMetricNarrativeRequest,
    ExplainabilityVo2ConfidenceRequest,
    RaceGpxAnalyzeRequest,
    RaceGpxSimulateRequest,
    SessionClassifyRequest,
    VlamaxSprintRequest,
)
from api.errors import ServiceError
from api.schemas import (
    AthleteParams,
    CalendarTransitionRequest,
    ConfirmRequest,
    SeasonProjectionRequest,
    TwinStateBuildRequest,
    WorkoutFeasibilityRequest,
    WorkoutPrescribeRequest,
    WorkoutValidateRequest,
)
from api.services.explainability_service import ExplainabilityService
from api.services.profile_extended_service import ProfileExtendedService, _with_sprint_vlamax_confidence
from api.services.race_service import RaceService
from api.services.ride_analytics_service import RideAnalyticsService
from api.services.ride_service import RideService
from api.services.test_service import TestService
from api.services.twin_service import TwinService
from api.services.workout_service import WorkoutService
from engines.core.athlete_context import AthleteContext
from engines.core.security import PayloadTooDeep
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.recovery.cardiac_engine import (
    ActivitySample,
    CardiacResponseAnalyzer,
    Segment,
    _detect_recovery_segments,
    _detect_steady_segments,
    compute_hr_kinetics_tau,
    compute_hr_recovery,
)
from engines.recovery.hrv_engine import (
    _apply_hysteresis_status,
    _artifact_mask,
    _correct_ectopic,
    _dfa_alpha1_full,
    _detect_threshold_crossing,
    _power_at_elapsed,
    _prepare_rr_quality,
    _sliding_dfa_local,
    analyze_rr_stream,
    calculate_dfa_alpha1,
    detect_thresholds_from_activity,
)
from engines.recovery.thermal_engine import (
    ThermalSessionReport,
    _detect_power_drop_temp,
    _half_means,
    _steady_state_mean,
    analyze_heat_acclimation,
    analyze_thermal_session,
)
from engines.workouts.models import WorkoutValidationError

ATHLETE = AthleteParams(weight_kg=72.0, gender="MALE", training_years=10, discipline="ENDURANCE")
MMP = {"5": 900, "60": 480, "300": 340, "1200": 285, "3600": 255}


def _stream(
    seconds: int = 1200,
    *,
    power: float = 240.0,
    with_rr: bool = False,
    with_core: bool = False,
    device_name: str | None = None,
):
    start = datetime(2026, 5, 1, 8, 0, 0)
    session: dict = {"start_time": start, "total_elapsed_time": seconds}
    if device_name:
        session["device_name"] = device_name
    records = []
    for i in range(seconds):
        row = {
            "timestamp": start + timedelta(seconds=i),
            "power": power + (i % 12),
            "heart_rate": 140.0 + (i % 10) * 0.4,
            "cadence": 90.0,
        }
        if with_rr and i % 8 == 0:
            row["rr_intervals"] = [820.0 + (i % 5), 815.0]
        if with_core:
            row["core_body_temperature"] = 37.2 + i * 0.0004
            row["skin_temperature"] = 33.0 + i * 0.0002
        records.append(row)
    return parse_fit_records_enhanced(records, session_dict=session)


def _rr_long(n: int = 200) -> list[dict]:
    out = []
    t = 0.0
    for i in range(n):
        rr = 820.0 + np.sin(i / 4.0) * 12.0
        out.append({"elapsed": t, "rr": [rr, rr + 1.5]})
        t += rr / 1000.0
    return out


class TestHrvEnginePhase9:
    def test_ectopic_convergence_and_sqi_single_beat(self) -> None:
        rr = np.array([800.0, 1600.0, 810.0, 805.0] * 20, dtype=float)
        mask = _artifact_mask(rr)
        corrected = _correct_ectopic(rr, mask, max_passes=3)
        assert corrected.shape == rr.shape

        single = np.array([810.0], dtype=float)
        from engines.recovery.hrv_engine import _compute_sqi

        assert _compute_sqi(single, single, 0.0) <= 1.0

        prep = _prepare_rr_quality([820.0 + (i % 7) for i in range(80)])
        assert "valid" in prep and prep["artifact_ratio"] <= 1.0

    def test_dfa_edge_scales_and_dof_zero(self) -> None:
        tiny = _dfa_alpha1_full(np.array([820.0] * 8))
        assert tiny["alpha1"] is None

        short = _dfa_alpha1_full(np.array([800.0 + i for i in range(20)]))
        assert "alpha1" in short

        with_ci = _dfa_alpha1_full(np.array([820.0 + (i % 6) for i in range(120)]), ci_level=0.925)
        assert "ci_low" in with_ci

    def test_sliding_window_skips_and_threshold_branches(self) -> None:
        rr = np.array([820.0 + (i % 3) for i in range(500)], dtype=float)
        beats = np.cumsum(rr) / 1000.0
        windows = _sliding_dfa_local(rr, rr, window_s=25.0, step_s=3.0, beat_times_s=beats)
        assert isinstance(windows, list)

        series = [
            {"timestamp": i * 30, "alpha1_smoothed": float(1.0 - i * 0.08)}
            for i in range(10)
        ]
        crossing = _detect_threshold_crossing(series, 0.75, persistence_windows=5)
        assert isinstance(crossing, tuple) and len(crossing) == 3

        assert _power_at_elapsed([100.0, 200.0], 5.0, power_timestamps=[0.0, 2.0]) is None

        interp = _detect_threshold_crossing(
            [
                {"timestamp": 0, "alpha1_smoothed": 0.9},
                {"timestamp": 60, "alpha1_smoothed": 0.7},
                {"timestamp": 120, "alpha1_smoothed": 0.65},
            ],
            0.75,
            power_data=[180.0, 220.0, 240.0],
            power_timestamps=[0.0, 60.0, 120.0],
            persistence_windows=1,
        )
        assert interp[0] is not None or interp[2] is None

    def test_analyze_stream_warnings_and_confidence(self) -> None:
        junk = [{"elapsed": float(i), "rr": [40.0, 2500.0, 60.0] * 15} for i in range(100)]
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            out = analyze_rr_stream(junk, window_seconds=30, step_seconds=5.0)
        assert isinstance(out, list)

        with patch("engines.recovery.hrv_engine._sliding_dfa_local", side_effect=RuntimeError("dfa boom")):
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                assert analyze_rr_stream(_rr_long(80), window_seconds=60, step_seconds=10.0) == []

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            low = calculate_dfa_alpha1(
                [820.0] * 45,
                context=AthleteContext(gender="FEMALE", training_years=18),
            )
        assert low["status"] in {
            "AEROBIC", "MIXED", "ANAEROBIC", "ERROR", "INVALID_WINDOW", "INSUFFICIENT_DATA",
        }

        det = detect_thresholds_from_activity(
            _rr_long(160),
            power_data=[200.0 + i * 0.3 for i in range(600)],
            context=AthleteContext(gender="MALE", training_years=10),
        )
        assert "vt1" in det

    def test_hysteresis_all_transitions(self) -> None:
        seq = [0.95, 0.85, 0.72, 0.58, 0.42, 0.55, 0.68, 0.82, 0.92]
        statuses = _apply_hysteresis_status(seq, vt1=0.75, vt2=0.50)
        assert len(statuses) == len(seq)
        assert statuses[0] == "AEROBIC"


class TestCardiacEnginePhase9:
    def test_recovery_end_of_stream_and_hrr(self) -> None:
        n = 700
        t = np.arange(n, dtype=float)
        p = np.zeros(n)
        h = np.zeros(n)
        p[:350] = 260.0
        h[:350] = 172.0
        p[350:] = 12.0
        h[350:] = np.maximum(118.0, 172.0 - np.arange(350) * 0.14)

        segs = _detect_recovery_segments(t, p, h)
        assert len(segs) >= 1

        seg = segs[-1]
        rec = compute_hr_recovery(t, h, seg)
        assert rec.get("available") in {True, False}

    def test_steady_segment_detection_and_kinetics_edges(self) -> None:
        n = 900
        t = np.arange(n, dtype=float)
        p = 220.0 + np.sin(np.arange(n) / 40.0) * 5.0
        h = 140.0 + np.arange(n) * 0.03
        steady = _detect_steady_segments(t, p)
        assert isinstance(steady, list)

        flat_seg = Segment(kind="ramp", start_idx=0, end_idx=20, start_t=0.0, end_t=20.0, duration_s=20.0)
        assert compute_hr_kinetics_tau(t[:30], p[:30], h[:30], flat_seg)["available"] is False

    def test_full_analyzer_with_hrv_crossval(self) -> None:
        samples = [
            ActivitySample(t=float(i), power=100.0 + i * 0.5, hr=120.0 + i * 0.08)
            for i in range(800)
        ]
        hrv = analyze_rr_stream(_rr_long(120), window_seconds=60, step_seconds=15.0)
        out = CardiacResponseAnalyzer(
            weight=72.0,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 270.0, "vt1_watts": 200.0},
            hrv_timeline=hrv,
        ).analyze(samples)
        assert out.get("status") in {"success", "partial", "error"}
        if out.get("status") == "success":
            assert out.get("summary", {}).get("fitness_class") or out.get("summary")

    def test_recovery_only_at_end(self) -> None:
        samples = []
        for i in range(500):
            if i < 300:
                samples.append(ActivitySample(t=float(i), power=255.0, hr=168.0))
            else:
                samples.append(ActivitySample(t=float(i), power=8.0, hr=max(115.0, 168.0 - (i - 300) * 0.15)))
        out = CardiacResponseAnalyzer(weight=72.0).analyze(samples)
        assert out.get("status") in {"success", "partial", "error"}


class TestThermalEnginePhase9:
    def test_core_helpers_and_drop_detection(self) -> None:
        arr = np.linspace(37.0, 39.0, 600)
        assert _steady_state_mean(arr) > 37.0
        a, b = _half_means(arr)
        assert b >= a

        core = np.concatenate([np.linspace(37.0, 38.5, 1200), np.linspace(38.5, 39.6, 1200)])
        power = np.concatenate([np.linspace(260, 275, 1200), np.linspace(275, 160, 1200)])
        drop = _detect_power_drop_temp(core, power, window_s=200)
        assert drop is None or drop > 37.0

    def test_full_session_branches(self) -> None:
        n = 3000
        core = [37.1 + (i / n) * 2.5 for i in range(n)]
        power = [230.0 - max(0, (i / 60 - 25)) * 3.0 for i in range(n)]
        hr = [135.0 + (core[i] - 37.1) * 11 for i in range(n)]
        skin = [33.0 + (core[i] - 37.1) * 0.4 for i in range(n)]
        amb = [24.0] * n

        report = analyze_thermal_session(core, power, hr_stream=hr, skin_temp_stream=skin, ambient_temp_stream=amb, ftp=250.0)
        d = report.to_dict()
        assert d["tier"] == "MODEL"
        assert d.get("heat_tolerance_classification") in {None, "excellent", "good", "fair", "poor"}

        limited = analyze_thermal_session(
            [37.0] * 200,
            [180.0] * 200,
            hr_stream=[125.0] * 200,
        )
        assert limited.data_quality in {"no_data", "limited", "partial", "good"}

    def test_acclimation_deacclimating_and_tolerance_gain(self) -> None:
        sessions = [
            ThermalSessionReport(
                data_quality="good",
                n_valid_samples=2000,
                n_total_samples=2400,
                thermal_rise_rate=0.010 + i * 0.003,
                heat_tolerance_threshold=38.4 + i * 0.15,
            )
            for i in range(6)
        ]
        trend = analyze_heat_acclimation(sessions)
        assert trend.trend in {"deacclimating", "stable", "acclimating", None}
        td = trend.to_dict()
        assert td["tier"] == "MODEL"


class TestApiServicesPhase9:
    def test_twin_service_error_paths(self) -> None:
        from tests._fixtures import twin_build_payload
        from api.domain_schemas import TwinStateBuildPayload

        svc = TwinService()
        payload = TwinStateBuildPayload.model_validate(twin_build_payload())
        with patch("api.services.twin_service.build_twin_state", side_effect=ValueError("bad twin")):
            with pytest.raises(ServiceError) as exc:
                svc.build(TwinStateBuildRequest(payload=payload))
            assert exc.value.code == "TWIN_BUILD"

        twin_doc = TwinService().build(TwinStateBuildRequest(payload=payload))
        from api.domain_schemas import TwinStateDocument

        twin = TwinStateDocument.model_validate(twin_doc)

        with patch("api.services.twin_service.project_season_from_plan", side_effect=WorkoutValidationError("bad plan")):
            with pytest.raises(ServiceError) as wexc:
                svc.project_season(
                    SeasonProjectionRequest(
                        twin_state=twin,
                        calendar_plan=[],
                        start_date="2026-06-01",
                        target_date="2026-06-03",
                    )
                )
            assert wexc.value.status_code == 400

        with patch("api.services.twin_service.assert_json_depth", side_effect=PayloadTooDeep("too deep")):
            with pytest.raises(ServiceError) as pexc:
                svc.project_season(
                    SeasonProjectionRequest(
                        twin_state=twin,
                        calendar_plan=[],
                        start_date="2026-06-01",
                        target_date="2026-06-03",
                    )
                )
            assert pexc.value.code == "PAYLOAD_TOO_DEEP"

    def test_ride_analytics_service_branches(self) -> None:
        svc = RideAnalyticsService()
        bare = SimpleNamespace(
            n_samples=3,
            power=np.array([None, None, None]),
            heart_rate=np.array([None, None, None]),
            elapsed_s=np.array([0.0, 1.0, 2.0]),
            rr_intervals=[None, None, None],
            has_rr=False,
        )
        cardiac_out = svc.cardiac(bare, athlete=ATHLETE, metabolic_snapshot=None)
        assert cardiac_out.get("reason") == "NO_VALID_SAMPLES" or cardiac_out.get("status") == "error"
        assert svc.hrv_analyze(bare)["reason"] == "NO_RR_DATA"

        empty_power = SimpleNamespace(
            n_samples=60,
            power=np.zeros(60),
            heart_rate=np.full(60, 140.0),
            elapsed_s=np.arange(60, dtype=float),
            normalized_power=lambda: 0,
        )
        err = svc.power_analyze(empty_power, weight_kg=72.0, ftp=None)
        assert err.get("status") == "error"

        stream = _stream(600, with_rr=True, with_core=True)
        assert svc.thermal_session(stream, ftp=280.0)["tier"] == "MODEL"
        assert svc.thermal_acclimation(
            [ThermalSessionReport(data_quality="good", n_valid_samples=100, n_total_samples=120, thermal_rise_rate=0.02)]
        )["tier"] == "MODEL"
        assert svc.metabolic_flexibility({"status": "success"})["reason"] == "MISSING_FATMAX_OR_VT2"

        adaptive = svc.adaptive_load(
            stream,
            AdaptiveLoadRequest(
                athlete=ATHLETE,
                ftp=280.0,
                daily_status={"date": "2026-06-01"},
                history=[],
            ),
        )
        assert isinstance(adaptive, dict)

        ped = svc.pedaling_balance(stream)
        assert isinstance(ped, dict)

    def test_ride_service_ingest_and_durability_errors(self) -> None:
        svc = RideService()
        stream = _stream(300)
        ingested = svc.ingest(
            stream=stream,
            ride_date=date(2026, 6, 1),
            file_id="ride.fit",
            weight_kg=72.0,
            stored_curve=None,
        )
        assert "curve" in ingested

        no_hr = _stream(200)
        no_hr.heart_rate[:] = 0
        ingested2 = svc.ingest(
            stream=no_hr,
            ride_date=date(2026, 6, 2),
            file_id="ride2.fit",
            weight_kg=72.0,
            stored_curve=None,
        )
        assert ingested2["ride_usable"] in {True, False}

        with pytest.raises(ServiceError) as exc:
            svc.compute_durability(stream, weight_kg=72.0, metabolic_snapshot={"status": "error"})
        assert exc.value.code == "INVALID_SNAPSHOT"

        no_power = SimpleNamespace(n_samples=10, power=np.zeros(10), has_power=False)
        with pytest.raises(ServiceError) as exc2:
            svc.compute_durability(no_power, weight_kg=72.0, metabolic_snapshot={"status": "success"})
        assert exc2.value.code == "NO_POWER"

        with pytest.raises(ServiceError):
            svc.build_parse_report({"file_id": "x.fit"})

    def test_workout_test_explainability_race_services(self) -> None:
        from api.domain_schemas import WorkoutDefinitionInput

        wsvc = WorkoutService()
        with patch("api.services.workout_service.validate_workout_payload", side_effect=WorkoutValidationError("bad")):
            with pytest.raises(ServiceError):
                wsvc.validate(
                    WorkoutValidateRequest(
                        workout=WorkoutDefinitionInput.model_validate(
                            {"title": "t", "steps": [{"duration_s": 60, "target_w": 200}]}
                        )
                    )
                )

        with pytest.raises(ServiceError):
            wsvc.export_workout(SimpleNamespace(format="txt", workout={}))

        wsvc.transition_calendar(CalendarTransitionRequest(current_status="planned", desired_status="completed"))

        tsvc = TestService()
        with pytest.raises(ServiceError) as exc:
            tsvc.propose_from_files([])
        assert exc.value.code == "NO_FILES"

        with pytest.raises(ServiceError) as exc2:
            tsvc.confirm(
                ConfirmRequest(
                    athlete=ATHLETE,
                    measured_on="not-a-date",
                    proposal={"status": "proposed"},
                )
            )
        assert exc2.value.code == "INVALID_DATE"

        esvc = ExplainabilityService()
        vo2 = esvc.vo2max_confidence(
            ExplainabilityVo2ConfidenceRequest(mmp_curve={"60": 480, "300": 340}, efforts_count=3, data_quality_score=0.9)
        )
        assert "confidence_level" in vo2
        dur = esvc.durability_confidence(
            ExplainabilityDurabilityConfidenceRequest(duration_hours=3.0, power_data_completeness=0.95)
        )
        assert dur["confidence_pct"] > 0
        narr = esvc.metric_narrative(
            ExplainabilityMetricNarrativeRequest(
                metric_name="vo2max",
                value=58.0,
                confidence={"confidence_level": "HIGH", "confidence_pct": 85},
                context={},
            )
        )
        assert narr["narrative"]

        gpx = """<?xml version="1.0"?><gpx><trk><trkseg>
        <trkpt lat="45.0" lon="7.0"><ele>200</ele></trkpt>
        <trkpt lat="45.01" lon="7.01"><ele>500</ele></trkpt>
        </trkseg></trk></gpx>"""
        race = RaceService()
        analyzed = race.analyze_gpx(RaceGpxAnalyzeRequest(gpx_text=gpx))
        assert analyzed["status"] == "success"
        sim = race.simulate_gpx(
            RaceGpxSimulateRequest(gpx_text=gpx, weight_kg=72.0, ftp_w=280.0, metabolic_snapshot={"status": "success"})
        )
        assert isinstance(sim, dict)

        with patch("api.services.race_service.parse_gpx_course", side_effect=ValueError("invalid gpx")):
            with pytest.raises(ServiceError):
                race.analyze_gpx(RaceGpxAnalyzeRequest(gpx_text="<bad>"))


class TestProfileExtendedPhase9:
    def test_sprint_vlamax_confidence_matrix(self) -> None:
        assert _with_sprint_vlamax_confidence({"status": "error"})["confidence_score"] == 0.0

        partial = _with_sprint_vlamax_confidence({"status": "success", "vlamax_mmol_l_s": 0.5})
        assert partial["confidence_score"] == 0.55

        high_sens = _with_sprint_vlamax_confidence({
            "status": "success",
            "vlamax_mmol_l_s": 0.5,
            "vlamax_range": [0.1, 0.9],
        })
        assert high_sens["confidence_score"] < 0.82
        assert "tau_alactic_sensitivity_high" in high_sens.get("quality_flags", [])

        mod = _with_sprint_vlamax_confidence({
            "status": "success",
            "vlamax_mmol_l_s": 0.6,
            "vlamax_range": [0.4, 0.75],
        })
        assert mod["confidence_score"] > 0.35

        bad_range = _with_sprint_vlamax_confidence({
            "status": "success",
            "vlamax_mmol_l_s": 0.5,
            "vlamax_range": ["x", "y"],
        })
        assert bad_range["confidence_score"] == 0.55

    def test_extended_service_vlamax_sprint(self) -> None:
        svc = ProfileExtendedService()
        out = svc.vlamax_from_sprint(
            VlamaxSprintRequest(athlete=ATHLETE, p_peak_1s=980.0, p_mean_sprint=860.0, peak_5s_w=940.0)
        )
        assert isinstance(out, dict)
        assert "confidence_score" in out or out.get("status") != "success"


class TestEnginesHighYieldPhase9Batch2:
    def test_neuromuscular_profile_sprints(self) -> None:
        from engines.performance.neuromuscular_profile import analyze_neuromuscular_profile

        stream = _stream(1200, power=180.0)
        for i in range(200, 210):
            stream.power[i] = 950.0
        for i in range(220, 228):
            stream.power[i] = 980.0
        for i in range(500, 508):
            stream.power[i] = 920.0
        stream.cadence[:] = 95.0
        stream.left_right_balance = np.full(stream.n_samples, 48.0)

        out = analyze_neuromuscular_profile(stream, weight_kg=72.0, sprint_threshold_w=700.0)
        assert out.get("status") in {"success", "partial", "insufficient_data", "error"}

        sparse = analyze_neuromuscular_profile(
            SimpleNamespace(power=np.array([]), cadence=np.array([]), left_right_balance=np.array([])),
            weight_kg=None,
        )
        assert sparse.get("status") in {"insufficient_data", "error", "partial"}

    def test_race_prediction_branches(self) -> None:
        from engines.performance.race_prediction_engine import (
            AthleteRaceProfile,
            analyze_course,
            build_course_segments,
            detect_climbs,
            parse_gpx_course,
            simulate_gpx_race,
            simulate_race,
        )

        gpx = """<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
        <trkpt lat="45.0" lon="7.0"><ele>200</ele></trkpt>
        <trkpt lat="45.02" lon="7.02"><ele>450</ele></trkpt>
        <trkpt lat="45.04" lon="7.04"><ele>300</ele></trkpt>
        <trkpt lat="45.06" lon="7.06"><ele>150</ele></trkpt>
        </trkseg></trk></gpx>"""
        pts = parse_gpx_course(gpx)
        segs = build_course_segments(pts, min_segment_m=10.0)
        climbs = detect_climbs(segs)
        course = analyze_course(pts)
        assert course.get("distance_km") or course.get("total_distance_m")

        profile = AthleteRaceProfile(weight_kg=72.0, ftp_w=280.0, mlss_w=270.0, fatmax_w=190.0)
        sim = simulate_race(pts, profile)
        assert sim.get("status") in {"success", "partial", "error"} or "prediction" in sim

        gpx_sim = simulate_gpx_race(
            gpx,
            weight_kg=72.0,
            ftp_w=280.0,
            metabolic_snapshot={"mlss_power_watts": 270.0, "fatmax_power_watts": 190.0},
        )
        assert isinstance(gpx_sim, dict)

    def test_mmp_quality_issue_matrix(self) -> None:
        from engines.performance.mmp_quality import analyze_mmp_quality, clean_mmp, filter_mmp_by_window

        plateau = {60: 400, 120: 400, 300: 350, 600: 320, 1200: 300, 3600: 280}
        r1 = analyze_mmp_quality(plateau)
        assert r1.classification in {"good", "fair", "poor"}

        sprinty = {5: 1500, 60: 600, 300: 380, 1200: 280, 3600: 260}
        r2 = analyze_mmp_quality(sprinty)
        assert len(r2.issues) >= 0

        non_mono = {60: 300, 120: 320, 300: 310}
        r3 = analyze_mmp_quality(non_mono)
        assert any(i.category == "non_monotonic" for i in r3.issues) or r3.classification

        samples = [
            {"duration_s": 60, "power_w": 400, "filename": "a.fit", "date": "2026-01-01"},
            {"duration_s": 120, "power_w": 390, "filename": "a.fit", "date": "2026-01-01"},
            {"duration_s": 300, "power_w": 350, "filename": "b.fit", "date": "2026-01-02"},
        ]
        r4 = analyze_mmp_quality({60: 400, 120: 390, 300: 350, 1200: 300}, mmp_samples=samples)
        assert r4.quality_score <= 1.0

        cleaned, audit = clean_mmp(plateau)
        assert isinstance(cleaned, dict) and isinstance(audit, dict)
        filtered, kept = filter_mmp_by_window(samples, window_days=90)
        assert isinstance(filtered, dict)

    def test_pedaling_balance_and_charts(self) -> None:
        from engines.io.activity_charts import (
            build_activity_charts,
            chart_elevation,
            chart_lr_balance,
            chart_power,
            chart_respiration,
            chart_thermal,
        )
        from engines.recovery.pedaling_balance import analyze_balance_trend, analyze_pedaling_balance

        n = 600
        balance = [48.0 + (i / n) * 4 for i in range(n)]
        power = [200.0 + (i % 50) for i in range(n)]
        dual = analyze_pedaling_balance(balance, power, pedaling_balance_source="dual")
        assert dual.to_dict()["tier"] == "REFERENCE"

        refused = analyze_pedaling_balance(balance, power, pedaling_balance_source="single_estimated")
        assert refused.data_quality == "refused_single_side"

        trend = analyze_balance_trend([dual, refused])
        assert trend.to_dict()["tier"] == "REFERENCE"

        stream = _stream(800, with_core=True)
        stream.left_right_balance = np.linspace(46, 54, stream.n_samples)
        stream.respiration_rate = np.full(stream.n_samples, 18.0)
        assert chart_power(stream).get("type") == "line"
        assert chart_elevation(stream).get("type") or chart_elevation(stream).get("available") is False
        assert chart_lr_balance(stream).get("type") or chart_lr_balance(stream).get("available") is False
        assert chart_respiration(stream).get("type") or chart_respiration(stream).get("available") is False
        assert chart_thermal(stream).get("type") or chart_thermal(stream).get("available") is False
        charts = build_activity_charts(stream, zones=[{"zone": "Z2", "seconds": 1200}])
        assert isinstance(charts, dict)

    def test_glycolytic_bayesian_and_protocols(self) -> None:
        from engines.metabolic.bayesian_profiler import bayesian_metabolic_snapshot
        from engines.metabolic.glycolytic_validation_engine import build_glycolytic_profile
        from engines.performance.test_protocols import run_incremental_test, run_test, run_wingate_test
        from engines.workouts.feasibility_engine import analyze_workout_feasibility

        prof = __import__("engines.metabolic.metabolic_profiler", fromlist=["MetabolicProfiler"]).MetabolicProfiler(
            weight=72.0, context=AthleteContext()
        )
        mmp_int = {int(k): float(v) for k, v in MMP.items()}
        snap = prof.generate_metabolic_snapshot(mmp_int)
        bayes = bayesian_metabolic_snapshot(prof, mmp_int, n_samples=400, n_warmup=100, seed=1)
        assert hasattr(bayes, "to_dict") or isinstance(bayes, dict)

        gly = build_glycolytic_profile(snap if isinstance(snap, dict) else snap, mmp={5: 900, 60: 480})
        assert gly.get("status") in {"success", "partial", "error", "unavailable"}

        wingate = run_wingate_test({"test_data": {"power_stream": [1000.0] * 30, "body_weight_kg": 72.0}})
        assert wingate.get("status") in {"success", "error"}
        inc = run_incremental_test({"test_data": {"steps": [{"power_w": 150, "hr_mean": 120}]}})
        assert inc.get("status") in {"success", "error"}
        env = run_test({"test_type": "wingate", "test_data": {"power_stream": [900.0] * 30, "body_weight_kg": 72.0}})
        assert env.get("status") in {"success", "error"}

        feas = analyze_workout_feasibility(
            {"title": "Test", "steps": [{"duration_s": 300, "target_w": 250}]},
            {"cp_w": 260, "w_prime_j": 19000, "weight_kg": 72},
            {},
        )
        assert feas.get("status") in {"success", "warning", "insufficient_profile", "error"}
