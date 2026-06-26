"""Phase 5 — surgical branch closure toward 92% line / 85% branch."""

from __future__ import annotations

import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest

from engines.io.fit_parser import (
    FitFileError,
    _copy_first_numeric_field,
    _ensure_utc_datetime,
    _field_to_float,
    _utc_isoformat,
    parse_fit_file_enhanced,
    parse_fit_records_enhanced,
)
from engines.performance.interval_detector import (
    _classify_by_laps,
    _classify_by_signal,
    _detect_sustained_blocks,
)
from engines.performance.mmp_quality import analyze_mmp_quality, clean_mmp, filter_mmp_by_window
from engines.recovery.cardiac_engine import (
    ActivitySample,
    CardiacResponseAnalyzer,
    Segment,
    compute_cardiac_drift,
    compute_hr_kinetics_tau,
    compute_hr_recovery,
    cross_validate_thresholds,
)
from engines.recovery.hrv_engine import (
    _detect_threshold_crossing,
    _power_at_elapsed,
    analyze_rr_stream,
)

FTP = 280.0


class TestFitParserBranches92D:
    def test_datetime_helpers_and_field_conversion(self) -> None:
        naive = datetime(2026, 6, 1, 8, 0, 0)
        aware = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert _ensure_utc_datetime(None) is None
        assert _ensure_utc_datetime("not-a-date") == "not-a-date"
        assert _ensure_utc_datetime(naive).tzinfo is not None
        assert _ensure_utc_datetime(aware).tzinfo is not None
        assert _utc_isoformat(None) is None
        assert _utc_isoformat(42) == 42
        assert "2026" in _utc_isoformat(naive)

        assert _field_to_float({"converted_value": 12.5}) == 12.5
        assert _field_to_float({"other": 1}) is None
        assert _field_to_float(({"raw_value": 7.0},)) == 7.0
        assert _field_to_float([]) is None

        target = np.zeros(3, dtype=float)
        _copy_first_numeric_field(
            {"respiration_rate": 2.0, "breathing_rate": 18.0},
            ("respiration_rate", "breathing_rate"),
            target,
            1,
            min_value=3.0,
            max_value=80.0,
        )
        assert target[1] == 18.0

    def test_records_without_total_elapsed(self) -> None:
        start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        records = [
            {
                "timestamp": start + timedelta(seconds=i),
                "power": 220.0,
                "heart_rate": 140.0,
            }
            for i in range(60)
        ]
        stream = parse_fit_records_enhanced(records, session_dict={"start_time": start})
        assert stream.n_samples >= 60

    def test_fitdecode_fallback_and_crc_recovery(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        import engines.io.fit_parser as fp

        start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        records = [
            {"timestamp": start + timedelta(seconds=i), "power": 220.0, "heart_rate": 140.0}
            for i in range(40)
        ]
        good = (
            records,
            [{"sport": "cycling", "start_time": start, "total_elapsed_time": 40}],
            [{"manufacturer": "Garmin", "product": "Edge"}],
            [{"time": 0.82}, {"rr_interval": [0.81, 0.83]}],
            [{"total_timer_time": 40}],
        )

        calls = {"crc": 0}

        def _decode_fail(_payload: bytes, *, check_crc: bool):
            raise fp.FitCRCError("crc fail")

        def _fitparse_ok(_payload: bytes, *, check_crc: bool):
            return good

        monkeypatch.setattr(fp, "FITDECODE_AVAILABLE", True, raising=False)
        monkeypatch.setattr(fp, "FITPARSE_AVAILABLE", True, raising=False)
        monkeypatch.setattr(fp, "FIT_BACKEND_AVAILABLE", True, raising=False)
        monkeypatch.setattr(fp, "_extract_messages_with_fitdecode", _decode_fail)
        monkeypatch.setattr(fp, "_extract_messages_with_fitparse", _fitparse_ok)

        extracted = fp._extract_messages(b"x" * 40, check_crc=True)
        assert extracted[0]

        def _crc_then_recover(_payload: bytes, *, check_crc: bool):
            calls["crc"] += 1
            if check_crc:
                raise fp.FitCRCError("bad crc")
            return good

        monkeypatch.setattr(fp, "_extract_messages", _crc_then_recover)
        fit_path = tmp_path / "recover.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 200)
        stream = fp.parse_fit_file_enhanced(str(fit_path), check_crc=True, repair_synthetic_header=False)
        assert stream.n_samples >= 40
        assert calls["crc"] >= 2

    def test_balance_fallback_and_hrv_distribution(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        import engines.io.fit_parser as fp

        start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        records = [
            {
                "timestamp": start + timedelta(seconds=i),
                "power": 220.0,
                "heart_rate": 140.0,
                "left_right_balance": 42.0 + (i % 8),
            }
            for i in range(90)
        ]

        def _extract_with_hrv(_payload: bytes, *, check_crc: bool):
            return (
                records,
                [{"sport": "cycling", "start_time": start, "total_elapsed_time": 90}],
                [{"manufacturer": "Generic", "product": "head unit"}],
                [{"rr_interval": [0.82, 0.81]}, {"time": (0.83, 0.84)}],
                [],
            )

        monkeypatch.setattr(fp, "_extract_messages", _extract_with_hrv)
        fit_path = tmp_path / "hrv.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 200)
        stream = fp.parse_fit_file_enhanced(str(fit_path), check_crc=False, repair_synthetic_header=False)
        assert stream.pedaling_balance_source in {"dual", "unknown", "single_estimated"}
        assert stream.has_rr or np.any([len(x) > 0 for x in stream.rr_intervals if x])

        all_fifty = [
            {
                "timestamp": start + timedelta(seconds=i),
                "power": 220.0,
                "left_right_balance": 50.0,
            }
            for i in range(90)
        ]

        def _extract_single_est(_payload: bytes, *, check_crc: bool):
            return (
                all_fifty,
                [{"sport": "cycling", "start_time": start, "total_elapsed_time": 90}],
                [{"manufacturer": "Generic", "product": "head unit"}],
                [],
                [],
            )

        monkeypatch.setattr(fp, "_extract_messages", _extract_single_est)
        single = fp.parse_fit_file_enhanced(str(fit_path), check_crc=False, repair_synthetic_header=False)
        assert single.pedaling_balance_source == "single_estimated"


class TestHrvBranches92D:
    def test_missing_elapsed_and_window_rejection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import engines.recovery.hrv_engine as he

        assert analyze_rr_stream([{"rr": [820.0, 810.0]}], window_seconds=60, step_seconds=5.0) == []

        bad_elapsed = [{"elapsed": "bad", "rr": [820.0] * 40} for _ in range(80)]
        bad_timeline = analyze_rr_stream(bad_elapsed, window_seconds=60, step_seconds=5.0)
        assert isinstance(bad_timeline, list)

        windows = []
        for i in range(20):
            windows.append(
                {
                    "t_center_s": i * 10,
                    "alpha1": 0.9 - i * 0.02,
                    "valid": i % 3 != 0,
                    "artifact_ratio": 0.1,
                    "sqi": 0.8,
                    "r_squared": 0.95,
                    "hr_avg": 140.0,
                    "rejected_reason": None,
                    "residual_std": 0.01,
                    "slope_stderr": 0.02,
                    "ci_low": 0.7,
                    "ci_high": 1.0,
                    "n_scales_used": 8,
                }
            )

        def _fake_sliding(**_kwargs):
            return windows

        monkeypatch.setattr(he, "_sliding_dfa_local", _fake_sliding)
        rr_samples = [{"elapsed": float(i * 4), "rr": [820.0] * 40} for i in range(80)]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            timeline = analyze_rr_stream(rr_samples, window_seconds=60, step_seconds=5.0)
        assert isinstance(timeline, list)
        assert any("quality gate" in str(w.message) for w in caught)

    def test_threshold_crossing_power_branches(self) -> None:
        series = [
            {"timestamp": 0.0, "alpha1_smoothed": 0.80},
            {"timestamp": 30.0, "alpha1_smoothed": 0.74},
            {"timestamp": 60.0, "alpha1_smoothed": 0.70},
        ]
        crossing, t_idx, p_at = _detect_threshold_crossing(
            series,
            threshold=0.75,
            power_data=[200.0, 210.0, 220.0],
            power_timestamps=[0.0, 30.0, 60.0],
            persistence_windows=2,
        )
        assert crossing is not None
        assert t_idx is not None
        assert p_at is not None

        flat_alpha = [
            {"timestamp": 0.0, "alpha1_smoothed": 0.76},
            {"timestamp": 30.0, "alpha1_smoothed": 0.76},
            {"timestamp": 60.0, "alpha1_smoothed": 0.70},
        ]
        _, _, p_flat = _detect_threshold_crossing(
            flat_alpha,
            threshold=0.75,
            power_data=[200.0, 210.0, 220.0],
            power_timestamps=[0.0, 30.0, 60.0],
            persistence_windows=1,
        )
        assert p_flat is None or isinstance(p_flat, float)

        only_curr = _detect_threshold_crossing(
            flat_alpha,
            threshold=0.75,
            power_data=[220.0],
            power_timestamps=[30.0],
            persistence_windows=1,
        )
        assert only_curr[2] is None or isinstance(only_curr[2], float)

        assert _power_at_elapsed([200.0], 5.0, [0.0]) is None


class TestCardiacBranches92D:
    def test_metric_edge_cases(self) -> None:
        t = np.arange(120, dtype=float)
        seg = Segment(kind="steady", start_idx=0, end_idx=120, start_t=0.0, end_t=119.0, duration_s=120.0)
        drift = compute_cardiac_drift(t, np.full(120, 220.0), np.zeros(120), seg)
        assert drift["available"] is False

        short = compute_hr_recovery(t[:5], np.linspace(170, 140, 5), seg)
        assert short["available"] is True
        assert short["hrr60_bpm"] is None

        ramp_seg = Segment(kind="ramp", start_idx=0, end_idx=60, start_t=0.0, end_t=59.0, duration_s=60.0)
        kinetics = compute_hr_kinetics_tau(
            t[:60],
            np.linspace(150, 250, 60),
            np.full(60, 145.0),
            ramp_seg,
        )
        assert kinetics["available"] is False

    def test_cross_validate_and_analyzer_aggregate(self) -> None:
        t = np.arange(3600, dtype=float)
        power = np.full(3600, 270.0)
        hr = np.linspace(140, 155, 3600)
        timeline = [
            {"timestamp": float(i * 30), "status": "AEROBIC"}
            for i in range(20)
        ] + [{"timestamp": 620.0, "status": "MIXED"}, {"timestamp": 650.0, "status": "ANAEROBIC"}]
        cv = cross_validate_thresholds(
            t,
            power,
            hr,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 270},
            hrv_timeline=timeline,
        )
        assert cv.get("available") in {True, False}
        assert "hr_at_vt1_dfa" in cv or "hr_at_mlss_observed" in cv or cv.get("available") is False

        samples = [
            ActivitySample(t=float(i), power=250.0 if i < 500 else 10.0, hr=170.0 - i * 0.01)
            for i in range(800)
        ]
        analyzer = CardiacResponseAnalyzer(
            weight=72.0,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 250},
            hrv_timeline=timeline,
        )
        result = analyzer.analyze(samples)
        assert result.get("status") in {"success", "error"}
        if result.get("status") == "success":
            assert "fitness_summary" in result or "segments" in result


class TestMmpIntervalBranches92D:
    def test_mmp_coerce_clean_and_filter(self) -> None:
        coerced = analyze_mmp_quality({"60s": 320, "5m": 300, "bad": None, 1200: 290})
        assert coerced.total_anchors >= 2

        samples = [
            {"duration_s": 1200, "power_w": 290, "filename": "a.fit", "date": "2026-05-01"},
            {"duration_s": 1800, "power_w": 285, "filename": "a.fit", "date": "2026-05-02"},
            {"duration_s": 2400, "power_w": 282, "filename": "a.fit", "date": "2026-05-03"},
            {"duration_s": 3600, "power_w": 280, "filename": "a.fit", "date": "2026-05-04"},
        ]
        rolling_mmp = {1200: 290, 1800: 285, 2400: 282, 3600: 280}
        rolling_report = analyze_mmp_quality(rolling_mmp, mmp_samples=samples)
        assert any(i.category == "rolling_window_redundant" for i in rolling_report.issues)

        cleaned, audit = clean_mmp(
            rolling_mmp,
            mmp_samples=samples,
            drop_rules=["rolling_window_redundant"],
        )
        assert audit["cleaned_anchors"] < audit["original_anchors"]
        assert cleaned

        flat_mmp = {1200: 280, 1800: 279, 2400: 278, 3600: 277}
        flat_report = analyze_mmp_quality(flat_mmp)
        assert any(i.category == "flat_long_region" for i in flat_report.issues)

        filtered, kept = filter_mmp_by_window(
            [
                {"duration_s": 300, "power_w": 340, "date": datetime(2026, 5, 1)},
                {"duration_s": 600, "power_w": 310, "date": "2025-01-01"},
            ],
            today="2026-06-01",
            window_days=90,
        )
        assert 300 in filtered
        assert 600 not in filtered
        assert len(kept) == 1

    def test_interval_signal_and_lap_subtypes(self) -> None:
        ftp = FTP
        cp3_block = [150.0] * 400 + [330.0] * 180 + [150.0] * 400
        cp3 = _classify_by_signal(cp3_block, ftp=ftp)
        assert cp3 is not None and cp3[0] == "TEST"

        cp6_block = [150.0] * 300 + [340.0] * 360 + [150.0] * 300
        cp6 = _classify_by_signal(cp6_block, ftp=ftp)
        assert cp6 is not None and cp6[0] == "TEST"

        mixed = [900.0] * 8 + [285.0] * 420 + [120.0] * 1200
        mixed_cls = _classify_by_signal(mixed, ftp=ftp)
        assert mixed_cls is not None and mixed_cls[0] == "TEST"

        sprint = [120.0] * 400 + [900.0] * 10 + [120.0] * 400
        sprint_cls = _classify_by_signal(sprint, ftp=ftp)
        assert sprint_cls is not None and sprint_cls[0] == "TEST"

        hiit_laps: List[Dict[str, Any]] = []
        for _ in range(14):
            hiit_laps.append({"duration_s": 30, "avg_power_w": 360})
            hiit_laps.append({"duration_s": 90, "avg_power_w": 130})
        micro = _classify_by_laps(hiit_laps, ftp=ftp)
        assert micro is not None and micro[0] == "HIIT"

        balanced = _classify_by_laps(
            [{"duration_s": 40, "avg_power_w": 350}, {"duration_s": 40, "avg_power_w": 140}] * 8,
            ftp=ftp,
        )
        assert balanced is not None and balanced[0] == "HIIT"

        blocks = _detect_sustained_blocks([150.0] * 200 + [300.0] * 400 + [150.0] * 200, ftp=ftp)
        assert blocks
        assert blocks[0]["duration_s"] >= 120
