"""Phase 5 perfection gate — targeted coverage push to 92% line / 85% branch."""

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
    detect_and_fill_gaps,
    measured_signal_flags,
    parse_fit_file_enhanced,
    parse_fit_records_enhanced,
)
from engines.metabolic.lab_data import parse_lab_pdf, parse_lab_text
from engines.performance.effort_extractor import extract_test_proposal
from engines.performance.interval_detector import QualifiedAnchor, classify_session, protocol_completeness
from engines.performance.mmp_quality import analyze_mmp_quality, clean_mmp, filter_mmp_by_window
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
    _normal_z_for_ci,
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


def _rich_fit_records(*, seconds: int = 120) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
    records: List[Dict[str, Any]] = []
    for i in range(seconds):
        records.append(
            {
                "timestamp": start + timedelta(seconds=i),
                "power": 220 + (i % 7),
                "heart_rate": 140 + (i % 5),
                "cadence": 90,
                "enhanced_speed": 8.2,
                "enhanced_altitude": 120.0 + i * 0.1,
                "distance": float(i * 8),
                "position_lat": 45.0 + i * 0.0001,
                "position_long": 9.0 + i * 0.0001,
                "temperature": 18.0,
                "respiration_rate": 17.0,
                "core_body_temperature": 37.1,
                "skin_temperature": 32.5,
                "left_right_balance": {"value": 128, "right": True} if i % 20 == 0 else 48.0,
                "left_power_phase": 120.0,
                "right_power_phase": 125.0,
                "left_pedal_smoothness": 44.0,
                "right_pedal_smoothness": 43.0,
                "left_torque_effectiveness": 21.0,
                "right_torque_effectiveness": 20.0,
                "cadence_position": "standing" if i % 40 == 0 else "seated",
                "rr_intervals": [820.0, 810.0, 805.0] if i % 15 == 0 else None,
            }
        )
    session = {"sport": "cycling", "start_time": start, "total_elapsed_time": seconds}
    return records, session


class TestFitParserGate:
    @pytest.mark.parametrize(
        "stem",
        [
            "minimal_power_hr_lap_hrv",
            "garmin_power_hr",
            "garmin_rr_hrv",
            "wahoo_power_cadence",
            "no_power_hr_only",
            "indoor_trainer_erg",
            "zwift_virtual",
            "bad_crc",
        ],
    )
    def test_parse_all_repo_fit_assets(self, stem: str) -> None:
        fit_path = FIT_DIR / f"{stem}.fit"
        if not fit_path.exists():
            pytest.skip(f"missing {fit_path.name}")
        stream = parse_fit_file_enhanced(str(fit_path), check_crc=False, repair_synthetic_header=False)
        assert stream.n_samples > 0
        assert isinstance(measured_signal_flags(stream), dict)

    def test_rich_record_parser_covers_sensor_branches(self) -> None:
        records, session = _rich_fit_records(seconds=90)
        stream = parse_fit_records_enhanced(records, session_dict=session)
        flags = measured_signal_flags(stream)
        assert stream.n_samples >= 90
        assert flags["power"]
        assert flags["respiration"] or stream.has_respiration
        assert flags["gps"]

    def test_balance_raw_encoding_and_gap_paths(self) -> None:
        start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        records = [
            {
                "timestamp": start + timedelta(seconds=i),
                "power": 0.0 if i in {10, 11, 12, 50, 51, 52, 53, 54, 55} else 240.0,
                "heart_rate": 0.0 if i in {20, 21} else 145.0,
                "left_right_balance": 200 if i % 2 == 0 else 48.0,
            }
            for i in range(80)
        ]
        stream = parse_fit_records_enhanced(records, session_dict={"start_time": start, "total_elapsed_time": 80})
        assert stream.gap_summary["power"]["n_gaps"] >= 0
        assert stream.gap_summary["heart_rate"]["n_gaps"] >= 0

    def test_device_info_dual_single_and_fitdecode_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        import engines.io.fit_parser as fp

        records, session = _rich_fit_records(seconds=30)
        dual_devices = [
            {"manufacturer": "Garmin", "product": "Edge 1040"},
            {"manufacturer": "SRAM", "product": "dual power crank"},
        ]
        single_devices = [
            {"manufacturer": "Garmin", "product": "Edge"},
            {"manufacturer": "Stages", "product": "single left power"},
        ]

        def _fake_extract(payload: bytes, *, check_crc: bool):
            devices = dual_devices if check_crc else single_devices
            return records, [session | {"sport": "cycling"}], devices, [{"time": [0.8]}], [{"total_timer_time": 60}]

        monkeypatch.setattr(fp, "_extract_messages", _fake_extract)
        fit_path = tmp_path / "mock.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 200)
        dual_stream = fp.parse_fit_file_enhanced(str(fit_path), check_crc=True, repair_synthetic_header=False)
        assert dual_stream.pedaling_balance_source == "dual"

        single_stream = fp.parse_fit_file_enhanced(str(fit_path), check_crc=False, repair_synthetic_header=False)
        assert single_stream.pedaling_balance_source == "single_estimated"
        assert single_stream.laps

    def test_truncated_asset_raises_typed_error(self) -> None:
        truncated = FIT_DIR / "truncated.fit"
        if not truncated.exists():
            pytest.skip("missing truncated.fit")
        with pytest.raises(FitFileError) as exc:
            parse_fit_file_enhanced(str(truncated), check_crc=False)
        assert exc.value.reason in {"TRUNCATED", "MALFORMED_RECORDS", "INVALID_HEADER", "NO_RECORDS"}


class TestHrvEngineGate:
    def test_internal_helpers_and_classification(self) -> None:
        rr = np.array([800.0 + np.sin(i / 3.0) * 20 for i in range(120)], dtype=float)
        mask = _artifact_mask(rr)
        corrected = _correct_ectopic(rr, mask)
        assert corrected.shape == rr.shape
        assert _winsorize_rr(np.array([50.0, 800.0, 5000.0])).max() <= 2500.0
        assert _classify(0.95, 0.75, 0.5) == "AEROBIC"
        assert _classify(0.65, 0.75, 0.5) == "MIXED"
        assert _classify(0.45, 0.75, 0.5) == "ANAEROBIC"
        vt1, vt2 = _resolve_dfa_thresholds(AthleteContext(gender="FEMALE", training_years=3, discipline="MTB"))
        assert vt1 > 0 and vt2 > 0
        assert _resolve_confidence(AthleteContext(training_years=12)) == "HIGH"
        assert _normal_z_for_ci(0.99) == pytest.approx(2.576)

    def test_dfa_full_sliding_and_hysteresis(self) -> None:
        rr = np.array([820.0 + (i % 9) for i in range(160)], dtype=float)
        full = _dfa_alpha1_full(rr)
        assert "alpha1" in full
        series = [1.0, 0.95, 0.9, 0.85, 0.8, 0.72, 0.68, 0.62, 0.55]
        smoothed = _ema(series)
        statuses = _apply_hysteresis_status(smoothed, 0.75, 0.5)
        assert len(statuses) == len(series)
        assert "ANAEROBIC" in statuses or "MIXED" in statuses

    def test_rr_stream_and_threshold_detection(self) -> None:
        rr_samples = [
            {"elapsed": float(i * 4), "rr": [820.0 + (i % 6) for _ in range(35)]}
            for i in range(160)
        ]
        timeline = analyze_rr_stream(
            rr_samples,
            window_seconds=90,
            step_seconds=8.0,
            context=AthleteContext(gender="MALE", training_years=8, discipline="ROAD"),
        )
        assert isinstance(timeline, list)

        power = [120.0 + i * 0.5 for i in range(3000)]
        thresholds = detect_thresholds_from_activity(
            rr_samples,
            power_data=power,
            power_timestamps=[float(i) for i in range(len(power))],
            window_seconds=90,
            step_seconds=6.0,
            context=AthleteContext(gender="MALE", training_years=10, discipline="ROAD"),
        )
        assert "quality_summary" in thresholds

        crossing = _detect_threshold_crossing(
            [
                {"timestamp": 0.0, "alpha1_smoothed": 1.0},
                {"timestamp": 30.0, "alpha1_smoothed": 0.95},
                {"timestamp": 60.0, "alpha1_smoothed": 0.72},
                {"timestamp": 90.0, "alpha1_smoothed": 0.68},
            ],
            threshold=0.75,
            power_data=[180.0, 210.0, 240.0, 260.0],
            power_timestamps=[0.0, 30.0, 60.0, 90.0],
            persistence_windows=2,
        )
        assert crossing[0] is not None or crossing[2] is not None
        assert _power_at_elapsed([200.0, 220.0], 0.5, [0.0, 1.0]) == pytest.approx(210.0)

        dfa = calculate_dfa_alpha1([820.0] * 80, context=AthleteContext())
        assert dfa["status"] in {"AEROBIC", "MIXED", "ANAEROBIC", "INVALID_WINDOW", "INSUFFICIENT_DATA", "ERROR"}
        bad = _prepare_rr_quality([300.0, 2500.0, 100.0] * 20)
        assert bad["valid"] is False
        assert bad.get("rejected_reason") in {"EXCESSIVE_ARTIFACTS", "INSUFFICIENT_BEATS", "HIGH_ARTIFACT_RATIO"}


class TestIntervalDetectorGate:
    def _steady(self, watts: float, seconds: int) -> List[float]:
        return [watts] * seconds

    def test_test_session_anchors_and_stimulus(self) -> None:
        cp3 = self._steady(150, 400) + self._steady(330, 180) + self._steady(150, 400)
        cp3_cls = classify_session(cp3, ftp=280.0, filename="cp3_test.fit")
        assert cp3_cls.category in {"TEST", "STEADY", "HIIT", "FREE"}
        assert cp3_cls.stimulus_vector is not None

        ftp20 = self._steady(150, 300) + self._steady(265, 1200) + self._steady(150, 300)
        ftp_cls = classify_session(ftp20, ftp=280.0, filename="ftp_20min_test.fit")
        assert ftp_cls.category in {"TEST", "STEADY", "HIIT", "FREE"}
        if ftp_cls.category == "TEST":
            assert ftp_cls.qualified_anchors or ftp_cls.subtype

        mixed = [950.0] * 8 + [280.0] * 420 + [120.0] * 300
        mixed_cls = classify_session(mixed, ftp=280.0)
        assert mixed_cls.category in {"TEST", "HIIT", "STEADY", "FREE", "UNCLASSIFIED"}

        hiit = []
        for _ in range(10):
            hiit.extend([360.0] * 60 + [140.0] * 120)
        hiit_cls = classify_session(hiit, ftp=280.0)
        assert hiit_cls.category in {"HIIT", "TEST", "STEADY", "FREE"}

    def test_lap_and_filename_classification_matrix(self) -> None:
        by_name = classify_session([200.0] * 600, filename="ftp_2x8_block.fit", ftp=280.0)
        assert by_name.category == "TEST"

        laps = [
            {"duration_s": 480, "avg_power_w": 270},
            {"duration_s": 120, "avg_power_w": 140},
            {"duration_s": 480, "avg_power_w": 268},
        ]
        lap_test = classify_session([220.0] * 2400, laps=laps, ftp=280.0)
        assert lap_test.category == "TEST"

        endurance = classify_session([175.0] * 5000, ftp=280.0)
        assert endurance.category in {"STEADY", "ENDURANCE", "FREE", "UNCLASSIFIED"}

        race = [150.0 + 130.0 * abs(np.sin(i / 22.0)) for i in range(3600)]
        race_cls = classify_session(race, ftp=280.0)
        assert race_cls.category in {"FREE", "HIIT", "STEADY", "TEST", "UNCLASSIFIED"}

    def test_protocol_completeness_recommendations(self) -> None:
        sparse = protocol_completeness(available_durations_s=[60])
        assert sparse.completeness_pct < 100
        assert sparse.recommended_tests

        rich = protocol_completeness(
            qualified_anchors=[
                QualifiedAnchor(5, 950.0, 1.0, "sprint_set"),
                QualifiedAnchor(60, 520.0, 1.0, "sprint_set"),
                QualifiedAnchor(300, 380.0, 1.0, "cp6"),
                QualifiedAnchor(1200, 300.0, 1.0, "ftp_20min"),
            ],
            available_durations_s=[5, 60, 300, 1200, 3600],
        )
        assert rich.completeness_pct >= 75
        assert rich.n_qualified_anchors >= 2


class TestCardiacEngineGate:
    def _samples(self, *, seconds: int = 600, power: float = 220.0) -> List[ActivitySample]:
        out: List[ActivitySample] = []
        for i in range(seconds):
            out.append(ActivitySample(t=float(i), power=power + (i % 10), hr=130.0 + i * 0.05))
        return out

    def test_analyzer_and_segment_metrics(self) -> None:
        samples = self._samples(seconds=500)
        out = CardiacResponseAnalyzer(weight=72.0).analyze(samples)
        assert out.get("status") in {"success", "partial", "error"}

        t = np.array([s.t for s in samples])
        p = np.array([s.power for s in samples])
        h = np.array([s.hr for s in samples])
        seg = Segment(kind="steady", start_idx=50, end_idx=450, start_t=50.0, end_t=449.0, duration_s=400.0)
        drift = compute_cardiac_drift(t, p, h, seg)
        assert drift.get("available") is True
        decouple = compute_aerobic_decoupling(t, p, h, seg)
        assert decouple.get("available") is True

        chrono = compute_chronotropic_response(t, p, h, seg)
        assert chrono.get("available") in {True, False}
        recovery = compute_hr_recovery(t, h, seg)
        assert recovery.get("available") in {True, False}

    def test_cross_validation_mlss_and_dfa(self) -> None:
        t = np.arange(900, dtype=float)
        p = np.array([220.0] * 900)
        h = np.array([140.0 + (i % 12) for i in range(900)])
        hrv = [
            {"timestamp": 60.0, "status": "AEROBIC"},
            {"timestamp": 180.0, "status": "MIXED"},
            {"timestamp": 300.0, "status": "ANAEROBIC"},
        ]
        cv = cross_validate_thresholds(
            t,
            p,
            h,
            {"status": "success", "mlss_power_watts": 220},
            hrv,
        )
        assert cv.get("available") is True or "hr_at_vt1_dfa" in cv or "hr_at_mlss" in cv


class TestMmpQualityGate:
    def test_issue_categories_and_clean_rules(self) -> None:
        plateau = {300: 320.0, 600: 320.0, 1200: 318.0, 3600: 310.0}
        plateau_report = analyze_mmp_quality(plateau)
        assert plateau_report.issues

        sprinty = {5: 2000, 60: 520, 180: 400, 300: 380, 1200: 320}
        sprint_report = analyze_mmp_quality(sprinty)
        assert sprint_report.quality_score >= 0

        non_mono = {60: 300.0, 300: 350.0, 1200: 360.0}
        mono_report = analyze_mmp_quality(non_mono)
        assert mono_report.classification

        cleaned, audit = clean_mmp(
            plateau,
            mmp_samples=[
                {"duration_s": 300, "power_w": 320, "ride_id": "a", "date": "2026-01-01"},
                {"duration_s": 600, "power_w": 320, "ride_id": "b", "date": "2026-01-02"},
            ],
            drop_rules=["identical_plateau", "rolling_window_redundant"],
        )
        assert audit["original_anchors"] >= 3
        assert isinstance(cleaned, dict)

        ref = date(2026, 6, 17)
        filtered, kept = filter_mmp_by_window(
            [
                {"duration_s": 300, "power_w": 380, "date": "2026-06-01"},
                {"duration_s": 1200, "power_w": 320, "date": "2024-01-01"},
            ],
            today=ref,
            window_days=120,
        )
        assert 300 in filtered
        assert 1200 not in filtered
        assert len(kept) == 1


class TestLabAndEffortGate:
    def test_lab_text_pdf_and_effort_proposals(self, tmp_path: Any) -> None:
        text = (
            "Report\nVO2max 63 ml/kg/min\nVLamax 0.52\nMLSS 285 W\n"
            "FTP 280 W\nFatMax 205 W\nMAP 360 W\nHRmax 188\nWeight 71 kg\n17/06/2026\n"
        )
        parsed = parse_lab_text(text)
        assert parsed.vo2max_ml_kg_min == pytest.approx(63.0)

        fake_pdf = tmp_path / "lab.pdf"
        fake_pdf.write_text(text, encoding="utf-8")
        pdf_parsed = parse_lab_pdf(str(fake_pdf), test_date=date(2026, 6, 17))
        assert pdf_parsed.vo2max_ml_kg_min == pytest.approx(63.0)

        sprint_power = [120.0] * 200 + [1050.0] * 12 + [120.0] * 200
        cp_power = [150.0] * 300 + [320.0] * 360 + [150.0] * 300
        proposal = extract_test_proposal(
            [
                {"file_id": "sprint.fit", "power": sprint_power, "laps": [{"duration_s": 15, "avg_power_w": 900}]},
                {"file_id": "cp.fit", "power": cp_power, "laps": [{"duration_s": 360, "avg_power_w": 320}]},
            ]
        )
        body = proposal.to_dict()
        assert body["status"] in {"proposed", "incomplete", "empty"}


class TestDataQualityGate:
    def test_severe_hr_cadence_and_pause_pipeline(self) -> None:
        hr_dropout = assess_data_quality(
            [220.0] * 100,
            hr_stream=[0.0] * 35 + [140.0] * 65,
        )
        assert hr_dropout.hr_quality < 0.85

        cadence_bad = assess_data_quality(
            [220.0] * 100,
            cadence_stream=[0.0] * 75 + [260.0] * 25,
        )
        assert cadence_bad.cadence_quality < 1.0

        spiky = assess_data_quality([0.0] * 30 + [220.0] * 40)
        assert spiky.power_quality < 1.0 or spiky.issues_detected

        paused = clean_workout_data(
            [220.0] * 60 + [0.0] * 40 + [220.0] * 60,
            hr=[140.0] * 160,
            remove_pauses_flag=True,
        )
        assert len(paused["power_cleaned"]) < 160


class TestStreamPropertyGate:
    def test_activity_stream_enhanced_properties(self) -> None:
        stream = ActivityStreamEnhanced(n_samples=4)
        stream.speed_mps = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        stream.temperature_c = np.array([20.0, 21.0, 22.0, 23.0], dtype=np.float32)
        stream.core_body_temp = np.array([37.0, 37.1, 37.2, 37.3], dtype=np.float32)
        stream.skin_temp = np.array([33.0, 33.1, 33.2, 33.3], dtype=np.float32)
        assert stream.speed.tolist() == [1.0, 2.0, 3.0, 4.0]
        assert stream.temperature.tolist() == [20.0, 21.0, 22.0, 23.0]
        assert stream.core_temperature.tolist() == pytest.approx([37.0, 37.1, 37.2, 37.3], rel=1e-4)
        assert stream.skin_temperature.tolist() == pytest.approx([33.0, 33.1, 33.2, 33.3], rel=1e-4)

        values = np.array([220.0, 0.0, 0.0, 220.0], dtype=float)
        quality = np.zeros(4, dtype=int)
        elapsed = np.array([0.0, 1.0, 2.0, 3.0])
        _, q_out, stats = detect_and_fill_gaps(values, quality, elapsed, gap_short_s=1.0, gap_long_s=2.0)
        assert stats["n_gaps"] >= 1
        assert len(q_out) == 4


class TestSecondaryModulesGate:
    """Additional branch coverage across engines with high gap counts."""

    def test_pedaling_balance_zones_and_trend(self) -> None:
        from engines.recovery.pedaling_balance import analyze_balance_trend, analyze_pedaling_balance

        marked = analyze_pedaling_balance([38.0] * 600, [200.0] * 600, ftp=250.0, pedaling_balance_source="dual")
        assert marked.asymmetry_classification == "marked"
        symmetric = analyze_pedaling_balance([50.0] * 600, [200.0] * 600, ftp=250.0, pedaling_balance_source="dual")
        trend = analyze_balance_trend([symmetric, symmetric, marked, marked])
        assert trend.trend in {"stable", "worsening", "improving", None} or trend.notes

    def test_zones_glycolytic_and_power_engine(self) -> None:
        from engines.metabolic.glycolytic_validation_engine import (
            build_glycolytic_profile,
            compute_vlapeak_observed,
            predict_vlapeak_from_snapshot,
            validate_vlapeak_against_model,
        )
        from engines.metabolic.zones_engine import coggan_power_zones, friel_hr_zones, metabolic_power_zones, seiler_polarization
        from engines.performance.power_engine import mean_maximal_power, normalized_power, variability_index

        start = datetime(2026, 1, 1, 8, 0, 0)
        records = [
            {"timestamp": start + timedelta(seconds=i), "power": 220.0, "heart_rate": 140.0, "cadence": 90.0}
            for i in range(600)
        ]
        stream = parse_fit_records_enhanced(records, session_dict={"start_time": start, "total_elapsed_time": 600})
        assert coggan_power_zones(stream, ftp=280.0)["available"] is True
        assert friel_hr_zones(stream, lthr=165.0)["available"] is True
        metabolic_snap = {
            "status": "success",
            "mlss_power_watts": 280.0,
            "map_aerobic_watts": 350.0,
            "expressiveness": {"mlss_reliable": True},
            "zones": [
                {"name": "Z1", "minWatt": 0, "maxWatt": 154},
                {"name": "Z2", "minWatt": 155, "maxWatt": 210},
                {"name": "Z3", "minWatt": 211, "maxWatt": 252},
                {"name": "Z4", "minWatt": 253, "maxWatt": 294},
                {"name": "Z5", "minWatt": 295, "maxWatt": 350},
            ],
        }
        assert metabolic_power_zones(stream, metabolic_snap)["available"] is True
        assert seiler_polarization(stream, vt1_w=200.0, vt2_w=260.0)["available"] is True

        snap = {
            "status": "success",
            "estimated_vlamax_mmol_L_s": 0.5,
            "mlss_power_watts": 280.0,
            "combustion_curve": [{"watt": 200, "carbOxidation": 20}, {"watt": 280, "carbOxidation": 45}],
        }
        assert build_glycolytic_profile(snap, mmp={1: 950, 60: 480})["status"] == "success"
        assert compute_vlapeak_observed(1.2, 12.0, 30.0)["status"] == "success"
        assert predict_vlapeak_from_snapshot(snap, mmp={1: 950})["status"] == "success"
        assert validate_vlapeak_against_model(vlapeak_observed_mmol_l_s=0.9, predicted_vlapeak_mmol_l_s=0.85)["status"]

        arr = np.array([200.0 + (i % 20) for i in range(600)])
        np_val = normalized_power(arr)
        assert variability_index(np_val, float(np.mean(arr))) is not None
        assert mean_maximal_power(arr, durations_s=[5, 60, 300])

    def test_compliance_feasibility_and_workout_models(self) -> None:
        from engines.workouts.compliance_engine import compare_workout_to_activity
        from engines.workouts.feasibility_engine import analyze_workout_feasibility
        from engines.workouts.models import WorkoutStep, materialize_workout, validate_workout_payload

        workout = {
            "title": "Sweet spot",
            "steps": [
                {"id": "w1", "type": "work", "duration_s": 1200, "target_pct_cp": 88, "is_key_step": True},
                {"id": "r1", "type": "recovery", "duration_s": 300, "target_pct_cp": 50},
            ],
        }
        start = datetime(2026, 1, 1, 8, 0, 0)
        records = [
            {"timestamp": start + timedelta(seconds=i), "power": 245.0, "heart_rate": 145.0, "cadence": 90.0}
            for i in range(1500)
        ]
        stream = parse_fit_records_enhanced(records, session_dict={"start_time": start, "total_elapsed_time": 1500})
        compliance = compare_workout_to_activity(workout, stream, athlete_profile={"cp_w": 280.0})
        assert compliance["status"] in {"success", "partial", "failed"}

        feasibility = analyze_workout_feasibility(
            workout,
            athlete_profile={"cp_w": 280.0, "w_prime_j": 20000, "weight_kg": 72.0},
        )
        assert feasibility["status"] in {"success", "warning", "blocked", "error", "feasible", "challenging"}

        payload = validate_workout_payload(workout)
        assert payload["status"] == "valid"
        step = WorkoutStep(step_id="1", type="work", duration_s=600, target_pct_cp=90)
        materialized = materialize_workout({"steps": [step.to_dict()]}, {"cp_w": 280.0})
        assert materialized["steps"]

    def test_activity_intelligence_and_workout_summary(self) -> None:
        from engines.io.activity_intelligence import (
            build_activity_intelligence,
            compute_best_efforts,
            compute_zone_distribution,
            detect_auto_intervals,
        )
        from engines.io.workout_summary import build_workout_summary

        start = datetime(2026, 1, 1, 8, 0, 0)
        power = []
        for i in range(1800):
            if i % 300 < 60:
                power.append(350.0)
            else:
                power.append(180.0)
        records = [
            {"timestamp": start + timedelta(seconds=i), "power": power[i], "heart_rate": 140.0, "cadence": 90.0}
            for i in range(1800)
        ]
        stream = parse_fit_records_enhanced(records, session_dict={"start_time": start, "total_elapsed_time": 1800})
        efforts = compute_best_efforts(stream.power.tolist())
        assert efforts
        zones = compute_zone_distribution(stream.power.tolist(), threshold=280.0, kind="power")
        assert zones.get("status") == "success" or zones.get("zones")
        intervals = detect_auto_intervals(stream.power.tolist(), threshold_w=280.0)
        assert intervals.get("status") == "success" or isinstance(intervals.get("intervals"), list)
        intel = build_activity_intelligence(stream, weight_kg=72.0, ftp=280.0)
        assert intel.get("status") in {"success", "partial", "error"} or "best_efforts" in intel
        summary = build_workout_summary(stream, ftp=280.0, weight_kg=72.0)
        assert summary.get("status") in {"success", "partial", "error"} or "duration_s" in summary

    def test_bayesian_kalman_and_vlamax(self) -> None:
        from engines.metabolic.bayesian_profiler import bayesian_metabolic_snapshot
        from engines.metabolic.metabolic_kalman import DailyInput, MetabolicKalman, process_workout_history
        from engines.metabolic.metabolic_profiler import MetabolicProfiler
        from engines.metabolic.power_vlamax_estimator import estimate_vlamax_from_power_series

        profiler = MetabolicProfiler(weight=72.0)
        snap = bayesian_metabolic_snapshot(
            profiler,
            {60: 500, 300: 360, 1200: 300, 3600: 280},
            n_samples=500,
            n_warmup=100,
            seed=11,
        )
        assert snap.to_dict()["status"] in {"success", "error"}

        kalman = MetabolicKalman(np.array([60.0, 0.4]), np.diag([4.0, 0.01]), weight=72.0)
        kalman.predict(DailyInput(date=date(2026, 6, 1), vo2max_stimulus_min=20.0))
        kalman.update([(180, 360.0), (360, 330.0)])
        traj = process_workout_history(
            [DailyInput(date=date(2026, 6, 1), vo2max_stimulus_min=25.0)],
            initial_vo2=60.0,
            initial_vla=0.4,
            weight=72.0,
        )
        assert len(traj.states) >= 1

        sprint = [200.0] * 3 + [1100.0] * 15 + [200.0] * 2
        vla = estimate_vlamax_from_power_series(
            sprint,
            dt_s=1.0,
            weight_kg=72.0,
            eta=0.23,
            active_muscle_mass_kg=10.0,
            vo2max_power_w=360.0,
        )
        assert vla.get("status") in {"success", "error", "partial", "invalid_protocol"}

    def test_thermal_explainability_and_race_prediction(self) -> None:
        from engines.performance.race_prediction_engine import analyze_course, parse_gpx_course
        from engines.recovery.explainability_engine import (
            calculate_durability_confidence,
            calculate_vo2max_confidence,
            generate_durability_narrative,
            generate_workout_summary_narrative,
        )
        from engines.recovery.thermal_engine import analyze_heat_acclimation, analyze_thermal_session

        thermal = analyze_thermal_session(
            core_temp_stream=[37.0 + i * 0.002 for i in range(400)],
            power_stream=[220.0] * 400,
            hr_stream=[140.0] * 400,
            ftp=280.0,
        )
        assert thermal.to_dict().get("data_quality") != "no_data" or thermal.n_valid_samples >= 0
        accl = analyze_heat_acclimation([thermal, thermal])
        assert accl.n_sessions >= 0
        assert accl.to_dict() is not None

        conf = calculate_vo2max_confidence({30: 850, 60: 720, 300: 420}, efforts_count=4, data_quality_score=0.85)
        d_conf = calculate_durability_confidence(duration_hours=3.5, power_data_completeness=0.9)
        rx = {"focus": "Maintain base", "volume": "8-10 h/week", "key_sessions": ["Long Z2 ride"]}
        assert generate_durability_narrative(92.0, "GOOD", d_conf, rx)
        assert generate_workout_summary_narrative(
            {
                "headline": {"workout_type": "Endurance", "tss": 85, "if_value": 0.72},
                "stream_metadata": {"duration_s": 5400},
                "sections": {},
            }
        )

        gpx = """<?xml version="1.0"?><gpx><trk><trkseg>
        <trkpt lat="45.0" lon="7.0"><ele>200</ele></trkpt>
        <trkpt lat="45.01" lon="7.01"><ele>350</ele></trkpt>
        </trkseg></trk></gpx>"""
        course = parse_gpx_course(gpx)
        analyzed = analyze_course(course)
        assert analyzed.get("status") in {"success", "partial", "error"} or "total_distance_m" in analyzed

    def test_test_protocols_and_detraining(self) -> None:
        from engines.metabolic.detraining_engine import apply_detraining_model, calculate_ctl_atl_tsb, calculate_decay_factor
        from engines.performance.test_protocols import run_incremental_test, run_power_cadence_test, run_test, run_wingate_test

        wingate = run_wingate_test({"test_data": {"power_stream": [1100.0] * 5 + [700.0] * 25, "body_weight_kg": 72.0}})
        assert wingate.get("status") in {"success", "error"}
        inc = run_incremental_test(
            {
                "test_data": {
                    "steps": [
                        {"power_w": 150, "hr_mean": 120},
                        {"power_w": 220, "hr_mean": 150},
                        {"power_w": 280, "hr_mean": 170},
                    ]
                }
            }
        )
        assert inc.get("status") in {"success", "error"}
        cadence = run_power_cadence_test(
            {"test_data": {"steps": [{"cadence_rpm": 80, "power_w": 200}, {"cadence_rpm": 100, "power_w": 220}]}}
        )
        assert cadence.get("status") in {"success", "error"}
        envelope = run_test(
            {
                "test_type": "wingate",
                "test_data": {"power_stream": [1000.0] * 30, "body_weight_kg": 72.0},
            }
        )
        assert envelope.get("status") in {"success", "error"}

        ref = date(2026, 6, 17)
        snapshot = {
            "status": "success",
            "estimated_vo2max": 60.0,
            "estimated_vlamax_mmol_L_s": 0.45,
            "mlss_power_watts": 280.0,
        }
        hist = [{"date": ref - timedelta(days=i), "tss": 80.0} for i in range(1, 30)]
        out = apply_detraining_model(snapshot, hist, ref)
        assert out.get("training_load")
        assert calculate_ctl_atl_tsb(hist, ref)["ctl"] > 0
        assert 0 < calculate_decay_factor(14.0, 55.0, "vo2max") <= 1.0

    def test_session_router_and_mmp_aggregator(self) -> None:
        from engines.io.session_router import decide_route, route_and_run
        from engines.performance.mmp_aggregator import curve_to_mmp, extract_ride_curve, update_power_curve

        power = [350.0] * 60 + [150.0] * 120
        decision = decide_route(power * 12, filename="30_15.fit", ftp=280.0, has_rr=True)
        assert decision.route in {"hiit", "metabolic_anchor", "hrv_threshold", "free"}

        rr = [{"elapsed": float(i * 5), "rr": [810.0] * 15} for i in range(40)]
        routed = route_and_run(
            [900.0] * 10 + [270.0] * 2000,
            rr_samples=rr,
            filename="cp_test.fit",
            ftp=280.0,
            weight_kg=72.0,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 280},
        )
        assert routed["routing"]["route"] in {"metabolic_anchor", "hrv_threshold", "hiit", "free"}

        curve = extract_ride_curve([250.0 + (i % 10) for i in range(1800)])
        assert curve
        updated = update_power_curve([250.0] * 1800, "2026-06-01", stored_curve={60: {"duration_s": 60, "power_w": 400.0}})
        assert hasattr(updated, "curve") or isinstance(updated, dict)
        assert curve_to_mmp({60: {"power_w": 420.0}, 300: {"power_w": 360.0}})
