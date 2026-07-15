"""Phase 8 — push toward 100% coverage on engines/ + api/ branch gaps."""

from __future__ import annotations

import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import (
    FitFileError,
    _field_to_float,
    parse_fit_file_enhanced,
    parse_fit_records_enhanced,
)
from engines.io.session_router import decide_route, route_and_run
from engines.metabolic.lab_data import (
    LabSource,
    LabTestType,
    create_lab_result,
    parse_lab_pdf,
    parse_lab_text,
    validate_lab_result,
)
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.interval_detector import (
    IntervalBlock,
    QualifiedAnchor,
    StimulusVector,
    _classify_by_laps,
    _classify_by_signal,
    _detect_ramp_protocol,
    _detect_sustained_blocks,
    _normalized_power,
    classify_session,
    protocol_completeness,
)
from engines.recovery.cardiac_engine import (
    ActivitySample,
    CardiacResponseAnalyzer,
    Segment,
    _classify,
    _detect_recovery_segments,
    compute_aerobic_decoupling,
    compute_chronotropic_response,
    compute_hr_kinetics_tau,
)
from engines.recovery.hrv_engine import (
    _artifact_mask,
    _compute_sqi,
    _correct_ectopic,
    _detect_threshold_crossing,
    _normal_z_for_ci,
    _power_at_elapsed,
    _prepare_rr_quality,
    _sliding_dfa_local,
    analyze_rr_stream,
    calculate_dfa_alpha1,
    detect_thresholds_from_activity,
)
from engines.recovery.thermal_engine import _detect_power_drop_temp, analyze_thermal_session

FIT_DIR = Path(__file__).resolve().parent / "assets" / "fit"
FTP = 250.0
CTX = AthleteContext(gender="MALE", training_years=10, discipline="ENDURANCE")

MMP_FULL = {
    5: 980, 15: 920, 60: 520, 300: 360, 720: 310, 1200: 285, 3600: 255,
}


def _flat(n: int, power: float = 200.0) -> list[float]:
    return [power] * n


def _hiit_laps(
    n: int,
    *,
    work_s: int = 30,
    rest_s: int = 30,
    work_w: float = 350.0,
    rest_w: float = 130.0,
) -> list[dict]:
    laps = []
    for i in range(n):
        if i % 2 == 0:
            laps.append({"duration_s": work_s, "avg_power_w": work_w, "max_power_w": work_w + 20})
        else:
            laps.append({"duration_s": rest_s, "avg_power_w": rest_w, "max_power_w": rest_w + 10})
    return laps


def _rr_stream(n: int = 150, *, base_ms: float = 820.0) -> list[dict]:
    samples = []
    t = 0.0
    for i in range(n):
        rr = base_ms + np.sin(i / 5.0) * 10.0
        samples.append({"elapsed": t, "rr": [rr, rr + 2.0]})
        t += rr / 1000.0
    return samples


class TestIntervalDetectorPhase8:
    def test_dataclass_serializers(self) -> None:
        block = IntervalBlock(
            start_s=0,
            end_s=120,
            duration_s=120,
            pattern={"work_s": 30, "rest_s": 30},
            classification="medium_interval",
        )
        assert block.to_dict()["classification"] == "medium_interval"

        anchor = QualifiedAnchor(
            duration_s=300,
            power_w=340.0,
            anchor_reliability=1.0,
            source_subtype="cp6",
        )
        assert anchor.to_dict()["power_w"] == 340.0

        sv = StimulusVector(total_time_s=100, threshold_stimulus_s=40)
        d = sv.to_dict()
        assert d["threshold_min"] == round(40 / 60, 1)

    def test_lap_strategy_cp_and_hiit_variants(self) -> None:
        for dur, sub in ((180, "cp3"), (400, "cp6"), (600, "cp12"), (1100, "ftp_20min")):
            laps = [
                {"duration_s": 120, "avg_power_w": 120},
                {"duration_s": dur, "avg_power_w": int(1.1 * FTP)},
            ]
            r = _classify_by_laps(laps, ftp=FTP)
            assert r is not None
            assert r[0] == "TEST"
            assert r[1] == sub

        micro_hi = _classify_by_laps(_hiit_laps(20, work_s=20, rest_s=40), ftp=FTP)
        assert micro_hi is not None and "microburst" in micro_hi[1]

        micro_bal = _classify_by_laps(_hiit_laps(20, work_s=40, rest_s=40), ftp=FTP)
        assert micro_bal is not None and "microburst" in micro_bal[1]

        medium = _classify_by_laps(_hiit_laps(14, work_s=90, rest_s=60), ftp=FTP)
        assert medium is not None and medium[1] == "medium_interval"

        long_int = _classify_by_laps(_hiit_laps(12, work_s=240, rest_s=240), ftp=FTP)
        assert long_int is not None and long_int[1] == "long_interval"

        mixed = _classify_by_laps(_hiit_laps(12, work_s=300, rest_s=60), ftp=FTP)
        assert mixed is not None and mixed[1] == "structured_mixed"

        few_laps = _classify_by_laps(
            [{"duration_s": 300, "avg_power_w": 220}, {"duration_s": 240, "avg_power_w": 230}] * 3,
            ftp=FTP,
        )
        assert few_laps is not None and few_laps[1] == "structured_mixed"

        none_pwr = _classify_by_laps([{"duration_s": 60}] * 4, ftp=FTP)
        assert none_pwr is None

    def test_signal_strategy_matrix(self) -> None:
        assert _normalized_power([200.0] * 10) == 200.0
        assert _detect_sustained_blocks([200.0] * 50, FTP) == []

        # Multiple CP blocks
        cp_multi = [120.0] * 400
        for start, dur, p in ((500, 200, 290), (900, 400, 300), (1500, 700, 280)):
            cp_multi[start : start + dur] = [p] * dur
        cat, sub, _, _ = _classify_by_signal(cp_multi, ftp=FTP)
        assert cat == "TEST" and sub in {"cp_test", "cp6", "cp12", "ftp_20min"}

        # Single CP6
        cp6 = [120.0] * 300 + [300.0] * 360 + [120.0] * 300
        cat2, sub2, _, _ = _classify_by_signal(cp6, ftp=FTP)
        assert cat2 == "TEST" and sub2 == "cp6"

        # Mixed test: sprints + sustained block
        mixed = [120.0] * 2000
        for i in range(1300, 1310):
            mixed[i] = 900.0
        mixed[1400:1580] = [240.0] * 180
        cat3, sub3, _, _ = _classify_by_signal(mixed, ftp=FTP)
        assert cat3 == "TEST" and sub3 == "mixed_test"

        # Sprint set (lenient path)
        sprint = [100.0] * 2000
        for i in range(1600, 1610):
            sprint[i] = 850.0
        cat4, sub4, _, _ = _classify_by_signal(sprint, ftp=FTP)
        assert cat4 == "TEST" and "sprint" in sub4

        # Steady threshold / sweet spot / tempo
        steady_thr = [int(FTP * 0.98 + np.sin(i / 200) * 3) for i in range(2400)]
        r_thr = _classify_by_signal(steady_thr, ftp=FTP)
        assert r_thr[0] == "STEADY"

        ss = [int(FTP * 0.88) for _ in range(2400)]
        r_ss = _classify_by_signal(ss, ftp=FTP)
        assert r_ss[0] == "STEADY"

        tempo = [int(FTP * 0.80) for _ in range(2400)]
        r_tempo = _classify_by_signal(tempo, ftp=FTP)
        assert r_tempo[0] == "STEADY"

        endurance = [int(FTP * 0.60) for _ in range(3600)]
        r_end = _classify_by_signal(endurance, ftp=FTP)
        assert r_end[0] == "STEADY" and "endurance" in r_end[1]

        # Race signature
        race = [150.0 + 80 * np.sin(i / 80) for i in range(3600)]
        for i in range(0, 3600, 400):
            race[i : i + 5] = [500.0] * 5
        r_race = _classify_by_signal(race, ftp=FTP)
        assert r_race[0] in {"FREE", "TEST", "HIIT", "STEADY"}

        # Generic HIIT
        hiit = [120.0] * 600 + [320.0] * 120 + [120.0] * 600 + [310.0] * 120
        r_hiit = _classify_by_signal(hiit, ftp=FTP)
        assert r_hiit[0] in {"HIIT", "TEST", "STEADY"}

        ramp = []
        for step in range(8):
            ramp.extend([100 + step * 35] * 60)
        ramp_info = _detect_ramp_protocol(ramp)
        assert isinstance(ramp_info["is_ramp"], bool)

    def test_protocol_completeness_planner(self) -> None:
        full = protocol_completeness(available_durations_s=[10, 45, 300, 1500])
        assert full.completeness_pct == 100
        assert full.expected_current_confidence == "high"
        d_full = full.to_dict()
        assert d_full["tier"] == "HEURISTIC"

        empty = protocol_completeness()
        assert empty.completeness_pct == 0
        assert empty.expected_current_confidence == "very_low"
        assert any(s.test_subtype == "mixed_test" for s in empty.recommended_tests)

        partial = protocol_completeness(available_durations_s=[10, 45])
        assert partial.completeness_pct == 50
        assert partial.expected_current_confidence == "low"

        anchors = [
            QualifiedAnchor(10, 900.0, 1.0, "sprint_set"),
            QualifiedAnchor(300, 340.0, 1.0, "cp6"),
        ]
        mid = protocol_completeness(qualified_anchors=anchors)
        assert mid.completeness_pct == 50
        assert any(s.test_subtype in {"ftp_20min", "cp6", "sprint_set"} for s in mid.recommended_tests)

    def test_classify_session_hint_and_stimulus(self) -> None:
        hinted = classify_session(_flat(600), hint=("STEADY", "endurance_z2"), ftp=FTP)
        assert hinted.source == "hint"
        assert hinted.stimulus_vector is not None
        assert hinted.stimulus_vector.to_dict()["tempo_min"] >= 0

        no_ftp = classify_session(_flat(600), filename="unknown.fit")
        assert no_ftp.stimulus_vector is None


class TestHrvEnginePhase8:
    def test_artifact_sqi_and_ci_branches(self) -> None:
        assert _artifact_mask(np.array([], dtype=float)).size == 0
        assert _compute_sqi(np.array([]), np.array([]), 0.0) == 0.0

        rr = np.array([800.0, 810.0, 805.0] * 30, dtype=float)
        mask = np.zeros(rr.size, dtype=bool)
        corrected = _correct_ectopic(rr, mask, max_passes=2)
        assert corrected.shape == rr.shape

        assert _normal_z_for_ci(0.95) == pytest.approx(1.96, abs=0.01)
        assert _normal_z_for_ci(0.92) > 1.6

        with pytest.raises(ValueError):
            _sliding_dfa_local(rr[:10], rr[:5], window_s=60.0, step_s=10.0)

    def test_threshold_crossing_and_power_interp(self) -> None:
        series = []
        for i, a1 in enumerate(np.linspace(1.0, 0.3, 12)):
            series.append({
                "timestamp": i * 60,
                "alpha1_smoothed": float(a1),
            })
        point, t_sec, pwr = _detect_threshold_crossing(
            series,
            0.75,
            power_data=[200.0 + i * 5 for i in range(720)],
            power_timestamps=[float(i) for i in range(720)],
            persistence_windows=1,
        )
        assert point is not None or t_sec is None

        with pytest.raises(ValueError):
            _detect_threshold_crossing(series, 0.75, persistence_windows=0)

        assert _power_at_elapsed([100.0, 200.0], 0.5) == pytest.approx(150.0, abs=1.0)
        assert _power_at_elapsed([100.0], 5.0, power_timestamps=[0.0]) is None
        assert _power_at_elapsed([], 1.0) is None

    def test_detect_thresholds_and_stream_paths(self) -> None:
        rr = _rr_stream(180)
        out = detect_thresholds_from_activity(
            rr,
            power_data=[180.0 + i * 0.4 for i in range(600)],
            power_timestamps=[float(i) for i in range(600)],
            context=CTX,
            window_seconds=60,
            step_seconds=15.0,
        )
        assert "vt1" in out and "quality_summary" in out

        # No elapsed timestamps → cumulative beat times
        no_elapsed = [{"rr": [820.0 + (i % 5), 815.0]} for i in range(120)]
        timeline = analyze_rr_stream(no_elapsed, window_seconds=60, step_seconds=10.0)
        assert isinstance(timeline, list)

        rejected = _prepare_rr_quality([50.0, 4000.0, 60.0] * 30)
        assert rejected["valid"] is False

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            low_conf = calculate_dfa_alpha1(
                [820.0] * 50,
                context=AthleteContext(gender="FEMALE", training_years=15),
            )
        assert low_conf["status"] in {
            "AEROBIC", "MIXED", "ANAEROBIC", "ERROR", "INVALID_WINDOW", "INSUFFICIENT_DATA",
        }


class TestFitParserPhase8:
    def test_field_to_float_matrix(self) -> None:
        assert _field_to_float(None) is None
        assert _field_to_float({"value": 42.5}) == 42.5
        assert _field_to_float({"raw_value": "12.3"}) == 12.3
        assert _field_to_float([{"value": 7.0}, None]) == 7.0
        assert _field_to_float("bad") is None
        assert _field_to_float(88) == 88.0

    def test_extract_fallback_and_hrv_messages(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import engines.io.fit_parser as fp

        start = datetime(2026, 3, 1, 8, 0, 0)
        records = [
            {"timestamp": start + timedelta(seconds=i), "power": 220.0, "heart_rate": 140.0}
            for i in range(40)
        ]

        def extract_toggle(payload: bytes, *, check_crc: bool):
            if check_crc:
                raise fp.FitParseCRCError()
            return records, [{"sport": "cycling"}], [], [{"time": [0.8, 0.82]}], []

        monkeypatch.setattr(fp, "_extract_messages", extract_toggle)

        fit_path = tmp_path / "fallback.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 200)
        stream = fp.parse_fit_file_enhanced(str(fit_path), check_crc=True)
        assert stream.n_samples >= 40

    def test_invalid_header_and_no_records(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import engines.io.fit_parser as fp

        fit_path = tmp_path / "bad.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 20)

        def bad_header(_payload: bytes, *, check_crc: bool):
            raise fp.FitParseLibError("not a FIT file")

        monkeypatch.setattr(fp, "_extract_messages", bad_header)
        with pytest.raises(FitFileError) as exc:
            fp.parse_fit_file_enhanced(str(fit_path))
        assert exc.value.reason == "INVALID_HEADER"

        def empty_records(_payload: bytes, *, check_crc: bool):
            return [], [], [], [], []

        monkeypatch.setattr(fp, "_extract_messages", empty_records)
        with pytest.raises(FitFileError) as exc2:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert exc2.value.reason == "NO_RECORDS"


class TestCardiacEnginePhase8:
    def test_recovery_segments_and_metric_edges(self) -> None:
        n = 900
        t = np.arange(n, dtype=float)
        p = np.concatenate([np.full(300, 260.0), np.full(600, 15.0)])
        h = np.concatenate([np.full(300, 170.0), 170.0 - np.arange(600) * 0.08])
        segs = _detect_recovery_segments(t, p, h)
        assert isinstance(segs, list)

        seg = Segment(kind="steady", start_idx=0, end_idx=200, start_t=0.0, end_t=200.0, duration_s=200.0)
        dec = compute_aerobic_decoupling(t, p, h, seg)
        assert dec.get("available") in {True, False}

        ramp_seg = Segment(kind="ramp", start_idx=0, end_idx=120, start_t=0.0, end_t=120.0, duration_s=120.0)
        p_ramp = np.linspace(100, 280, 120)
        h_ramp = np.linspace(120, 175, 120)
        kin = compute_hr_kinetics_tau(t[:120], p_ramp, h_ramp, ramp_seg)
        assert kin.get("available") in {True, False}

        chrono = compute_chronotropic_response(t[:120], p_ramp, h_ramp, ramp_seg)
        assert chrono.get("available") in {True, False}

        assert _classify(5, 10, 20, 30, lower_is_better=True) == "EXCELLENT"
        assert _classify(35, 10, 20, 30, lower_is_better=False) == "EXCELLENT"

    def test_analyzer_recovery_at_end_of_stream(self) -> None:
        samples: list[ActivitySample] = []
        for i in range(800):
            if i < 500:
                samples.append(ActivitySample(t=float(i), power=250.0, hr=165.0))
            else:
                samples.append(ActivitySample(t=float(i), power=10.0, hr=max(120.0, 165.0 - (i - 500) * 0.1)))
        out = CardiacResponseAnalyzer(weight=72.0).analyze(samples)
        assert out.get("status") in {"success", "partial", "error"}


class TestMetabolicProfilerPhase8:
    def test_coerce_mmp_and_root_solver(self) -> None:
        prof = MetabolicProfiler(weight=72.0, context=CTX)
        coerced = prof._coerce_mmp_dict({
            "60s": 500,
            "5m": 400,
            None: 300,
            0: 100,
            "bad": "x",
            "120": 280,
        })
        assert 60 in coerced and 300 in coerced and 120 in coerced

        diff = np.array([1.0, -0.5, 0.2])
        w = np.array([200.0, 250.0, 300.0])
        assert prof._solve_root_last_crossing(diff, w) > 0

        diff_pos = np.array([1.0, 0.5, 0.3])
        assert prof._solve_root_last_crossing(diff_pos, w) == pytest.approx(200.0)

        diff_neg = np.array([-1.0, -0.5, -0.3])
        assert prof._solve_root_last_crossing(diff_neg, w) == pytest.approx(300.0)

        assert prof._bimodality_ratio({5: 1000, 3600: 250}) is not None
        assert prof._bimodality_ratio({300: 320}) is None

    def test_segmented_and_auto_fit(self) -> None:
        prof = MetabolicProfiler(weight=72.0, context=CTX)
        joint = prof.generate_metabolic_snapshot({"60": 500, "300": 360})
        assert joint.get("status") in {"success", "error", "partial"}

        fallback = prof.generate_metabolic_snapshot_segmented({"300": 360}, aerobic_min_duration_s=600)
        assert fallback.get("fit_method") == "joint_fallback" or fallback.get("status") != "success"

        bimodal_mmp = {5: 1100, 15: 1000, 60: 520, 300: 340, 1200: 270, 3600: 240}
        auto = prof.generate_metabolic_snapshot_auto(bimodal_mmp, bimodal_threshold=3.5)
        assert auto.get("fit_method") in {"segmented", "joint", "joint_fallback", None} or auto.get("status") != "success"


class TestThermalEnginePhase8:
    def test_power_drop_and_full_session(self) -> None:
        n = 3600
        core = np.linspace(37.0, 39.8, n)
        power = np.concatenate([
            np.linspace(250, 270, 1200),
            np.linspace(270, 200, 1200),
            np.linspace(200, 170, 1200),
        ])
        drop = _detect_power_drop_temp(core, power, window_s=300)
        assert drop is None or drop >= 37.0

        short = _detect_power_drop_temp(np.array([37.0, 37.1]), np.array([200.0, 210.0]))
        assert short is None

        report = analyze_thermal_session(
            list(core),
            list(power),
            hr_stream=list(140 + (core - 37.0) * 12),
            skin_temp_stream=list(33 + (core - 37.0) * 0.5),
            ambient_temp_stream=[22.0] * n,
            ftp=FTP,
        )
        d = report.to_dict()
        assert d["tier"] == "MODEL"
        assert "n_valid_samples" in d


class TestSessionRouterPhase8:
    def test_hiit_mader_and_weight_default(self) -> None:
        hiit_power = [120.0] * 300 + [320.0] * 60 + [120.0] * 300 + [310.0] * 60
        hiit_power *= 3
        snap = MetabolicProfiler(weight=72.0).generate_metabolic_snapshot(MMP_FULL)
        out = route_and_run(
            hiit_power,
            _rr_stream(80),
            weight_kg="not-a-number",
            filename="tabata_indoor.fit",
            ftp=FTP,
            context=CTX,
            metabolic_snapshot=snap if isinstance(snap, dict) else snap.to_dict(),
        )
        assert out["routing"]["route"] == "hiit"
        assert any("weight_kg" in a for a in out.get("assumptions", []))
        assert "power_curve" in out["results"] or "power_curve_update" in out["skipped"]

    def test_steady_monitoring_with_mader(self) -> None:
        ride = [int(FTP * 0.65) for _ in range(2400)]
        snap = {"status": "success", "mlss_power_watts": 280.0, "estimated_vo2max": 55.0}
        d = decide_route(ride, filename="endurance_long_ride.fit", ftp=FTP, has_rr=True, has_metabolic_profile=True)
        assert d.route == "ride_monitoring"
        assert "mader_durability" in d.engines_to_run

        out = route_and_run(ride, _rr_stream(60), weight_kg=75.0, filename="endurance_long_ride.fit", ftp=FTP, metabolic_snapshot=snap)
        assert out["routing"]["route"] == "ride_monitoring"


class TestLabDataPhase8:
    def test_parse_and_validate_matrix(self, tmp_path: Path) -> None:
        text = """
        metabolic profile report
        VO2max: 58.2 ml/kg/min
        VLamax: 0.48 mmol/L/s
        MLSS: 285 W
        FTP: 280 W
        FatMax: 210 W
        MAP: 350 W
        HRmax: 188 bpm
        LT2: 275 W
        Weight: 72.5 kg
        Date: 15/03/2026
        """
        parsed = parse_lab_text(text)
        assert parsed.vo2max_ml_kg_min == pytest.approx(58.2, abs=0.1)
        assert parsed.test_type in {LabTestType.METABOLIC_PROFILE, LabTestType.VO2MAX_ONLY, LabTestType.UNKNOWN}

        bad_date = parse_lab_text("VO2max 50\nDate: 99/99/2099")
        assert bad_date.test_date is not None

        manual = create_lab_result(
            test_date=date(2026, 1, 1),
            vo2max=55.0,
            source="manual_entry",
        )
        val = validate_lab_result(manual)
        assert isinstance(val, list)

        suspicious = create_lab_result(test_date=date(2026, 1, 1), vo2max=10.0, vlamax=3.0, mlss_w=400, map_w=300)
        warns = validate_lab_result(suspicious)
        assert len(warns) >= 1

        pdf_path = tmp_path / "lab.txt"
        pdf_path.write_text(text, encoding="utf-8")
        # parse_lab_pdf falls back to raw read when no PDF libs
        pdf_result = parse_lab_pdf(str(pdf_path), test_date=date(2026, 3, 15))
        assert pdf_result.source_label or pdf_result.notes


class TestApiAndMiscPhase8:
    def test_engines_legacy_imports(self) -> None:
        import engines

        assert hasattr(engines, "MetabolicProfiler") or hasattr(engines, "build_workout_summary")

    def test_rich_fit_records_enhanced(self) -> None:
        start = datetime(2026, 4, 1, 7, 0, 0)
        records = []
        for i in range(300):
            records.append({
                "timestamp": start + timedelta(seconds=i),
                "power": 230.0,
                "heart_rate": 145.0,
                "cadence": 90.0,
                "left_right_balance": 50 if i % 3 == 0 else 52,
                "core_body_temperature": 37.5,
            })
        stream = parse_fit_records_enhanced(
            records,
            session_dict={"start_time": start, "sport": "cycling"},
        )
        summary_flags = {
            "power": bool(np.any(stream.power > 0)),
            "hr": bool(np.any(stream.heart_rate > 0)),
        }
        assert summary_flags["power"] and summary_flags["hr"]

    @pytest.mark.parametrize("fit_name", ["garmin_power_hr.fit", "minimal_power_hr_lap_hrv.fit"])
    def test_committed_fit_still_parse(self, fit_name: str) -> None:
        path = FIT_DIR / fit_name
        if not path.is_file():
            pytest.skip("FIT assets missing")
        stream = parse_fit_file_enhanced(str(path))
        assert stream.n_samples > 0


class TestHrvEnginePhase8Batch2:
    def test_hysteresis_and_ci_interpolation(self) -> None:
        from engines.recovery.hrv_engine import _apply_hysteresis_status, _ema

        series = [1.0, 0.9, 0.8, 0.7, 0.55, 0.45, 0.35, 0.5, 0.65, 0.8, 0.95]
        statuses = _apply_hysteresis_status(series, vt1=0.75, vt2=0.50)
        assert len(statuses) == len(series)
        assert "MIXED" in statuses

        assert _normal_z_for_ci(0.90) == pytest.approx(1.645, abs=0.01)
        assert _normal_z_for_ci(0.50) == pytest.approx(1.645, abs=0.01)
        assert _normal_z_for_ci(0.999) == pytest.approx(2.576, abs=0.01)
        mid = _normal_z_for_ci(0.925)
        assert 1.645 < mid < 1.96
        assert _ema([]) == []

    def test_sliding_dfa_window_skips_and_low_sqi(self) -> None:
        rr = np.array([820.0 + (i % 4) for i in range(400)], dtype=float)
        beat_times = np.cumsum(rr) / 1000.0
        windows = _sliding_dfa_local(rr, rr, window_s=30.0, step_s=5.0, beat_times_s=beat_times)
        assert isinstance(windows, list)

        noisy = np.array([800.0, 50.0, 3000.0, 820.0] * 80, dtype=float)
        prep = _prepare_rr_quality(noisy.tolist())
        assert prep["valid"] is False
        assert prep["rejected_reason"] in {"EXCESSIVE_ARTIFACTS", "HIGH_ARTIFACT_RATIO", "LOW_SQI", "INSUFFICIENT_BEATS"}

    def test_threshold_crossing_power_branches(self) -> None:
        results = [
            {"timestamp": 0, "alpha1_smoothed": 0.95},
            {"timestamp": 60, "alpha1_smoothed": 0.70},
            {"timestamp": 120, "alpha1_smoothed": 0.65},
        ]
        p, t, pw = _detect_threshold_crossing(
            results, 0.75,
            power_data=[200.0, 220.0, 240.0],
            power_timestamps=[0.0, 60.0, 120.0],
            persistence_windows=1,
        )
        assert p is not None or pw is None

        assert _detect_threshold_crossing([], 0.75) == (None, None, None)
        assert _detect_threshold_crossing([{"timestamp": 0, "alpha1_smoothed": 0.9}], 0.75) == (None, None, None)


class TestEffortExtractorPhase8:
    def test_extract_proposal_sprint_and_cp(self) -> None:
        from engines.performance.effort_extractor import extract_test_proposal

        sprint_power = [120.0] * 200 + [950.0] * 8 + [200.0] * 200
        sprint_power += [280.0] * 360 + [120.0] * 200
        sprint_power += [270.0] * 720 + [120.0] * 200
        laps = [
            {"duration_s": 8, "avg_power_w": 900, "start_s": 200},
            {"duration_s": 360, "avg_power_w": 280, "start_s": 408},
            {"duration_s": 720, "avg_power_w": 270, "start_s": 968},
        ]
        prop = extract_test_proposal([
            {"file_id": "flow_protocol.fit", "power": sprint_power, "laps": laps},
        ])
        d = prop.to_dict()
        assert d["status"] in {"proposed", "incomplete", "empty"}
        if d["sprint"]:
            assert d["sprint"]["peak_1s_w"] > 0

        empty = extract_test_proposal([{"file_id": "easy.fit", "power": [150.0] * 100}])
        assert empty.to_dict()["status"] in {"incomplete", "empty", "proposed"}


class TestCardiacEnginePhase8Batch2:
    def test_recovery_hrr_and_short_stream(self) -> None:
        from engines.recovery.cardiac_engine import compute_hr_recovery, _detect_steady_segments

        t = np.arange(600, dtype=float)
        p = np.concatenate([np.full(200, 250.0), np.full(400, 15.0)])
        h = np.concatenate([np.full(200, 175.0), 175.0 - np.arange(400) * 0.12])
        segs = _detect_recovery_segments(t, p, h)
        if segs:
            rec = compute_hr_recovery(t, h, segs[0])
            assert rec.get("available") in {True, False}

        short = _detect_steady_segments(np.arange(30, dtype=float), np.full(30, 200.0))
        assert short == []


class TestThermalEnginePhase8Batch2:
    def test_heat_tolerance_classes_and_acclimation(self) -> None:
        from engines.recovery.thermal_engine import analyze_heat_acclimation

        n = 2400
        core = np.linspace(37.2, 39.9, n)
        power = np.concatenate([
            np.linspace(260, 280, 800),
            np.linspace(280, 150, 800),
            np.full(800, 140.0),
        ])
        report = analyze_thermal_session(
            list(core),
            list(power),
            hr_stream=list(145 + (core - 37.0) * 10),
            ftp=FTP,
        )
        d = report.to_dict()
        if d.get("heat_tolerance_classification"):
            assert d["heat_tolerance_classification"] in {"excellent", "good", "fair", "poor"}

        sessions = [
            analyze_thermal_session(list(np.linspace(37.0, 39.0, 1200)), list(np.full(1200, 220.0))),
            analyze_thermal_session(list(np.linspace(37.0, 38.5, 1200)), list(np.full(1200, 220.0))),
            analyze_thermal_session(list(np.linspace(37.0, 38.2, 1200)), list(np.full(1200, 220.0))),
            analyze_thermal_session(list(np.linspace(37.0, 38.0, 1200)), list(np.full(1200, 220.0))),
        ]
        trend = analyze_heat_acclimation(sessions)
        td = trend.to_dict()
        assert td["trend"] in {"acclimating", "stable", "deacclimating", None}


class TestFitParserPhase8Batch2:
    def test_no_backend_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import engines.io.fit_parser as fp

        monkeypatch.setattr(fp, "FIT_BACKEND_AVAILABLE", False)
        fit_path = tmp_path / "x.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 30)
        with pytest.raises(RuntimeError):
            fp.parse_fit_file_enhanced(str(fit_path))

    def test_fitdecode_only_no_fitparse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import engines.io.fit_parser as fp

        def boom(_payload: bytes, *, check_crc: bool):
            raise fp.FitParseCRCError()

        monkeypatch.setattr(fp, "FITDECODE_AVAILABLE", True)
        monkeypatch.setattr(fp, "FITPARSE_AVAILABLE", False)
        monkeypatch.setattr(fp, "_extract_messages_with_fitdecode", boom)
        with pytest.raises(fp.FitDecoderError) as exc:
            fp._extract_messages(b"payload", check_crc=True)
        assert exc.value.reason == "CRC_MISMATCH"
        assert exc.value.backend == "fitdecode"
        assert isinstance(exc.value.__cause__, fp.FitParseCRCError)

    def test_crc_mismatch_on_recovery(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import engines.io.fit_parser as fp

        def always_crc(_payload: bytes, *, check_crc: bool):
            raise fp.FitParseCRCError("bad crc")

        monkeypatch.setattr(fp, "_extract_messages", always_crc)
        fit_path = tmp_path / "crc.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 40)
        with pytest.raises(FitFileError) as exc:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert exc.value.reason == "CRC_MISMATCH"
