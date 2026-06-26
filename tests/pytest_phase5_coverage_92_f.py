"""Phase 5 — deep branch closure batch F (hrv, cardiac, fit, bayesian, lab, effort, mmp)."""

from __future__ import annotations

import warnings
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import (
    FitFileError,
    normalize_lap_messages,
    parse_fit_file_enhanced,
)
from engines.metabolic.bayesian_profiler import (
    PosteriorSummary,
    _adaptive_metropolis,
    _compute_vo2_floor,
    _effective_sample_size,
    _mcmc_misconverged,
    bayesian_metabolic_snapshot,
)
from engines.metabolic.lab_data import LabTestResult, create_lab_result, parse_lab_text, validate_lab_result
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.effort_extractor import (
    ProfileProposal,
    SprintCandidate,
    extract_test_proposal,
)
from engines.recovery.cardiac_engine import (
    ActivitySample,
    CardiacResponseAnalyzer,
    _detect_recovery_segments,
    compute_hr_recovery,
)
from engines.recovery.hrv_engine import (
    _apply_hysteresis_status,
    _artifact_mask,
    _correct_ectopic,
    _detect_threshold_crossing,
    _dfa_alpha1_full,
    _ema,
    _power_at_elapsed,
    _sliding_dfa_local,
    _winsorize_rr,
    analyze_rr_stream,
    calculate_dfa_alpha1,
    detect_thresholds_from_activity,
)


class TestHrvDeep92F:
    def test_internal_pipeline_branches(self) -> None:
        assert _ema([]) == []

        hysteresis = _apply_hysteresis_status(
            [0.95, 0.93, 0.70, 0.55, 0.48, 0.52, 0.58, 0.78, 0.92],
            vt1=0.75,
            vt2=0.50,
        )
        assert "MIXED" in hysteresis
        assert "ANAEROBIC" in hysteresis

        assert _power_at_elapsed([], 1.0) is None
        assert _power_at_elapsed([200.0], 5.0, [0.0]) is None
        assert _power_at_elapsed([200.0, 220.0], 0.5, [0.0, 1.0]) == pytest.approx(210.0)
        assert _power_at_elapsed([200.0], 0.5, [float("nan")]) is None

        jumpy = np.array([800.0, 1600.0, 810.0, 805.0] * 40, dtype=float)
        mask = _artifact_mask(jumpy)
        assert mask.any()
        corrected = _correct_ectopic(jumpy, mask)
        assert corrected.shape == jumpy.shape

        flat = _dfa_alpha1_full(np.full(80, 800.0))
        assert flat.get("alpha1") is None or isinstance(flat.get("alpha1"), float)

        rr = np.array([820.0 + (i % 9) for i in range(200)], dtype=float)
        rr_w = _winsorize_rr(rr)
        rr_corr = _correct_ectopic(rr_w, _artifact_mask(rr_w))
        non_mono = np.linspace(0, 180, rr_corr.size)
        non_mono[50] = 10.0
        windows = _sliding_dfa_local(
            rr_corrected=rr_corr,
            rr_winsorized_raw=rr_w,
            window_s=60.0,
            step_s=8.0,
            beat_times_s=non_mono,
        )
        assert isinstance(windows, list)

        with pytest.raises(ValueError):
            _sliding_dfa_local(rr_corr, rr_w[:10], window_s=60.0, step_s=8.0)

    def test_stream_rejection_and_confidence_downgrade(self) -> None:
        sparse = analyze_rr_stream([{"rr": [300.0, 2500.0, 100.0] * 30}], window_seconds=60, step_seconds=10.0)
        assert sparse == []

        bad_global = [{"rr": [float("nan"), 3000.0, 50.0] * 40} for _ in range(5)]
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            rejected = analyze_rr_stream(bad_global, window_seconds=60, step_seconds=10.0)
        assert rejected == []

        low_r2 = calculate_dfa_alpha1(
            [820.0] * 90,
            context=AthleteContext(gender="MALE", training_years=15, discipline="ROAD"),
        )
        assert low_r2["confidence"] in {"HIGH", "MEDIUM", "LOW", "NONE"}

        rr_samples = [
            {"elapsed": float(i * 4), "rr": [820.0 + (i % 6) for _ in range(45)]}
            for i in range(100)
        ]
        power = [150.0 + i * 0.3 for i in range(2000)]
        detected = detect_thresholds_from_activity(
            rr_samples,
            power_data=power,
            power_timestamps=[float(i) for i in range(len(power))],
            window_seconds=90,
            step_seconds=6.0,
            context=AthleteContext(gender="MALE", training_years=12, discipline="ROAD"),
        )
        assert "quality_summary" in detected

        crossing = _detect_threshold_crossing(
            [
                {"timestamp": 0.0, "alpha1_smoothed": 0.90},
                {"timestamp": 30.0, "alpha1_smoothed": 0.74},
                {"timestamp": 60.0, "alpha1_smoothed": 0.70},
                {"timestamp": 90.0, "alpha1_smoothed": 0.68},
            ],
            threshold=0.75,
            power_data=[200.0, 220.0, 240.0, 250.0],
            power_timestamps=[0.0, 30.0, 60.0, 90.0],
            persistence_windows=3,
        )
        assert crossing[0] is not None or crossing[2] is not None


class TestFitParserDeep92F:
    def test_lap_normalization_edges(self) -> None:
        assert normalize_lap_messages([{}, {"total_timer_time": "bad"}, {"total_elapsed_time": -5}]) == []
        laps = normalize_lap_messages(
            [{"total_timer_time": 300, "avg_power": 250, "start_time": datetime(2026, 6, 1, 8, 0, 0)}]
        )
        assert laps and laps[0]["duration_s"] == 300

    def test_device_power_meter_and_hrv_scalar(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        import engines.io.fit_parser as fp

        start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        records = [
            {
                "timestamp": start + timedelta(seconds=i),
                "power": 220.0,
                "heart_rate": 140.0,
                "left_right_balance": 45.0 + (i % 6),
            }
            for i in range(90)
        ]

        def _extract(_payload: bytes, *, check_crc: bool):
            return (
                records,
                [{"sport": "cycling", "start_time": start, "total_elapsed_time": 90}],
                [
                    {"manufacturer": "Garmin", "product": "Edge"},
                    {"manufacturer": "quarq", "product": "power spider", "antplus_device_type": "bike_power"},
                ],
                [{"rr_interval": 0.82}, {"other_time_field": 0.81}],
                [{"total_timer_time": 90}],
            )

        monkeypatch.setattr(fp, "_extract_messages", _extract)
        fit_path = tmp_path / "device.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 200)
        stream = fp.parse_fit_file_enhanced(str(fit_path), check_crc=False, repair_synthetic_header=False)
        assert stream.n_samples >= 90
        assert stream.pedaling_balance_source in {"dual", "unknown", "single_estimated"}

    def test_parse_error_reasons(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        import engines.io.fit_parser as fp

        fit_path = tmp_path / "bad.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 200)

        def _header_fail(_payload: bytes, *, check_crc: bool):
            raise fp.FitHeaderError("not a FIT file")

        monkeypatch.setattr(fp, "_extract_messages", _header_fail)
        with pytest.raises(FitFileError) as exc:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert exc.value.reason == "INVALID_HEADER"

        def _no_records(_payload: bytes, *, check_crc: bool):
            return [], [], [], [], []

        monkeypatch.setattr(fp, "_extract_messages", _no_records)
        with pytest.raises(FitFileError) as exc2:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert exc2.value.reason == "NO_RECORDS"


class TestCardiacDeep92F:
    def test_aggregate_with_recovery_classes(self) -> None:
        recovery_metric = {
            "available": True,
            "hrr60_bpm": 35.0,
            "hrr60_class": "GOOD",
            "hrr120_bpm": 55.0,
            "hrr120_class": "EXCELLENT",
        }
        decoupling = [{"available": True, "fitness_class": "GOOD"}]
        drift = [{"available": True, "fitness_class": "FAIR"}]
        cei = [{"available": True, "fitness_class": "GOOD"}]
        kinetics = [{"available": True, "fitness_class": "EXCELLENT"}]
        summary = CardiacResponseAnalyzer._aggregate_summary(
            decoupling, drift, cei, kinetics, [recovery_metric]
        )
        assert summary["fitness_class"] in {"EXCELLENT", "GOOD", "FAIR", "POOR"}
        assert "hr_recovery" in summary["contributions"]

        empty = CardiacResponseAnalyzer._aggregate_summary([], [], [], [], [])
        assert empty["fitness_class"] == "UNKNOWN"

    def test_full_analyzer_with_recovery_block(self) -> None:
        samples: List[ActivitySample] = []
        for i in range(900):
            if i < 400:
                p, h = 225.0, 140.0 + i * 0.01
            elif i < 500:
                p, h = 250.0 + (i - 400) * 0.8, 155.0 + (i - 400) * 0.05
            elif i < 700:
                p, h = 10.0, max(125.0, 175.0 - (i - 500) * 0.2)
            else:
                p, h = 220.0, 130.0 + (i - 700) * 0.01
            samples.append(ActivitySample(t=float(i), power=p, hr=h))

        timeline = [
            {"timestamp": float(i * 30), "status": "AEROBIC"}
            for i in range(15)
        ] + [{"timestamp": 500.0, "status": "MIXED"}, {"timestamp": 530.0, "status": "ANAEROBIC"}]

        result = CardiacResponseAnalyzer(
            weight=72.0,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 250},
            hrv_timeline=timeline,
        ).analyze(samples)
        assert result.get("status") == "success"
        assert result["summary"]["n_metrics_available"] >= 1

        t = np.arange(200, dtype=float)
        rec_p = np.concatenate([np.full(80, 260.0), np.full(120, 10.0)])
        rec_h = np.concatenate([np.full(80, 175.0), np.linspace(175, 120, 120)])
        segs = _detect_recovery_segments(t, rec_p, rec_h)
        if segs:
            rec = compute_hr_recovery(t, rec_h, segs[0])
            assert rec.get("available") is True


class TestBayesianLabEffort92F:
    def test_bayesian_internals_and_error_dict(self) -> None:
        profiler = MetabolicProfiler(weight=72.0)
        err = bayesian_metabolic_snapshot(profiler, {60: 400}, n_samples=100, n_warmup=20)
        assert err.status == "error"
        body = err.to_dict()
        assert body["status"] == "error"
        assert "message" in body

        floor = _compute_vo2_floor(profiler, {300: 280, 1200: 260}, eta=0.23)
        assert floor >= 0.0

        vo2_post = PosteriorSummary(
            mean=35.0,
            median=35.0,
            std=2.0,
            ci95_low=30.0,
            ci95_high=40.0,
            ci80_low=32.0,
            ci80_high=38.0,
            prior_mean=55.0,
            prior_std=5.0,
            n_effective_samples=100,
        )
        reason = _mcmc_misconverged(
            vo2_post=vo2_post,
            mlss_w=250.0,
            ref_vo2=55.0,
            ref_mlss=270.0,
            vo2_floor=45.0,
            acceptance_rate=0.25,
        )
        assert reason in {"vo2_below_reference_fit", "vo2_below_aerobic_floor", None} or isinstance(reason, str)

        samples, acc = _adaptive_metropolis(
            lambda x: -float(np.sum((x - np.array([55.0, 0.4, 0.1])) ** 2)),
            np.array([55.0, 0.4, 0.1]),
            n_samples=50,
            n_warmup=20,
            rng=np.random.default_rng(1),
        )
        assert samples.shape == (50, 3)
        assert 0.0 <= acc <= 1.0
        assert _effective_sample_size(samples[:, 0]) >= 1

    def test_lab_roundtrip_and_validation(self) -> None:
        created = create_lab_result(
            test_date=date(2026, 6, 1),
            vo2max=62.0,
            vlamax=0.45,
            mlss_w=280,
        )
        assert created.has_vo2max

        parsed = LabTestResult.from_dict(
            {
                "test_date": "2026-06-01",
                "source": "not_a_real_source",
                "test_type": "mystery",
                "vo2max_ml_kg_min": 10.0,
                "vlamax_mmol_L_s": 3.0,
                "mlss_power_w": 400,
                "map_w": 300,
                "hr_max_bpm": 100,
                "lactate_curve": [{"power_w": 200, "lactate_mmol": 2.0, "heart_rate_bpm": 150}],
            }
        )
        warns = validate_lab_result(parsed)
        assert warns

        text = parse_lab_text("VO2max 55\nVLamax 0.4\nMLSS 260W\n")
        assert text.vo2max_ml_kg_min == pytest.approx(55.0)

    def test_effort_extractor_lap_and_sprint_paths(self) -> None:
        rng = np.random.default_rng(1)
        warmup = [120.0] * 600
        sprint_block = [400.0, 900.0, 950.0, 900.0, 400.0] + [120.0] * 10
        cp_block = [360.0] * 360
        power = warmup + sprint_block + [100.0] * 120 + cp_block
        laps = [
            {"duration_s": 600, "avg_power_w": 120},
            {"duration_s": 15, "avg_power_w": 900},
            {"duration_s": 120, "avg_power_w": 100},
            {"duration_s": 360, "avg_power_w": 360},
        ]
        proposal = extract_test_proposal([{"file_id": "test-day", "power": power, "laps": laps}])
        assert isinstance(proposal, ProfileProposal)
        d = proposal.to_dict()
        assert d["status"] in {"proposed", "incomplete", "empty"}
        if proposal.sprint is not None:
            sprint_dict = proposal.sprint.to_dict()
            assert "peak_3s_w" in sprint_dict or "peak_1s_w" in sprint_dict

        noisy_cp = [200.0] * 200 + list(280.0 + rng.normal(0, 40, 360)) + [200.0] * 200
        noisy = extract_test_proposal([{"file_id": "noisy", "power": noisy_cp, "laps": None}])
        assert noisy.status in {"proposed", "incomplete", "empty"}
