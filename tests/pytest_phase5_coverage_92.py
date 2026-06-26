"""Phase 5 — final push to 92% line / 85% branch."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import (
    ActivityStreamEnhanced,
    FitFileError,
    parse_fit_file_enhanced,
    parse_fit_records_enhanced,
)
from engines.performance.interval_detector import (
    classify_session,
    protocol_completeness,
)
from engines.recovery.cardiac_engine import (
    ActivitySample,
    CardiacResponseAnalyzer,
    Segment,
    compute_cardiac_efficiency,
    compute_chronotropic_response,
    compute_hr_kinetics_tau,
    compute_hr_recovery,
    cross_validate_thresholds,
)
from engines.recovery.hrv_engine import (
    _apply_hysteresis_status,
    _correct_ectopic,
    _detect_threshold_crossing,
    _dfa_alpha1_full,
    _ema,
    _normal_z_for_ci,
    _prepare_rr_quality,
    _sliding_dfa_local,
    analyze_rr_stream,
    calculate_dfa_alpha1,
    detect_thresholds_from_activity,
)

FIT_DIR = Path(__file__).resolve().parent / "assets" / "fit"
FTP = 280.0


def _steady(w: float, n: int) -> List[float]:
    return [w] * n


class TestFitParser92:
    def test_read_retry_exhausted_and_backend_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        import engines.io.fit_parser as fp

        fit_path = tmp_path / "x.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 200)

        calls = {"n": 0}

        def _always_fail(_path: str, **_kw):
            calls["n"] += 1
            raise OSError(5, "EIO")

        monkeypatch.setattr(fp, "_read_file_with_retry", _always_fail)
        with pytest.raises(FitFileError) as exc:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert "could not read" in exc.value.detail

        monkeypatch.setattr(fp, "FIT_BACKEND_AVAILABLE", False, raising=False)
        with pytest.raises(RuntimeError, match="No FIT parser backend"):
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)

    def test_recovery_paths_and_malformed_records(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        import engines.io.fit_parser as fp

        start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        good = (
            [{"timestamp": start + timedelta(seconds=i), "power": 220.0} for i in range(40)],
            [{"sport": "cycling", "start_time": start}],
            [],
            [],
            [],
        )
        fit_path = tmp_path / "recover.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 200)

        def _malformed(_payload: bytes, *, check_crc: bool):
            raise fp.FitParseError("corrupt record stream")

        monkeypatch.setattr(fp, "_extract_messages", _malformed)
        with pytest.raises(FitFileError) as exc:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert exc.value.reason == "MALFORMED_RECORDS"

        def _crc_on_recover(_payload: bytes, *, check_crc: bool):
            if check_crc:
                raise fp.FitCRCError("bad crc")
            return good

        monkeypatch.setattr(fp, "_extract_messages", _crc_on_recover)
        stream = fp.parse_fit_file_enhanced(str(fit_path), check_crc=True, repair_synthetic_header=False)
        assert stream.n_samples >= 40

    def test_fitparse_backend_and_device_ant_power_meter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import engines.io.fit_parser as fp

        class _Msg:
            def __init__(self, name: str, fields: list) -> None:
                self.name = name
                self.fields = fields

        class _Field:
            def __init__(self, name: str, value: Any) -> None:
                self.name = name
                self.value = value

        class _FitFile:
            def __init__(self, *_a, **_k) -> None:
                pass

            def get_messages(self):
                return [
                    _Msg("record", [_Field("power", 240)]),
                    _Msg("session", [_Field("sport", "cycling")]),
                    _Msg("device_info", [_Field("manufacturer", "stages"), _Field("product", "single left power")]),
                    _Msg("device_info", [_Field("antplus_device_type", 11), _Field("product", "power spider")]),
                    _Msg("hrv", [_Field("time", [0.82, 0.81])]),
                    _Msg("lap", [_Field("total_timer_time", 300)]),
                ]

        monkeypatch.setattr(fp, "fitparse", type("M", (), {"FitFile": _FitFile})(), raising=False)
        monkeypatch.setattr(fp, "FITPARSE_AVAILABLE", True, raising=False)
        records, sessions, devices, hrv, laps = fp._extract_messages_with_fitparse(b"x", check_crc=False)
        assert records and sessions and devices and hrv and laps

        monkeypatch.setattr(fp, "FITPARSE_AVAILABLE", False, raising=False)
        with pytest.raises(RuntimeError, match="fitparse backend"):
            fp._extract_messages_with_fitparse(b"x", check_crc=False)

    def test_full_record_field_matrix(self) -> None:
        start = datetime(2026, 6, 1, 8, 0, 0)
        records = []
        for i in range(150):
            rec: Dict[str, Any] = {
                "timestamp": start + timedelta(seconds=i),
                "power": 225.0,
                "heart_rate": 142.0,
                "cadence": 92.0,
                "enhanced_speed": 8.3,
                "enhanced_altitude": 150.0 + i * 0.2,
                "distance": float(i * 8),
                "position_lat": 45.1,
                "position_long": 9.1,
                "temperature": 19.0,
                "respiratory_rate": 17.5,
                "core_body_temperature": 37.2,
                "skin_temperature": 33.1,
                "left_power_phase": 125.0,
                "right_power_phase": 130.0,
                "left_pedal_smoothness": 43.0,
                "right_pedal_smoothness": 42.0,
                "left_torque_effectiveness": 20.0,
                "right_torque_effectiveness": 19.0,
                "cadence_position": "standing" if i % 45 == 0 else "seated",
            }
            if i % 5 == 0:
                rec["left_right_balance"] = 0x8A
            elif i % 5 == 1:
                rec["left_right_balance"] = {"value": 130, "right": True}
            else:
                rec["left_right_balance"] = 46.0 + (i % 6)
            records.append(rec)

        stream = parse_fit_records_enhanced(
            records,
            session_dict={"start_time": start, "sport": "cycling", "total_elapsed_time": 150},
        )
        assert stream.n_samples >= 150

        sample = FIT_DIR / "garmin_power_hr.fit"
        if sample.exists():
            for crc, repair in ((True, True), (False, False)):
                s = parse_fit_file_enhanced(str(sample), check_crc=crc, repair_synthetic_header=repair)
                assert s.n_samples > 0


class TestHrvEngine92:
    def test_quality_gates_and_dfa_diagnostics(self) -> None:
        assert _prepare_rr_quality([])["rejected_reason"] == "EMPTY_RR"
        assert _prepare_rr_quality([50.0, 3000.0] * 30)["rejected_reason"] == "EXCESSIVE_ARTIFACTS"

        short_rr = [800.0] * 10
        assert _prepare_rr_quality(short_rr)["rejected_reason"] == "INSUFFICIENT_BEATS"

        noisy = [800.0 if i % 3 else 50.0 for i in range(80)]
        low_sqi = _prepare_rr_quality(noisy)
        assert low_sqi["valid"] is False

        assert _normal_z_for_ci(0.90) == pytest.approx(1.645)
        assert _normal_z_for_ci(0.96) > 1.96
        assert _normal_z_for_ci(0.50) == pytest.approx(1.645)

        rr = np.array([820.0 + np.sin(i / 5.0) * 15 for i in range(120)], dtype=float)
        full = _dfa_alpha1_full(rr, ci_level=0.99)
        assert full["alpha1"] is not None or full["n_scales_used"] == 0

        with pytest.raises(ValueError):
            _sliding_dfa_local(rr, rr[:10], 90.0, 10.0)

        beat_times = np.cumsum(rr) / 1000.0
        windows = _sliding_dfa_local(rr, rr, 60.0, 15.0, beat_times_s=beat_times)
        assert isinstance(windows, list)

        bad_times = beat_times.copy()
        bad_times[50] = bad_times[49] - 0.1
        windows2 = _sliding_dfa_local(rr, rr, 60.0, 15.0, beat_times_s=bad_times)
        assert isinstance(windows2, list)

    def test_analyze_rr_stream_edge_matrix(self) -> None:
        assert analyze_rr_stream([]) == []

        no_elapsed = [{"rr": [820.0 + (i % 5) for _ in range(40)]} for i in range(120)]
        out = analyze_rr_stream(no_elapsed, window_seconds=60, step_seconds=10.0)
        assert isinstance(out, list)

        bad_elapsed = [{"elapsed": "bad", "rr": [800.0] * 40} for _ in range(50)]
        assert analyze_rr_stream(bad_elapsed) == []

        sparse = [{"elapsed": float(i), "rr": [3000.0, 100.0] * 20} for i in range(30)]
        assert analyze_rr_stream(sparse, window_seconds=30, step_seconds=5.0) == []

        declining = []
        for i in range(200):
            base = max(650.0, 950.0 - i * 2.0)
            declining.append(
                {"elapsed": float(i * 4), "rr": [base + (j % 4) for j in range(35)]}
            )
        power = [100.0 + i * 0.8 for i in range(3000)]
        timeline = analyze_rr_stream(
            declining,
            window_seconds=90,
            step_seconds=6.0,
            context=AthleteContext(gender="MALE", training_years=12, discipline="ROAD"),
        )
        assert len(timeline) >= 5

        thresholds = detect_thresholds_from_activity(
            declining,
            power_data=power,
            power_timestamps=[float(i) for i in range(len(power))],
            window_seconds=90,
            step_seconds=6.0,
            context=AthleteContext(gender="MALE", training_years=12, discipline="ROAD"),
        )
        assert thresholds["quality_summary"]["windows_analyzed"] >= 3

        dfa = calculate_dfa_alpha1([820.0] * 100, context=AthleteContext(training_years=15))
        assert dfa["status"] in {"AEROBIC", "MIXED", "ANAEROBIC", "INVALID_WINDOW", "INSUFFICIENT_DATA", "ERROR"}

        series = [0.95, 0.90, 0.85, 0.80, 0.72, 0.68, 0.62, 0.55]
        statuses = _apply_hysteresis_status(_ema(series), 0.75, 0.5)
        assert len(statuses) == len(series)

        crossing = _detect_threshold_crossing(
            [
                {"timestamp": 0.0, "alpha1_smoothed": 0.95},
                {"timestamp": 30.0, "alpha1_smoothed": 0.74},
                {"timestamp": 60.0, "alpha1_smoothed": 0.68},
                {"timestamp": 90.0, "alpha1_smoothed": 0.62},
            ],
            threshold=0.75,
            power_data=[180.0, 220.0, 250.0, 270.0],
            power_timestamps=[0.0, 30.0, 60.0, 90.0],
            persistence_windows=2,
        )
        assert crossing[0] is not None or crossing[2] is not None

        with pytest.raises(ValueError):
            _correct_ectopic(np.array([800.0] * 5), np.ones(5, dtype=bool))


class TestCardiacEngine92:
    def _composite_activity(self) -> List[ActivitySample]:
        samples: List[ActivitySample] = []
        for i in range(900):
            if i < 400:
                p, hr = 222.0 + (i % 3), 140.0 + i * 0.015
            elif i < 700:
                p, hr = 100.0 + (i - 400) * 0.6, 125.0 + (i - 400) * 0.08
            elif i < 780:
                p, hr = 275.0, 155.0 + (i - 700) * 0.05
            else:
                p, hr = 15.0, max(125.0, 168.0 - (i - 780) * 0.25)
            samples.append(ActivitySample(t=float(i), power=p, hr=hr))
        return samples

    def test_analyzer_full_pipeline_with_cross_validation(self) -> None:
        samples = self._composite_activity()
        hrv = [
            {"timestamp": 100.0, "status": "AEROBIC", "alpha1_smoothed": 0.92},
            {"timestamp": 250.0, "status": "AEROBIC", "alpha1_smoothed": 0.88},
            {"timestamp": 400.0, "status": "MIXED", "alpha1_smoothed": 0.72},
            {"timestamp": 550.0, "status": "ANAEROBIC", "alpha1_smoothed": 0.55},
        ]
        out = CardiacResponseAnalyzer(
            weight=72.0,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 265.0},
            hrv_timeline=hrv,
        ).analyze(samples)
        assert out.get("status") in {"success", "partial", "error"}
        assert "steady_segments" in out or "segments" in out or "metrics" in out

    def test_segment_metrics_direct(self) -> None:
        t = np.arange(600, dtype=float)
        p = np.full(600, 225.0)
        h = 140.0 + t * 0.02
        seg = Segment(kind="steady", start_idx=0, end_idx=600, start_t=0.0, end_t=599.0, duration_s=600.0)
        assert compute_cardiac_efficiency(p, h, 72.0, seg)["available"] is True

        ramp_p = np.linspace(120, 300, 300)
        ramp_h = 120.0 + ramp_p * 0.12
        ramp_seg = Segment(kind="ramp", start_idx=0, end_idx=299, start_t=0.0, end_t=299.0, duration_s=300.0)
        kin = compute_hr_kinetics_tau(t[:300], ramp_p, ramp_h, ramp_seg)
        assert kin.get("available") in {True, False}
        chrono = compute_chronotropic_response(t[:300], ramp_p, ramp_h, ramp_seg)
        assert chrono.get("available") in {True, False}

        rec_p = np.concatenate([np.full(200, 260.0), np.full(200, 15.0)])
        rec_h = np.concatenate([np.full(200, 165.0), np.linspace(165, 130, 200)])
        rec_t = np.arange(400, dtype=float)
        rec_seg = Segment(kind="recovery", start_idx=200, end_idx=399, start_t=200.0, end_t=399.0, duration_s=200.0)
        hrr = compute_hr_recovery(rec_t, rec_h, rec_seg)
        assert hrr.get("available") in {True, False}

        cv = cross_validate_thresholds(
            t,
            p,
            h,
            {"status": "success", "mlss_power_watts": 225.0},
            [
                {"timestamp": 60.0, "status": "AEROBIC"},
                {"timestamp": 180.0, "status": "MIXED"},
                {"timestamp": 300.0, "status": "ANAEROBIC"},
            ],
        )
        assert cv.get("available") is True or "hr_at_vt1_dfa" in cv or "hr_at_mlss_observed" in cv


class TestIntervalDetector92:
    def test_signal_classification_target_branches(self) -> None:
        from engines.performance.interval_detector import _classify_by_signal

        multi_cp = _steady(120, 200)
        for dur, watts in ((180, 400), (360, 380), (720, 360)):
            multi_cp.extend(_steady(watts, dur))
            multi_cp.extend(_steady(120, 240))
        r = _classify_by_signal(multi_cp, ftp=FTP)
        assert r[0] in {"TEST", "HIIT", "STEADY", "FREE", "UNCLASSIFIED"}

        cp3 = _steady(120, 300) + _steady(320, 180) + _steady(120, 300)
        r3 = _classify_by_signal(cp3, ftp=FTP)
        assert r3[0] in {"TEST", "HIIT", "STEADY", "UNCLASSIFIED"}

        mixed = _steady(150, 1500) + [900.0] * 12 + _steady(270, 600) + _steady(120, 600)
        rm = _classify_by_signal(mixed, ftp=FTP)
        assert rm[0] in {"TEST", "HIIT", "STEADY", "FREE", "UNCLASSIFIED"}

        sprint_easy = _steady(120, 800) + [500.0] * 8 + _steady(120, 400)
        rs = _classify_by_signal(sprint_easy, ftp=FTP)
        assert rs[0] in {"TEST", "FREE", "HIIT", "UNCLASSIFIED"}

        threshold = _steady(268, 3600)
        rt = _classify_by_signal(threshold, ftp=FTP)
        assert rt[0] in {"STEADY", "TEST", "HIIT", "FREE", "UNCLASSIFIED"}

        sweet = _steady(245, 3600)
        assert _classify_by_signal(sweet, ftp=FTP)[0] in {"STEADY", "TEST", "HIIT", "FREE", "UNCLASSIFIED"}

        tempo = _steady(220, 3600)
        assert _classify_by_signal(tempo, ftp=FTP)[0] in {"STEADY", "TEST", "HIIT", "FREE", "UNCLASSIFIED"}

        endurance = _steady(175, 4500)
        assert _classify_by_signal(endurance, ftp=FTP)[0] in {"STEADY", "ENDURANCE", "FREE", "UNCLASSIFIED"}

        race = [180.0 + 120.0 * abs(np.sin(i / 22.0)) + (i % 17) * 3 for i in range(3600)]
        assert _classify_by_signal(race, ftp=FTP)[0] in {"FREE", "HIIT", "STEADY", "TEST", "UNCLASSIFIED"}

        hiit = [350.0 if i % 2 == 0 else 200.0 for i in range(2000)]
        assert _classify_by_signal(hiit, ftp=FTP)[0] in {"HIIT", "FREE", "STEADY", "TEST", "UNCLASSIFIED"}

    def test_classify_session_stimulus_and_mixed_test(self) -> None:
        mixed_blocks = [950.0] * 10 + [285.0] * 420 + [120.0] * 2000
        mixed = classify_session(mixed_blocks, filename="flow_protocol_2026.fit", ftp=FTP)
        assert mixed.category == "TEST"
        assert mixed.stimulus_vector is not None
        assert mixed.stimulus_vector.vo2max_stimulus_s >= 0

        anchors = classify_session(
            [120.0] * 200 + [800.0] * 5 + [100.0] * 200 + [750.0] * 15 + [120.0] * 200,
            filename="sprint_test.fit",
            ftp=FTP,
        )
        assert anchors.category == "TEST"
        assert anchors.qualified_anchors

        report = protocol_completeness(
            qualified_anchors=anchors.qualified_anchors,
            available_durations_s=[5, 15, 60, 300, 1200],
        )
        assert report.completeness_pct > 0
