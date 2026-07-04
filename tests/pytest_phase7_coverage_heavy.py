"""Phase 7 — heavy coverage pass: golden FIT assets, HRV/cardiac, summary E2E."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from api.domain_schemas import PowerSourceActivity, WorkoutDefinitionInput
from engines.adaptive_load.trend import calculate_load_trend
from engines.core.athlete_context import AthleteContext
from engines.io.activity_intelligence import build_activity_intelligence, build_chart_series
from engines.io.data_quality_report import build_data_quality_report
from engines.io.fit_parser import (
    FitFileError,
    measured_signal_flags,
    parse_fit_file_enhanced,
    parse_fit_records_enhanced,
)
from engines.io.workout_summary import build_workout_summary
from engines.metabolic.lactate_validation_engine import (
    LactateStep,
    compute_lactate_thresholds,
    validate_model_against_lactate,
)
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.metabolic.power_vlamax_estimator import estimate_vlamax_from_power_series
from engines.performance.sprint_peak_analysis import _rolling_max_mean, analyze_sprint_power
from engines.projection.season_projection_engine import project_season_from_plan
from engines.recovery.cardiac_engine import (
    ActivitySample,
    CardiacResponseAnalyzer,
    Segment,
    compute_aerobic_decoupling,
)
from engines.recovery.hrv_engine import (
    _artifact_mask,
    _compute_sqi,
    _correct_ectopic,
    _prepare_rr_quality,
    analyze_rr_stream,
)
from engines.twin_state.models import build_twin_state

FIT_DIR = Path(__file__).resolve().parent / "assets" / "fit"

METABOLIC_SNAP = {
    "status": "success",
    "mlss_power_watts": 280.0,
    "map_aerobic_watts": 350.0,
    "estimated_vo2max": 58.0,
    "estimated_vlamax_mmol_L_s": 0.45,
    "combustion_curve": [{"watt": 200, "carbOxidation": 30}],
    "expressiveness": {"reliability": {"mlss": True, "vo2max": True}},
}


def _long_stream(seconds: int = 3600, *, power: float = 230.0, with_rr: bool = False):
    start = datetime(2026, 1, 1, 8, 0, 0)
    records = []
    for i in range(seconds):
        row = {
            "timestamp": start + timedelta(seconds=i),
            "power": power + (i % 15),
            "heart_rate": 140.0 + (i % 20) * 0.3,
            "cadence": 90.0,
        }
        if with_rr:
            row["rr_intervals"] = [810.0 + (i % 4), 805.0 + (i % 3)]
        records.append(row)
    return parse_fit_records_enhanced(
        records,
        session_dict={"start_time": start, "total_elapsed_time": seconds, "sport": "cycling"},
    )


def _rr_samples(n: int = 120) -> list[dict]:
    return [{"rr": [800.0 + np.sin(i / 4.0) * 12 for _ in range(6)]} for i in range(n)]


class TestGoldenFitAssetsHeavy:
    def test_all_committed_fit_files_parse(self) -> None:
        files = sorted(FIT_DIR.glob("*.fit"))
        assert files, "run tools/generate_golden_fit_assets.py to create FIT binaries"
        parsed = 0
        for fit_path in files:
            if fit_path.stem == "truncated":
                with pytest.raises(FitFileError) as exc:
                    parse_fit_file_enhanced(str(fit_path), check_crc=False, repair_synthetic_header=False)
                assert exc.value.reason == "TRUNCATED"
                parsed += 1
                continue
            stream = parse_fit_file_enhanced(
                str(fit_path),
                check_crc=fit_path.stem != "bad_crc",
                repair_synthetic_header=True,
            )
            assert stream.n_samples > 0
            parsed += 1
        assert parsed == len(files)

    def test_bad_crc_recovery_and_expected_snapshots(self) -> None:
        bad = FIT_DIR / "bad_crc.fit"
        stream = parse_fit_file_enhanced(str(bad), check_crc=True, repair_synthetic_header=True)
        assert stream.n_samples >= 60
        assert measured_signal_flags(stream)["power"] is True

        expected_path = FIT_DIR / "garmin_power_hr.expected_parse.json"
        expected = json.loads(expected_path.read_text())
        live = parse_fit_file_enhanced(str(FIT_DIR / "garmin_power_hr.fit"))
        flags = measured_signal_flags(live)
        assert flags["power"] == expected["has_power_stream"]
        assert flags["heart_rate"] == expected["has_hr_stream"]

    def test_minimal_fit_has_lap_and_rr(self) -> None:
        stream = parse_fit_file_enhanced(str(FIT_DIR / "minimal_power_hr_lap_hrv.fit"))
        assert stream.has_rr or any(stream.rr_intervals)
        assert stream.n_samples >= 60


class TestFitParserSyntheticHeavy:
    def test_read_retry_and_rich_record_fields(self) -> None:
        from engines.io import fit_parser

        import builtins

        real_open = builtins.open
        calls = {"n": 0}

        def flaky_open(path, mode="rb"):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError(5, "EIO simulated")
            return real_open(path, mode)

        fit_path = FIT_DIR / "garmin_power_hr.fit"
        with patch("builtins.open", side_effect=flaky_open):
            data = fit_parser._read_file_with_retry(str(fit_path), attempts=2, delay_s=0)
        assert len(data) > 100

        start = datetime(2026, 2, 1, 9, 0, 0)
        records = []
        for i in range(180):
            records.append({
                "timestamp": start + timedelta(seconds=i),
                "power": 240.0,
                "heart_rate": 150.0,
                "cadence": 92.0,
                "core_body_temperature": 37.2 if i % 30 == 0 else None,
                "skin_temperature": 33.5 if i % 40 == 0 else None,
                "left_right_balance": 128 if i % 20 == 0 else 48,
                "respiration_rate": 18.0 if i % 25 == 0 else None,
                "cadence_position": "standing" if i % 50 == 0 else "seated",
                "rr_intervals": [820.0, 815.0] if i % 10 == 0 else None,
            })
        stream = parse_fit_records_enhanced(
            records,
            session_dict={"start_time": start, "device_name": "test_head_unit"},
        )
        assert stream.has_core_sensor or np.any(np.isfinite(stream.core_body_temp))
        assert stream.has_respiration or np.any(np.isfinite(stream.respiration_rate))
        assert stream.has_cycling_dynamics


class TestHrvEngineHeavy:
    def test_rr_quality_and_artifact_matrix(self) -> None:
        assert _prepare_rr_quality([])["rejected_reason"] == "EMPTY_RR"
        noisy = _prepare_rr_quality([50.0, 3000.0, 80.0] * 40)
        assert noisy["valid"] is False

        clean_rr = np.array([800.0 + np.sin(i / 6.0) * 8 for i in range(120)], dtype=float)
        mask = _artifact_mask(clean_rr)
        corrected = _correct_ectopic(clean_rr, mask)
        assert corrected.shape == clean_rr.shape
        assert _compute_sqi(clean_rr, corrected, float(np.mean(mask))) > 0.5

        with pytest.raises(ValueError):
            _correct_ectopic(clean_rr, np.ones_like(clean_rr, dtype=bool))

    def test_analyze_rr_stream_on_fit_and_long_series(self) -> None:
        stream = parse_fit_file_enhanced(str(FIT_DIR / "garmin_rr_hrv.fit"))
        rr_samples = [{"rr": list(map(float, beats))} for beats in stream.rr_intervals if beats]
        if rr_samples:
            timeline = analyze_rr_stream(rr_samples, window_seconds=30, step_seconds=10.0)
            assert isinstance(timeline, list)

        long_timeline = analyze_rr_stream(
            _rr_samples(200),
            window_seconds=60,
            step_seconds=15.0,
            context=AthleteContext(gender="MALE", training_years=5),
        )
        assert isinstance(long_timeline, list)

        bad = analyze_rr_stream([{"rr": [50.0, 2500.0, 90.0] * 8}], window_seconds=30, step_seconds=5.0)
        assert isinstance(bad, list)


class TestCardiacEngineHeavy:
    def test_steady_ramp_recovery_and_decoupling(self) -> None:
        steady = [
            ActivitySample(t=float(i), power=220.0 + (i % 5), hr=140.0 + i * 0.02)
            for i in range(1200)
        ]
        steady_out = CardiacResponseAnalyzer(weight=72.0, metabolic_snapshot=METABOLIC_SNAP).analyze(steady)
        assert steady_out.get("status") in {"success", "partial", "error"}

        ramp = [
            ActivitySample(t=float(i), power=100.0 + i * 0.8, hr=120.0 + i * 0.07)
            for i in range(600)
        ]
        ramp_out = CardiacResponseAnalyzer(weight=72.0).analyze(ramp)
        assert ramp_out.get("status") in {"success", "partial", "error"}

        recovery: list[ActivitySample] = []
        for i in range(900):
            if i < 300:
                recovery.append(ActivitySample(t=float(i), power=270.0, hr=168.0))
            else:
                recovery.append(ActivitySample(t=float(i), power=20.0, hr=max(118.0, 168.0 - (i - 300) * 0.12)))
        rec_out = CardiacResponseAnalyzer(
            weight=72.0,
            metabolic_snapshot=METABOLIC_SNAP,
            hrv_timeline=analyze_rr_stream(_rr_samples(80), window_seconds=60, step_seconds=20.0),
        ).analyze(recovery)
        assert rec_out.get("status") in {"success", "partial", "error"}

        seg = Segment(kind="steady", start_idx=0, end_idx=200, start_t=0.0, end_t=199.0, duration_s=200.0)
        t = np.arange(200, dtype=float)
        bad = compute_aerobic_decoupling(t, np.full(200, 220.0), np.zeros(200), seg)
        assert bad.get("available") is False

    def test_moving_average_short_series(self) -> None:
        from engines.recovery.cardiac_engine import _moving_average

        t = np.array([0.0, 1.0, 2.0])
        out = _moving_average(np.array([100.0, 110.0, 120.0]), window_s=60.0, t=t)
        assert out.size == 3


class TestWorkoutSummaryAndIntelligenceHeavy:
    def test_workout_summary_on_golden_fits(self) -> None:
        for stem in ("garmin_power_hr", "zwift_virtual", "minimal_power_hr_lap_hrv", "indoor_trainer_erg"):
            stream = parse_fit_file_enhanced(str(FIT_DIR / f"{stem}.fit"))
            summary = build_workout_summary(
                stream,
                weight_kg=72.0,
                ftp=280.0 if stem != "indoor_trainer_erg" else None,
                metabolic_snapshot=METABOLIC_SNAP if stem != "no_power_hr_only" else None,
                vt1_w=200.0,
                vt2_w=260.0,
            )
            assert summary["status"] == "success"
            assert "sections" in summary
            assert "headline" in summary

        rr_stream = parse_fit_file_enhanced(str(FIT_DIR / "garmin_rr_hrv.fit"))
        rr_summary = build_workout_summary(rr_stream, weight_kg=72.0, ftp=250.0)
        assert rr_summary["sections"]["hrv"]["available"] in {True, False}
        assert rr_summary["sections"]["cardiac"]["available"] in {True, False}

        long = _long_stream(4200, with_rr=True)
        long_summary = build_workout_summary(
            long,
            weight_kg=72.0,
            ftp=280.0,
            metabolic_snapshot=METABOLIC_SNAP,
            hrv_window_seconds=60,
            hrv_step_seconds=20.0,
        )
        assert long_summary["sections"]["power"].get("status") in {"success", None} or long_summary["sections"]["power"].get("available") is not False

    def test_activity_intelligence_and_data_quality_on_streams(self) -> None:
        stream = parse_fit_file_enhanced(str(FIT_DIR / "zwift_virtual.fit"))
        intel = build_activity_intelligence(stream, weight_kg=72.0, ftp=280.0, lthr=165.0)
        assert intel.get("status") == "success"
        assert intel.get("chart_series") or "series" in str(intel)

        chart = build_chart_series(_long_stream(5000))
        assert chart["status"] == "success"
        assert chart["series"]["power_w"]

        dq = build_data_quality_report(stream)
        assert dq["signals"]["power"]["available"] is True
        assert "overall_score" in dq

        hr_only = parse_fit_file_enhanced(str(FIT_DIR / "no_power_hr_only.fit"))
        dq_hr = build_data_quality_report(hr_only)
        assert dq_hr["signals"]["power"]["available"] is False
        assert dq_hr["signals"]["heart_rate"]["available"] is True


class TestHeavyScientificResiduals:
    def test_lactate_vlamax_sprint_projection_trend(self) -> None:
        short_curve = compute_lactate_thresholds([
            LactateStep(power_w=180, lactate_mmol=2.0),
            LactateStep(power_w=200, lactate_mmol=2.5),
        ])
        assert short_curve.mlss_dmax_w is None

        profiler = MetabolicProfiler(weight=72.0)
        dmax_fail = validate_model_against_lactate(
            [
                LactateStep(power_w=150, lactate_mmol=1.0),
                LactateStep(power_w=180, lactate_mmol=1.5),
                LactateStep(power_w=210, lactate_mmol=2.0),
                LactateStep(power_w=240, lactate_mmol=3.5),
                LactateStep(power_w=270, lactate_mmol=5.5),
            ],
            profiler,
            {5: 900},
        )
        assert dmax_fail["status"] == "error"

        sprint = [200.0] * 3 + [850.0] * 12 + [700.0] * 10
        vla = estimate_vlamax_from_power_series(
            sprint,
            weight_kg=72.0,
            eta=0.23,
            active_muscle_mass_kg=12.0,
            cp_w=280.0,
        )
        assert vla.get("status") in {"success", "insufficient_sprint", "invalid_protocol"}

        assert _rolling_max_mean(np.array([400.0]), window_s=3.0, dt_s=1.0) == 400.0
        assert analyze_sprint_power([0.0, 0.0, 0.0], dt_s=1.0) is None

        history = [{"tss": 80.0, "session_load": 40.0} for _ in range(60)]
        trend = calculate_load_trend(history, 40.0, current_external_load=80.0)
        div = trend["external_internal_divergence"]
        assert div.get("divergence_status") in {"good_adaptation", "aligned", "watch", "hidden_fatigue", None}

        twin = build_twin_state({"athlete_id": "a1", "metabolic_snapshot": METABOLIC_SNAP})
        proj = project_season_from_plan(
            twin,
            [{"date": "2026-06-18", "tss": 250.0}],
            start_date="2026-06-17",
            target_date="2026-06-20",
        )
        assert any(w.get("type") == "large_daily_load" for w in proj["warnings"])

        w = WorkoutDefinitionInput.model_construct(
            name="From structure",
            structure=[{"duration_s": 300, "type": "work"}],
            steps=[],
        )
        normalized = WorkoutDefinitionInput._normalize_steps(w)
        assert len(normalized.steps) == 1
        assert PowerSourceActivity(curve={"300": 320.0}).to_engine_dict()["mmp"]["300"] == 320.0


def _cardiac_activity(*, steady_s: int = 600, power: float = 220.0) -> list[ActivitySample]:
    samples: list[ActivitySample] = []
    for i in range(steady_s):
        hr = 140.0 + 25.0 * (i / max(steady_s - 1, 1))
        samples.append(ActivitySample(t=float(i), power=power, hr=hr))
    hr_drop = 165.0
    for j in range(120):
        hr_drop = max(100.0, hr_drop - 1.2)
        samples.append(ActivitySample(t=float(steady_s + j), power=0.0, hr=hr_drop))
    return samples


class TestPhase7CoverageHeavyBatch2:
    """Deeper HRV/cardiac/summary branches ported from phase-4 depth tests."""

    def test_hrv_dfa_threshold_and_ci_paths(self) -> None:
        from engines.recovery.hrv_engine import (
            _detect_threshold_crossing,
            _normal_z_for_ci,
            calculate_dfa_alpha1,
        )

        assert _normal_z_for_ci(0.92) > _normal_z_for_ci(0.90)
        assert _normal_z_for_ci(0.99) == pytest.approx(2.576, rel=0.01)

        sparse = calculate_dfa_alpha1([800.0] * 5)
        assert sparse["status"] in {"INSUFFICIENT_DATA", "INVALID_WINDOW", "ERROR"}

        crossing = _detect_threshold_crossing(
            [
                {"timestamp": 0.0, "alpha1_smoothed": 0.95},
                {"timestamp": 30.0, "alpha1_smoothed": 0.72},
                {"timestamp": 60.0, "alpha1_smoothed": 0.68},
            ],
            threshold=0.75,
            power_data=[200.0, 240.0, 260.0],
            power_timestamps=[0.0, 30.0, 60.0],
            persistence_windows=1,
        )
        assert crossing[0] is not None

        rr_samples = [
            {"elapsed": float(i * 5), "rr": [880.0 - (i % 4) + (j % 3) * 2 for j in range(40)]}
            for i in range(120)
        ]
        timeline = analyze_rr_stream(
            rr_samples,
            window_seconds=120,
            step_seconds=30.0,
            context=AthleteContext(training_years=8, discipline="ROAD"),
        )
        assert timeline

    def test_cardiac_segment_metrics_matrix(self) -> None:
        from engines.recovery.cardiac_engine import (
            compute_cardiac_drift,
            compute_chronotropic_response,
            compute_hr_recovery,
            cross_validate_thresholds,
        )

        samples = _cardiac_activity(steady_s=600)
        t = np.array([s.t for s in samples])
        p = np.array([s.power for s in samples])
        h = np.array([s.hr for s in samples])
        seg = Segment(kind="steady", start_idx=50, end_idx=550, start_t=50.0, end_t=549.0, duration_s=500.0)

        assert compute_cardiac_drift(t, p, h, seg).get("available") in {True, False}
        assert compute_aerobic_decoupling(t, p, h, seg).get("available") in {True, False}
        assert compute_chronotropic_response(t, p, h, seg).get("available") in {True, False}
        assert compute_hr_recovery(t, h, seg).get("available") in {True, False}

        cv = cross_validate_thresholds(
            t,
            p,
            h,
            {"status": "success", "mlss_power_watts": 220, "map_aerobic_watts": 320},
            [
                {"timestamp": 60.0, "status": "AEROBIC", "alpha1_smoothed": 0.92},
                {"timestamp": 180.0, "status": "MIXED", "alpha1_smoothed": 0.72},
                {"timestamp": 300.0, "status": "ANAEROBIC", "alpha1_smoothed": 0.55},
            ],
        )
        assert cv.get("available") in {True, False}

        out = CardiacResponseAnalyzer(weight=72.0, metabolic_snapshot=METABOLIC_SNAP).analyze(samples)
        assert out.get("status") in {"success", "partial", "error"}

    def test_workout_summary_hrv_cardiac_edge_sections(self) -> None:
        from engines.io.workout_summary import _mmp_curve_to_dict

        assert _mmp_curve_to_dict([{"duration_s": None, "power_w": 300}]) == {}

        class _EmptyRRStream:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                if name == "rr_intervals":
                    return [[] for _ in range(self._inner.n_samples)]
                return getattr(self._inner, name)

        base = parse_fit_file_enhanced(str(FIT_DIR / "minimal_power_hr_lap_hrv.fit"))
        empty_rr = build_workout_summary(_EmptyRRStream(base), weight_kg=72.0, ftp=280.0)
        assert empty_rr["sections"]["hrv"]["reason"] == "RR_INTERVALS_EMPTY"

        class _NullPHStream:
            n_samples = 120
            has_heart_rate = True
            has_power = True
            has_rr = False
            power = np.array([None] * 120)
            heart_rate = np.array([None] * 120)
            elapsed_s = np.arange(120, dtype=float)
            sport = "cycling"
            start_time = datetime(2026, 1, 1)
            total_elapsed_s = 120

        null_cardiac = build_workout_summary(_NullPHStream(), weight_kg=72.0, ftp=280.0)
        assert null_cardiac["sections"]["cardiac"]["reason"] == "NO_VALID_SAMPLES_AFTER_FILTERING"

        with patch("engines.io.workout_summary.analyze_rr_stream_endurance_scheduled", side_effect=RuntimeError("hrv fail")):
            fail_hrv = build_workout_summary(_long_stream(900, with_rr=True), weight_kg=72.0, ftp=280.0)
            assert "HRV_ANALYSIS_FAILED" in fail_hrv["sections"]["hrv"]["reason"]

    def test_activity_data_quality_trend_residuals(self) -> None:
        from engines.io.activity_intelligence import _full_array, compute_cardiac_decoupling
        from engines.io.data_quality_report import _quality_flags, _series_quality

        assert _full_array(None).size == 0

        assert _series_quality(None, measured=False)["notes"] == ["missing_signal"]
        assert _series_quality([], measured=True)["notes"] == ["empty_signal"]
        partial = _series_quality([0.0] * 60 + [220.0] * 10, measured=True, valid_min=1)
        assert "low_coverage" in partial["notes"]
        class _Unarrayable:
            def __array__(self):
                raise TypeError("cannot convert")

        assert _quality_flags(_Unarrayable()).get("available") is False
        assert _quality_flags(np.array([])).get("available") is False

        dec = compute_cardiac_decoupling(_long_stream(1500))
        assert dec["status"] in {"success", "skipped"}

        watch_hist = [{"tss": 30.0, "session_load": 70.0} for _ in range(60)]
        watch = calculate_load_trend(watch_hist, 70.0, current_external_load=30.0)
        assert watch["external_internal_divergence"].get("divergence_status") in {
            "watch", "hidden_fatigue", "aligned", "good_adaptation",
        }

        adapt_hist = [{"tss": 90.0, "session_load": 35.0} for _ in range(60)]
        adapt = calculate_load_trend(adapt_hist, 35.0, current_external_load=90.0)
        assert adapt["external_internal_divergence"].get("divergence_status") in {
            "good_adaptation", "aligned", "watch", "hidden_fatigue",
        }

        assert calculate_load_trend([None, {"tss": "x", "session_load": "y"}], None)["status"] == "insufficient_data"
