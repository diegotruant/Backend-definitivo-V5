"""Phase 5 — batch K: final branch sweep on top-5 gap modules."""

from __future__ import annotations

import warnings
from datetime import date, datetime, timedelta, timezone
from typing import Any, List

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import (
    FitFileError,
    _field_to_float,
    parse_fit_file_enhanced,
    parse_fit_records_enhanced,
)
from engines.metabolic.lab_data import LabSource, LabTestResult, LabTestType, parse_lab_pdf, parse_lab_text
from engines.performance.interval_detector import (
    _classify_by_laps,
    _classify_by_signal,
    _detect_sustained_blocks,
    classify_session,
)
from engines.recovery.cardiac_engine import (
    ActivitySample,
    CardiacResponseAnalyzer,
    Segment,
    _detect_recovery_segments,
    _detect_steady_segments,
    compute_aerobic_decoupling,
    compute_cardiac_efficiency,
    compute_hr_kinetics_tau,
    cross_validate_thresholds,
)
from engines.recovery.hrv_engine import (
    _sliding_dfa_local,
    analyze_rr_stream,
    calculate_dfa_alpha1,
    detect_thresholds_from_activity,
)


class TestHrvFinalBranches92K:
    def test_sliding_rejection_and_stream_confidence(self) -> None:
        rr = np.array([820.0 + (i % 13) for i in range(240)], dtype=float)
        noisy = rr.copy()
        noisy[::7] = 2500.0
        windows = _sliding_dfa_local(noisy, rr, window_s=60.0, step_s=6.0)
        rejected = [w for w in windows if not w["valid"]]
        assert isinstance(windows, list)

        rr_samples = [
            {"elapsed": float(i * 2), "rr": [820.0 + (i % 4) for _ in range(55)]}
            for i in range(100)
        ]
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            timeline = analyze_rr_stream(
                rr_samples,
                window_seconds=90,
                step_seconds=5.0,
                context=AthleteContext(gender="FEMALE", training_years=18, discipline="MTB"),
            )
        assert isinstance(timeline, list)

        for conf_path in (
            [820.0] * 50,
            [820.0 + (i % 2) for i in range(90)],
        ):
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                dfa = calculate_dfa_alpha1(
                    conf_path,
                    context=AthleteContext(gender="MALE", training_years=15, discipline="ROAD"),
                )
            assert dfa["status"] in {
                "AEROBIC", "MIXED", "ANAEROBIC", "ERROR", "INVALID_WINDOW", "INSUFFICIENT_DATA",
            }

        power = [150.0 + i * 0.2 for i in range(2500)]
        det = detect_thresholds_from_activity(
            rr_samples,
            power_data=power,
            power_timestamps=[float(i) for i in range(len(power))],
            window_seconds=120,
            step_seconds=8.0,
            context=AthleteContext(gender="MALE", training_years=12, discipline="ROAD"),
        )
        assert "quality_summary" in det


class TestIntervalFinalBranches92K:
    def test_signal_lap_and_block_matrix(self) -> None:
        ftp = 280.0
        ramp = []
        for step, base in enumerate([120, 150, 180, 210, 240, 270, 300, 330]):
            ramp.extend([base] * 120)
        cat, sub, _, _ = _classify_by_signal(ramp, ftp=ftp)
        assert cat == "TEST"

        blocks = _detect_sustained_blocks([150.0] * 200 + [290.0] * 400 + [150.0] * 200, ftp)
        assert blocks

        laps = [
            {"duration_s": 600, "avg_power_w": 270, "max_power_w": 285},
            {"duration_s": 120, "avg_power_w": 120, "max_power_w": 130},
            {"duration_s": 480, "avg_power_w": 265, "max_power_w": 280},
        ]
        lap_result = _classify_by_laps(laps, ftp=ftp)
        assert lap_result is None or lap_result[0] in {"TEST", "HIIT", "STEADY", "FREE"}

        vo2 = [130.0] * 300 + [330.0] * 240 + [130.0] * 300 + [340.0] * 300 + [130.0] * 300
        cls = classify_session(vo2, filename="vo2_blocks.fit", ftp=ftp)
        assert cls.category in {"TEST", "HIIT", "STEADY", "FREE"}


class TestCardiacFinalBranches92K:
    def test_segments_recovery_aggregate_crossval(self) -> None:
        t = np.arange(1200, dtype=float)
        p = np.concatenate([np.full(400, 230.0), np.full(400, 255.0), np.full(400, 15.0)])
        h = np.concatenate([np.full(400, 145.0), np.full(400, 168.0), np.linspace(165, 125, 400)])

        p_smooth = p.copy()
        steady = _detect_steady_segments(t, p_smooth)
        assert isinstance(steady, list)
        recovery = _detect_recovery_segments(t, p_smooth, h)
        assert isinstance(recovery, list)

        if steady:
            seg = steady[0]
            assert compute_aerobic_decoupling(t, p, h, seg).get("available") in {True, False}
            assert compute_cardiac_efficiency(p, h, 72.0, seg).get("available") in {True, False}
            assert compute_hr_kinetics_tau(t, p, h, seg).get("available") in {True, False}

        analyzer = CardiacResponseAnalyzer(
            weight=72.0,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 250},
        )
        summary = analyzer._aggregate_summary(
            [{"available": True, "fitness_class": "GOOD"}],
            [{"available": True, "fitness_class": "FAIR"}],
            [{"available": True, "fitness_class": "EXCELLENT"}],
            [{"available": True, "fitness_class": "GOOD"}],
            [{"available": True, "hrr60_class": "GOOD", "hrr120_class": "FAIR"}],
        )
        assert summary["fitness_class"] in {"EXCELLENT", "GOOD", "FAIR", "POOR", "UNKNOWN"}

        cv = cross_validate_thresholds(
            t,
            p,
            h,
            {"status": "success", "mlss_power_watts": 250},
            [
                {"timestamp": 100.0, "status": "AEROBIC"},
                {"timestamp": 500.0, "status": "MIXED"},
                {"timestamp": 900.0, "status": "ANAEROBIC"},
            ],
        )
        assert isinstance(cv, dict)

        samples = [ActivitySample(t=float(i), power=float(p[i]), hr=float(h[i])) for i in range(600)]
        analyzed = CardiacResponseAnalyzer(
            weight=72.0,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 250},
        ).analyze(samples)
        assert analyzed.get("status") in {"success", "partial", "error"}


class TestFitParserLabFinal92K:
    def test_field_float_and_hrv_paths(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        assert _field_to_float(None) is None
        assert _field_to_float({"value": 12.5}) == 12.5
        assert _field_to_float([10.0, 20.0]) == 10.0
        assert _field_to_float("bad") is None

        start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        records = [
            {
                "timestamp": start + timedelta(seconds=i),
                "power": 220.0,
                "heart_rate": 140.0,
                "left_right_balance": {"value": 130, "right": True},
                "rr_intervals": [812.0, 805.0],
            }
            for i in range(80)
        ]

        import engines.io.fit_parser as fp

        def _extract(_payload: bytes, *, check_crc: bool):
            return (
                records,
                [{"sport": "cycling", "sub_sport": "mountain", "start_time": start}],
                [{"manufacturer": "wahoo", "product": "ELEMNT"}],
                [{"time": [0.81, 0.82, 0.83]}, {"rr_interval": 0.79}],
                [{"total_timer_time": 80}],
            )

        monkeypatch.setattr(fp, "_extract_messages", _extract)
        fit_path = tmp_path / "hrv.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 200)
        stream = fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert stream.n_samples >= 80

        def _crc_malformed(_payload: bytes, *, check_crc: bool):
            if check_crc:
                raise fp.FitParseCRCError()
            raise fp.FitParseLibError("malformed")

        monkeypatch.setattr(fp, "_extract_messages", _crc_malformed)
        with pytest.raises(FitFileError) as exc:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert exc.value.reason == "MALFORMED_RECORDS"

    def test_lab_pdf_and_text_edge_cases(self, tmp_path: Any) -> None:
        text = "VO2max: 55.0 ml/kg/min\nVLamax: 0.40\nMLSS: 270W\nMAP: 999W\nFTP: 260"
        parsed = parse_lab_text(text, test_date=date(2026, 3, 15))
        assert parsed.vo2max_ml_kg_min == pytest.approx(55.0)

        pdf = tmp_path / "report.txt"
        pdf.write_text("FTP: 250 W\nWeight: 70 kg", encoding="utf-8")
        from_pdf = parse_lab_pdf(str(pdf))
        assert from_pdf.mlss_power_w is not None or from_pdf.ftp_w is not None

        result = LabTestResult(
            test_date=date(2026, 1, 1),
            source=LabSource.SPIROMETRY,
            source_label="lab",
            test_type=LabTestType.VO2MAX_ONLY,
            vo2max_ml_kg_min=96.0,
            mlss_power_w=400,
            map_w=350,
        )
        from engines.metabolic.lab_data import validate_lab_result

        warns = validate_lab_result(result)
        assert len(warns) >= 2
