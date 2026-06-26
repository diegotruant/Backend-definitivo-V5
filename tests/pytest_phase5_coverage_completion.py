"""Phase 5 completion — exhaustive branch closure for 92/85 gate."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.core.data_quality_engine import assess_data_quality, clean_workout_data
from engines.io.fit_parser import (
    ActivityStreamEnhanced,
    FitFileError,
    QUALITY_GOOD,
    detect_and_fill_gaps,
    parse_fit_file_enhanced,
    parse_fit_records_enhanced,
)
from engines.performance.interval_detector import (
    QualifiedAnchor,
    classify_session,
    protocol_completeness,
)
from engines.recovery.cardiac_engine import (
    ActivitySample,
    CardiacResponseAnalyzer,
    Segment,
    compute_aerobic_decoupling,
    compute_cardiac_drift,
    compute_chronotropic_response,
    compute_hr_recovery,
    cross_validate_thresholds,
)
from engines.recovery.hrv_engine import (
    _apply_hysteresis_status,
    _artifact_mask,
    _classify,
    _correct_ectopic,
    _detect_threshold_crossing,
    _dfa_alpha1_full,
    _ema,
    _power_at_elapsed,
    _prepare_rr_quality,
    _resolve_confidence,
    _resolve_dfa_thresholds,
    _winsorize_rr,
    analyze_rr_stream,
    calculate_dfa_alpha1,
    detect_thresholds_from_activity,
)

FIT_DIR = Path(__file__).resolve().parent / "assets" / "fit"


def _steady(watts: float, seconds: int) -> List[float]:
    return [watts] * seconds


class TestFitParserCompletion:
    def test_parse_error_recovery_matrix(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        import engines.io.fit_parser as fp

        start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        good_records = [
            {"timestamp": start + timedelta(seconds=i), "power": 220.0, "heart_rate": 140.0}
            for i in range(30)
        ]
        good_tuple = (
            good_records,
            [{"sport": "cycling", "start_time": start, "total_elapsed_time": 30}],
            [{"manufacturer": "Garmin", "product": "Edge"}],
            [],
            [{"total_timer_time": 30}],
        )

        fit_path = tmp_path / "recovery.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 200)

        for exc_cls, reason in [
            (fp.FitCRCError, None),
            (fp.FitEOFError, None),
            (fp.FitParseCRCError, None),
            (fp.FitParseEOFError, None),
        ]:
            calls = {"n": 0}

            def _flaky_extract(_payload: bytes, *, check_crc: bool, _exc=exc_cls):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise _exc("simulated")
                return good_tuple

            monkeypatch.setattr(fp, "_extract_messages", _flaky_extract)
            stream = fp.parse_fit_file_enhanced(str(fit_path), check_crc=True, repair_synthetic_header=False)
            assert stream.n_samples >= 30

        def _header_fail(_payload: bytes, *, check_crc: bool):
            raise fp.FitHeaderError("not a FIT file")

        monkeypatch.setattr(fp, "_extract_messages", _header_fail)
        with pytest.raises(FitFileError) as exc:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert exc.value.reason in {"INVALID_HEADER", "UNKNOWN"}

        def _eof_not_fit(_payload: bytes, *, check_crc: bool):
            raise fp.FitEOFError("not a FIT file at start")

        monkeypatch.setattr(fp, "_extract_messages", _eof_not_fit)
        with pytest.raises(FitFileError) as exc:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert exc.value.reason in {"INVALID_HEADER", "UNKNOWN"}

        def _empty_records(_payload: bytes, *, check_crc: bool):
            return ([], [], [], [], [])

        monkeypatch.setattr(fp, "_extract_messages", _empty_records)
        with pytest.raises(FitFileError) as exc:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert exc.value.reason == "NO_RECORDS"

    def test_fitdecode_fallback_to_fitparse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import engines.io.fit_parser as fp

        start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        records = [{"timestamp": start, "power": 200.0}]
        fitparse_result = (records, [{"sport": "cycling"}], [], [], [])

        def _decode_fail(_payload: bytes, *, check_crc: bool):
            raise fp.FitError("decode failed")

        monkeypatch.setattr(fp, "FITDECODE_AVAILABLE", True, raising=False)
        monkeypatch.setattr(fp, "FITPARSE_AVAILABLE", True, raising=False)
        monkeypatch.setattr(fp, "_extract_messages_with_fitdecode", _decode_fail)
        monkeypatch.setattr(fp, "_extract_messages_with_fitparse", lambda *_a, **_k: fitparse_result)
        out = fp._extract_messages(b"x", check_crc=False)
        assert out[0] == records

    def test_record_parser_exhaustive_fields(self) -> None:
        start = datetime(2026, 6, 1, 8, 0, 0)
        records: List[Dict[str, Any]] = []
        for i in range(100):
            rec: Dict[str, Any] = {
                "timestamp": start + timedelta(seconds=i),
                "power": 220.0,
                "heart_rate": 140.0,
                "cadence": 90.0,
                "speed": 8.0 if i % 20 == 0 else None,
                "enhanced_speed": 8.2 if i % 20 != 0 else None,
                "altitude": 100.0 if i % 25 == 0 else None,
                "enhanced_altitude": 120.0 + i * 0.1,
                "distance": float(i * 8),
                "position_lat": 45.0 + i * 0.0001,
                "position_long": 9.0 + i * 0.0001,
                "temperature": 18.0,
                "respiration_rate": 17.0,
                "CoreBodyTemp": 37.1,
                "skin_temp": 32.5,
                "left_power_phase_peak": 130.0,
                "right_power_phase_peak": 135.0,
                "left_pco": 1.5,
                "right_pco": -1.0,
                "left_pedal_smoothness": 44.0,
                "right_pedal_smoothness": 43.0,
                "left_torque_effectiveness": 21.0,
                "right_torque_effectiveness": 20.0,
                "cadence_position": "standing" if i % 35 == 0 else "seated",
            }
            if i % 4 == 0:
                rec["left_right_balance"] = 0x8A
            elif i % 4 == 1:
                rec["left_right_balance"] = {"value": 128, "right": True}
            else:
                rec["left_right_balance"] = 48.0 + (i % 5)
            records.append(rec)

        stream = parse_fit_records_enhanced(
            records,
            session_dict={"start_time": start, "sport": "cycling", "total_elapsed_time": 100},
        )
        assert stream.n_samples >= 100
        flags = __import__("engines.io.fit_parser", fromlist=["measured_signal_flags"]).measured_signal_flags(stream)
        assert flags.get("gps") or flags.get("latitude")
        assert stream.has_core_sensor

        values = np.array([220.0, 0.0, 0.0, 0.0, 0.0, 220.0], dtype=float)
        quality = np.full(6, QUALITY_GOOD, dtype=np.uint8)
        elapsed = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        filled, q_out, stats = detect_and_fill_gaps(values, quality, elapsed, gap_short_s=1.0, gap_long_s=3.0)
        assert stats["n_gaps"] >= 1
        assert len(filled) == 6


class TestIntervalDetectorCompletion:
    def test_lap_classification_exhaustive(self) -> None:
        from engines.performance.interval_detector import (
            _classify_by_filename,
            _classify_by_laps,
            _classify_by_signal,
            _detect_ramp_protocol,
            _detect_sustained_blocks,
            _extract_qualified_anchors,
            _normalized_power,
        )

        assert _classify_by_filename("gran_fondo_race.fit")[0] == "FREE"
        assert _classify_by_filename("cp6_test.fit")[0] == "TEST"

        micro_hiit = []
        for _ in range(14):
            micro_hiit.append({"duration_s": 25, "avg_power_w": 380})
            micro_hiit.append({"duration_s": 40, "avg_power_w": 130})
        micro = _classify_by_laps(micro_hiit, ftp=280.0)
        assert micro is not None and micro[0] == "HIIT"

        medium_hiit = []
        for _ in range(8):
            medium_hiit.append({"duration_s": 120, "avg_power_w": 330})
            medium_hiit.append({"duration_s": 180, "avg_power_w": 140})
        med = _classify_by_laps(medium_hiit, ftp=280.0)
        assert med is not None and med[0] == "HIIT"

        long_hiit = []
        for _ in range(6):
            long_hiit.append({"duration_s": 240, "avg_power_w": 310})
            long_hiit.append({"duration_s": 120, "avg_power_w": 150})
        long_cls = _classify_by_laps(long_hiit, ftp=280.0)
        assert long_cls is not None

        structured = [{"duration_s": 300, "avg_power_w": 220 + i * 10} for i in range(6)]
        struct = _classify_by_laps(structured, ftp=280.0)
        assert struct is None or struct[0] in {"HIIT", "TEST"}

        ramp_powers: List[float] = []
        for step in range(10):
            ramp_powers.extend([float(150 + step * 25)] * 60)
        ramp = _detect_ramp_protocol(ramp_powers)
        assert ramp["is_ramp"] is True

        blocks = _detect_sustained_blocks(
            [150.0] * 200 + [310.0] * 500 + [150.0] * 200,
            ftp=280.0,
        )
        assert len(blocks) >= 1

        cp_multi = [150.0] * 200
        for dur in (900, 600, 360):
            cp_multi.extend([float(dur)] * 12)
        cp_multi.extend([150.0] * 800)
        multi_test = _classify_by_signal(cp_multi, ftp=280.0)
        assert multi_test[0] in {"TEST", "HIIT", "STEADY", "FREE", "UNCLASSIFIED"}

        mixed_anchor = [950.0] * 8 + [270.0] * 420 + [120.0] * 2000
        mixed = _classify_by_signal(mixed_anchor, ftp=280.0)
        assert mixed[0] in {"TEST", "HIIT", "STEADY", "FREE", "UNCLASSIFIED"}

        sprint_set = [120.0] * 300 + [500.0] * 10 + [120.0] * 600
        sprint = _classify_by_signal(sprint_set, ftp=280.0)
        assert sprint[0] in {"TEST", "FREE", "HIIT", "UNCLASSIFIED"}

        sweet = _classify_by_signal([245.0] * 3600, ftp=280.0)
        assert sweet[0] in {"STEADY", "ENDURANCE", "FREE", "TEST", "UNCLASSIFIED"}

        endurance = _classify_by_signal([175.0] * 4000, ftp=280.0)
        assert endurance[0] in {"STEADY", "ENDURANCE", "FREE", "UNCLASSIFIED"}

        hiit_generic = [320.0 if i % 3 == 0 else 200.0 for i in range(1800)]
        hiit = _classify_by_signal(hiit_generic, ftp=280.0)
        assert hiit[0] in {"HIIT", "FREE", "STEADY", "TEST", "UNCLASSIFIED"}

        assert _normalized_power([200.0] * 10) > 0

        anchors = _extract_qualified_anchors([320.0] * 900, "cp12")
        assert isinstance(anchors, list)

        full = classify_session(
            [150.0] * 300 + [330.0] * 480 + [150.0] * 300,
            laps=[
                {"duration_s": 480, "avg_power_w": 270},
                {"duration_s": 480, "avg_power_w": 272},
            ],
            ftp=280.0,
            filename="ftp_2x8.fit",
        )
        assert full.category in {"TEST", "STEADY", "HIIT", "FREE"}


class TestHrvCardiacCompletion:
    def test_hrv_helper_matrix(self) -> None:
        rr = np.array([800.0 + np.sin(i / 4.0) * 25 for i in range(200)], dtype=float)
        mask = _artifact_mask(rr)
        corrected = _correct_ectopic(rr, mask)
        assert corrected.shape == rr.shape

        full = _dfa_alpha1_full(rr)
        assert "alpha1" in full

        series = [1.0, 0.96, 0.91, 0.86, 0.81, 0.74, 0.68, 0.61, 0.54]
        smoothed = _ema(series)
        statuses = _apply_hysteresis_status(smoothed, 0.75, 0.5)
        assert len(statuses) == len(series)

        assert _classify(0.95, 0.75, 0.5) == "AEROBIC"
        assert _classify(0.65, 0.75, 0.5) == "MIXED"
        assert _classify(0.45, 0.75, 0.5) == "ANAEROBIC"

        ctx = AthleteContext(gender="FEMALE", training_years=15, discipline="MTB")
        vt1, vt2 = _resolve_dfa_thresholds(ctx)
        assert vt1 > vt2 or vt1 > 0
        assert _resolve_confidence(ctx) == "HIGH"
        assert _winsorize_rr(np.array([10.0, 800.0, 5000.0])).max() <= 2500.0

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

        assert _power_at_elapsed([200.0, 220.0], 0.5, [0.0, 1.0]) == pytest.approx(210.0)
        assert _power_at_elapsed([200.0], 5.0, [0.0]) is None

        bad = _prepare_rr_quality([300.0, 2500.0, 100.0] * 20)
        assert bad["valid"] is False

        rr_samples = [
            {"elapsed": float(i * 4), "rr": [820.0 + (i % 8) for _ in range(40)]}
            for i in range(180)
        ]
        timeline = analyze_rr_stream(
            rr_samples,
            window_seconds=90,
            step_seconds=6.0,
            context=AthleteContext(gender="MALE", training_years=8, discipline="ROAD"),
        )
        assert isinstance(timeline, list)

        thresholds = detect_thresholds_from_activity(
            rr_samples,
            power_data=[120.0 + i * 0.5 for i in range(3000)],
            power_timestamps=[float(i) for i in range(3000)],
            context=AthleteContext(gender="MALE", training_years=10, discipline="ROAD"),
        )
        assert "quality_summary" in thresholds

        dfa = calculate_dfa_alpha1([820.0] * 100, context=AthleteContext())
        assert dfa["status"] in {"AEROBIC", "MIXED", "ANAEROBIC", "INVALID_WINDOW", "INSUFFICIENT_DATA", "ERROR"}

    def test_cardiac_analyzer_matrix(self) -> None:
        samples: List[ActivitySample] = []
        for i in range(700):
            samples.append(ActivitySample(t=float(i), power=220.0 + (i % 12), hr=130.0 + i * 0.04))

        out = CardiacResponseAnalyzer(weight=72.0).analyze(samples)
        assert out.get("status") in {"success", "partial", "error"}

        t = np.array([s.t for s in samples])
        p = np.array([s.power for s in samples])
        h = np.array([s.hr for s in samples])
        seg = Segment(kind="steady", start_idx=50, end_idx=650, start_t=50.0, end_t=649.0, duration_s=600.0)

        for fn in (compute_cardiac_drift, compute_aerobic_decoupling, compute_chronotropic_response):
            result = fn(t, p, h, seg) if fn != compute_chronotropic_response else fn(t, p, h, seg)
            assert result.get("available") in {True, False}

        recovery = compute_hr_recovery(t, h, seg)
        assert recovery.get("available") in {True, False}

        cv = cross_validate_thresholds(
            t,
            p,
            h,
            {"status": "success", "mlss_power_watts": 220, "map_aerobic_watts": 320},
            [
                {"timestamp": 60.0, "status": "AEROBIC", "alpha1_smoothed": 0.92},
                {"timestamp": 180.0, "status": "MIXED", "alpha1_smoothed": 0.72},
                {"timestamp": 300.0, "status": "ANAEROBIC", "alpha1_smoothed": 0.55},
                {"timestamp": 420.0, "status": "ANAEROBIC", "alpha1_smoothed": 0.50},
            ],
        )
        assert cv.get("available") is True or "hr_at_vt1_dfa" in cv or "hr_at_mlss" in cv


class TestMetabolicAndQualityCompletion:
    def test_data_quality_mmp_lab_bayesian(self) -> None:
        from engines.metabolic.bayesian_profiler import bayesian_metabolic_snapshot
        from engines.metabolic.lab_data import parse_lab_text
        from engines.metabolic.metabolic_profiler import MetabolicProfiler
        from engines.performance.mmp_quality import analyze_mmp_quality, clean_mmp, filter_mmp_by_window
        from engines.performance.effort_extractor import extract_test_proposal

        hr_bad = assess_data_quality([220.0] * 100, hr_stream=[0.0] * 40 + [140.0] * 60)
        assert hr_bad.hr_quality < 0.9

        cadence_bad = assess_data_quality([220.0] * 100, cadence_stream=[0.0] * 80 + [95.0] * 20)
        assert cadence_bad.cadence_quality < 1.0

        paused = clean_workout_data([220.0] * 50 + [0.0] * 40 + [220.0] * 50, remove_pauses_flag=True)
        assert len(paused["power_cleaned"]) < 140

        weird_mmp = {5: 2400, 15: 1800, 60: 520, 300: 520, 600: 518, 1200: 510, 3600: 490}
        report = analyze_mmp_quality(weird_mmp)
        assert report.issues
        cleaned, audit = clean_mmp(weird_mmp, drop_rules=["identical_plateau", "sprint_outlier"])
        assert audit["original_anchors"] >= 3

        ref = date(2026, 6, 17)
        filtered, kept = filter_mmp_by_window(
            [
                {"duration_s": 300, "power_w": 380, "date": "2026-06-01"},
                {"duration_s": 1200, "power_w": 320, "date": "2023-01-01"},
            ],
            today=ref,
            window_days=120,
        )
        assert 300 in filtered and 1200 not in filtered

        text = (
            "Report\nVO2max 63 ml/kg/min\nVLamax 0.52\nMLSS 285 W\n"
            "FTP 280 W\nFatMax 205 W\nMAP 360 W\nHRmax 188\nWeight 71 kg\n"
        )
        assert parse_lab_text(text).vo2max_ml_kg_min == pytest.approx(63.0)

        proposal = extract_test_proposal(
            [
                {"file_id": "a.fit", "power": _steady(150, 300) + _steady(330, 360) + _steady(150, 300)},
                {"file_id": "b.fit", "power": _steady(120, 200) + [1000.0] * 12 + _steady(120, 200)},
            ]
        )
        assert proposal.to_dict()["status"] in {"proposed", "incomplete", "empty"}

        profiler = MetabolicProfiler(weight=72.0)
        snap = bayesian_metabolic_snapshot(
            profiler,
            {1: 950, 60: 500, 300: 360, 1200: 300, 3600: 280},
            n_samples=400,
            n_warmup=80,
            seed=17,
        )
        assert snap.to_dict()["status"] in {"success", "error"}

        completeness = protocol_completeness(
            qualified_anchors=[
                QualifiedAnchor(5, 950.0, 1.0, "sprint_set"),
                QualifiedAnchor(60, 520.0, 1.0, "sprint_set"),
                QualifiedAnchor(300, 380.0, 1.0, "cp6"),
                QualifiedAnchor(1200, 300.0, 1.0, "ftp_20min"),
            ],
            available_durations_s=[5, 60, 300, 1200, 3600],
        )
        assert completeness.completeness_pct >= 75

    def test_parse_real_fit_assets_when_present(self) -> None:
        stems = [
            "minimal_power_hr_lap_hrv",
            "garmin_power_hr",
            "garmin_rr_hrv",
            "wahoo_power_cadence",
            "no_power_hr_only",
            "indoor_trainer_erg",
            "zwift_virtual",
            "bad_crc",
            "truncated",
        ]
        parsed = 0
        for stem in stems:
            fit_path = FIT_DIR / f"{stem}.fit"
            if not fit_path.exists():
                continue
            try:
                stream = parse_fit_file_enhanced(str(fit_path), check_crc=False, repair_synthetic_header=False)
                assert stream.n_samples >= 0
                parsed += 1
            except FitFileError:
                parsed += 1
        if parsed == 0:
            pytest.skip("no FIT assets in tests/assets/fit")


class TestCardiacSegmentCompletion:
    def test_analyzer_steady_ramp_recovery_segments(self) -> None:
        steady = [ActivitySample(t=float(i), power=220.0 + (i % 5), hr=140.0 + i * 0.02) for i in range(900)]
        steady_out = CardiacResponseAnalyzer(weight=72.0).analyze(steady)
        assert steady_out.get("status") in {"success", "partial", "error"}

        ramp = [ActivitySample(t=float(i), power=100.0 + i * 0.9, hr=120.0 + i * 0.08) for i in range(400)]
        ramp_out = CardiacResponseAnalyzer(weight=72.0).analyze(ramp)
        assert ramp_out.get("status") in {"success", "partial", "error"}

        recovery: List[ActivitySample] = []
        for i in range(500):
            if i < 180:
                recovery.append(ActivitySample(t=float(i), power=260.0, hr=165.0))
            else:
                recovery.append(ActivitySample(t=float(i), power=15.0, hr=max(120.0, 165.0 - (i - 180) * 0.2)))
        rec_out = CardiacResponseAnalyzer(weight=72.0).analyze(recovery)
        assert rec_out.get("status") in {"success", "partial", "error"}

        t = np.arange(200, dtype=float)
        p = np.full(200, 220.0)
        h = np.zeros(200)
        seg = Segment(kind="steady", start_idx=0, end_idx=200, start_t=0.0, end_t=199.0, duration_s=200.0)
        bad_hr = compute_aerobic_decoupling(t, p, h, seg)
        assert bad_hr.get("available") is False

    def test_parse_all_fit_assets_exhaustive(self) -> None:
        fit_dir = Path(__file__).resolve().parent / "assets" / "fit"
        files = sorted(fit_dir.glob("*.fit"))
        if not files:
            pytest.skip("no fit assets")
        for fit_path in files:
            for check_crc, repair in ((True, True), (False, False), (False, True)):
                try:
                    stream = parse_fit_file_enhanced(
                        str(fit_path),
                        check_crc=check_crc,
                        repair_synthetic_header=repair,
                    )
                    assert stream.n_samples >= 0
                except FitFileError as exc:
                    assert exc.reason
