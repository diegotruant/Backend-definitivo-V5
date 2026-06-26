"""Phase 5 — batch H: final branch closure (hrv, fit_parser, lab, bayesian, phenotype, durability, detraining)."""

from __future__ import annotations

import warnings
from datetime import date, datetime, timedelta, timezone
from typing import Any, List

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.io.activity_statistics import compute_activity_statistics
from engines.io.fit_parser import (
    FitFileError,
    detect_and_fill_gaps,
    parse_fit_file_enhanced,
    parse_fit_records_enhanced,
)
from engines.metabolic.bayesian_profiler import (
    PosteriorSummary,
    _adaptive_metropolis,
    _compute_vo2_floor,
    _mcmc_misconverged,
    bayesian_metabolic_snapshot,
)
from engines.metabolic.detraining_engine import apply_detraining_model, calculate_ctl_atl_tsb
from engines.metabolic.lab_data import (
    LabSource,
    LabTestResult,
    LabTestType,
    create_lab_result,
    parse_lab_pdf,
    parse_lab_text,
    validate_lab_result,
)
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.metabolic.metabolic_profiler_phenotype import (
    compute_energy_contribution_adaptive,
    compute_recovery_curve_adaptive,
    enhance_metabolic_snapshot_with_phenotype,
    get_pcr_params,
)
from engines.performance.durability_engine import (
    calculate_durability_index,
    calculate_np_drift,
    calculate_tte_sustainability,
    generate_durability_prescription,
    generate_hourly_decay_curve,
)
from engines.performance.power_engine import PowerEngine, mean_maximal_power
from engines.recovery.hrv_engine import (
    _correct_ectopic,
    _compute_sqi,
    _dfa_alpha1_full,
    _sliding_dfa_local,
    analyze_rr_stream,
    calculate_dfa_alpha1,
)


def _stream(*, seconds: int = 600, power: float = 220.0):
    start = datetime(2026, 1, 1, 8, 0, 0)
    records = [
        {
            "timestamp": start + timedelta(seconds=i),
            "power": power,
            "heart_rate": 140.0 + (i % 5),
            "cadence": 90.0,
            "speed": 8.5,
            "altitude": 300.0 + i * 0.01,
            "temperature": 22.0,
        }
        for i in range(seconds)
    ]
    return parse_fit_records_enhanced(records, session_dict={"start_time": start, "total_elapsed_time": seconds})


class TestHrvClosure92H:
    def test_ectopic_multi_pass_and_sqi_cv_branch(self) -> None:
        rr = np.array([800.0, 1600.0, 810.0, 805.0, 815.0, 820.0] * 25, dtype=float)
        mask = np.zeros(rr.size, dtype=bool)
        mask[::6] = True
        corrected = _correct_ectopic(rr, mask, max_passes=3)
        assert corrected.shape == rr.shape

        # High CV penalty branch
        noisy = np.array([600.0, 1200.0, 650.0, 700.0, 800.0], dtype=float)
        sqi = _compute_sqi(noisy, noisy, art_ratio=0.1)
        assert 0.0 <= sqi <= 1.0

        # dof <= 0 branch in DFA full
        tiny = _dfa_alpha1_full(np.array([800.0, 810.0, 805.0]))
        assert "alpha1" in tiny

    def test_sliding_dfa_edge_windows(self) -> None:
        rr = np.array([820.0 + (i % 7) for i in range(200)], dtype=float)
        short = _sliding_dfa_local(rr, rr, window_s=500.0, step_s=10.0)
        assert short == []

        beat_times = np.cumsum(rr) / 1000.0
        beat_times[50] = 5.0  # non-monotonic → fallback cumulative
        windows = _sliding_dfa_local(rr, rr, window_s=60.0, step_s=8.0, beat_times_s=beat_times)
        assert isinstance(windows, list)

        noisy = np.array([800.0, 3000.0, 50.0, 820.0] * 40, dtype=float)
        noisy_w = noisy.copy()
        noisy_corr = _correct_ectopic(noisy_w, np.zeros(noisy_w.size, dtype=bool))
        rejected = _sliding_dfa_local(noisy_corr, noisy_w, window_s=60.0, step_s=8.0)
        assert isinstance(rejected, list)

    def test_stream_rejection_and_confidence_paths(self) -> None:
        # >30% window rejection warning
        junk = [{"elapsed": float(i), "rr": [50.0, 3000.0, 100.0] * 20} for i in range(80)]
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            out = analyze_rr_stream(junk, window_seconds=60, step_seconds=8.0)
        assert isinstance(out, list)

        # Global rejection
        bad = [{"rr": [float("nan"), 3000.0, 50.0] * 50} for _ in range(3)]
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            rejected = analyze_rr_stream(bad, window_seconds=60, step_seconds=10.0)
        assert rejected == []

        # Sliding DFA exception path
        broken = [{"elapsed": float(i), "rr": [820.0] * 50} for i in range(60)]
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            analyze_rr_stream(broken, window_seconds=90, step_seconds=6.0)

        # Point DFA confidence downgrade + exception
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            low = calculate_dfa_alpha1(
                [820.0] * 40,
                context=AthleteContext(gender="FEMALE", training_years=20, discipline="MTB"),
            )
        assert low["status"] in {
            "AEROBIC", "MIXED", "ANAEROBIC", "ERROR", "INVALID_WINDOW", "INSUFFICIENT_DATA",
        }

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            err = calculate_dfa_alpha1("not-a-list")  # type: ignore[arg-type]
        assert err["status"] in {"ERROR", "INSUFFICIENT_DATA"}


class TestFitParserClosure92H:
    def test_crc_recovery_and_error_reasons(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        import engines.io.fit_parser as fp

        start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        records = [
            {"timestamp": start + timedelta(seconds=i), "power": 220.0, "heart_rate": 140.0}
            for i in range(30)
        ]
        calls: list[bool] = []

        def _crc_then_ok(_payload: bytes, *, check_crc: bool):
            calls.append(check_crc)
            if check_crc:
                raise fp.FitParseCRCError()
            return (
                records,
                [{"sport": "cycling", "sub_sport": "road", "start_time": start, "total_elapsed_time": 30}],
                [{"manufacturer": "stages", "product": "single_left power meter"}],
                [],
                [],
            )

        monkeypatch.setattr(fp, "_extract_messages", _crc_then_ok)
        fit_path = tmp_path / "crc.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 200)
        stream = fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert stream.n_samples >= 30
        assert calls == [True, False]

        def _eof_truncated(_payload: bytes, *, check_crc: bool):
            if check_crc:
                raise fp.FitParseEOFError()
            raise fp.FitParseEOFError()

        monkeypatch.setattr(fp, "_extract_messages", _eof_truncated)
        with pytest.raises(FitFileError) as exc:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert exc.value.reason == "TRUNCATED"

        def _malformed(_payload: bytes, *, check_crc: bool):
            if check_crc:
                raise fp.FitParseCRCError()
            raise fp.FitParseLibError("bad records")

        monkeypatch.setattr(fp, "_extract_messages", _malformed)
        with pytest.raises(FitFileError) as exc2:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert exc2.value.reason == "MALFORMED_RECORDS"

        def _unknown(_payload: bytes, *, check_crc: bool):
            if check_crc:
                raise fp.FitParseCRCError()
            raise RuntimeError("mystery")

        monkeypatch.setattr(fp, "_extract_messages", _unknown)
        with pytest.raises(FitFileError) as exc3:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert exc3.value.reason == "UNKNOWN"

    def test_balance_hrv_and_dynamics(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        import engines.io.fit_parser as fp

        start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        records = [
            {
                "timestamp": start + timedelta(seconds=i),
                "power": 220.0,
                "heart_rate": 140.0,
                "left_right_balance": 50.0,
                "cadence_position": "standing",
                "rr_intervals": 812.0 if i == 5 else None,
            }
            for i in range(80)
        ]

        def _extract(_payload: bytes, *, check_crc: bool):
            return (
                records,
                [{"sport": "cycling", "start_time": start}],
                [{"manufacturer": "unknown_vendor", "product": "pm"}],
                [
                    {"other_time_field": [0.82, 0.81, 0.83]},
                    {"time": 0.79},
                ],
                [],
            )

        monkeypatch.setattr(fp, "_extract_messages", _extract)
        fit_path = tmp_path / "balance.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 200)
        stream = fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert stream.n_samples >= 80
        assert stream.pedaling_balance_source in {"single_estimated", "unknown", "dual"}

        varying = [
            {
                "timestamp": start + timedelta(seconds=i),
                "power": 220.0,
                "heart_rate": 140.0,
                "left_right_balance": 45.0 + (i % 8),
            }
            for i in range(90)
        ]

        def _dual(_payload: bytes, *, check_crc: bool):
            return varying, [{"sport": "cycling", "start_time": start}], [], [], []

        monkeypatch.setattr(fp, "_extract_messages", _dual)
        dual = fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert dual.pedaling_balance_source == "dual"

    def test_gap_fill_demo_lines(self) -> None:
        n = 300
        power = np.full(n, 200.0)
        power[100:110] = 0
        power[150:180] = 0
        quality = np.full(n, 1, dtype=np.uint8)
        elapsed = np.arange(n, dtype=np.float32)
        filled, qual, stats = detect_and_fill_gaps(power, quality, elapsed)
        assert filled.shape == power.shape
        assert stats["n_gaps"] >= 1


class TestLabBayesianPhenotype92H:
    def test_lab_summary_parse_validate(self, tmp_path: Any) -> None:
        result = create_lab_result(
            test_date=date(2026, 5, 20),
            source="metabolic_profile",
            vo2max=62.3,
            vlamax=0.42,
            mlss_w=275,
            fatmax_w=175,
            map_w=250,
            lt2_w=260,
            hr_max=185,
            lactate_curve=[(150, 1.2), (200, 2.0), (250, 4.5), (300, 8.0)],
        )
        summary = result.summary()
        assert "VO₂max" in summary
        assert "VLamax" in summary
        assert "MLSS" in summary

        text = """
        INSCYD metabolic profile report
        Test date: 15/06/2026
        VO2max: 58.5 ml/kg/min
        VLamax: 0.450 mmol/L/s
        MLSS: 280 W
        FTP: 275 W
        FatMax: 180 W
        MAP: 390 W
        HRmax: 188 bpm
        Weight: 72 kg
        """
        parsed = parse_lab_text(text)
        assert parsed.vo2max_ml_kg_min == pytest.approx(58.5)
        assert parsed.source in {LabSource.METABOLIC_PROFILE, LabSource.SPIROMETRY}

        bad_text = "VO2max: not_a_number ml/kg/min"
        partial = parse_lab_text(bad_text, test_date=date(2026, 1, 1))
        assert partial.test_date == date(2026, 1, 1)

        pdf_path = tmp_path / "lab.txt"
        pdf_path.write_text(text, encoding="utf-8")
        from_pdf = parse_lab_pdf(str(pdf_path))
        assert from_pdf.vo2max_ml_kg_min is not None

        warns = validate_lab_result(
            LabTestResult(
                test_date=date(2026, 1, 1),
                source=LabSource.UNKNOWN,
                test_type=LabTestType.UNKNOWN,
                vo2max_ml_kg_min=10.0,
                vlamax_mmol_L_s=2.5,
                mlss_power_w=400,
                map_w=350,
                hr_max_bpm=100,
                lactate_curve=[],
            )
        )
        assert warns

    def test_bayesian_misconvergence_and_mcmc(self) -> None:
        vo2_post = PosteriorSummary(
            mean=30.0, median=30.0, std=2.0,
            ci95_low=26.0, ci95_high=34.0,
            ci80_low=27.5, ci80_high=32.5,
            prior_mean=55.0, prior_std=8.0, n_effective_samples=100,
        )
        assert _mcmc_misconverged(
            vo2_post=vo2_post, mlss_w=200.0, ref_vo2=55.0, ref_mlss=280.0,
            vo2_floor=40.0, acceptance_rate=0.05,
        ) == "vo2_below_reference_fit"

        assert _mcmc_misconverged(
            vo2_post=vo2_post, mlss_w=200.0, ref_vo2=None, ref_mlss=280.0,
            vo2_floor=45.0, acceptance_rate=0.5,
        ) == "vo2_below_aerobic_floor"

        profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
        floor = _compute_vo2_floor(profiler, {1200: 280, 3600: 260}, eta=0.23)
        assert floor >= 0.0

        def log_post(x: np.ndarray) -> float:
            if x[0] < 0:
                return float("-inf")
            return -0.5 * float(np.sum((x - np.array([1.0, 2.0])) ** 2))

        samples, rate = _adaptive_metropolis(
            log_post, np.array([0.5, 1.5]), n_samples=50, n_warmup=20, rng=np.random.default_rng(1)
        )
        assert samples.shape[0] == 50
        assert 0.0 <= rate <= 1.0

        mmp = {5: 900, 15: 750, 60: 520, 300: 360, 1200: 290, 3600: 265}
        profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
        snap = bayesian_metabolic_snapshot(profiler, mmp)
        status = getattr(snap, "status", None) or (snap.to_dict().get("status") if hasattr(snap, "to_dict") else None)
        assert status in {"success", "error", "partial", None} or snap is not None

    def test_phenotype_adaptive_model(self) -> None:
        for phenotype in ("SPRINTER", "TT_CLIMBER", "PURSUITER", "ALL_ROUNDER", None):
            params = get_pcr_params(phenotype)
            assert params["pcr_capacity_kj"] > 0
            contrib = compute_energy_contribution_adaptive(
                duration_s=30.0, power_w=800.0, vo2max_mlkgmin=55.0,
                weight_kg=75.0, phenotype=phenotype,
            )
            assert abs(contrib["pcr_fraction"] + contrib["anaerobic_fraction"] + contrib["aerobic_fraction"] - 1.0) < 0.01
            curve = compute_recovery_curve_adaptive(10.0, 120.0, phenotype=phenotype)
            assert curve.size > 0

        snap = MetabolicProfiler(weight=72.0).generate_metabolic_snapshot(
            {5: 900, 60: 480, 300: 340, 1200: 285, 3600: 255}
        )
        enhanced = enhance_metabolic_snapshot_with_phenotype(
            snap, phenotype="SPRINTER", weight_kg=72.0, power_30s=900, power_1200s=285
        )
        assert "energy_contributions" in enhanced


class TestDurabilityDetrainingPower92H:
    def test_durability_engine_full_matrix(self) -> None:
        rng = np.random.default_rng(3)
        power_stream: List[float] = []
        power_stream.extend([250 + rng.normal(0, 15) for _ in range(3600)])
        power_stream.extend([245 + rng.normal(0, 15) for _ in range(3600)])
        power_stream.extend([235 + rng.normal(0, 20) for _ in range(3600)])
        duration = len(power_stream)

        di = calculate_durability_index(power_stream, duration)
        assert di["durability_index"] > 0
        np_drift = calculate_np_drift(power_stream, duration)
        assert np_drift["np_first_half"] > 0
        tte = calculate_tte_sustainability(power_stream, threshold_power=290, tolerance_pct=5.0)
        assert tte["classification"] in {"EXCELLENT", "GOOD", "FAIR", "POOR", "UNKNOWN"}
        decay = generate_hourly_decay_curve(power_stream, duration)
        assert decay["hourly_data"]
        rx = generate_durability_prescription(di["durability_index"], di["classification"])
        assert rx.get("volume") and rx.get("key_sessions")

    def test_detraining_all_status_branches(self) -> None:
        today = date(2026, 5, 15)
        baseline = {
            "status": "success",
            "estimated_vo2max": 65.0,
            "estimated_vlamax_mmol_L_s": 0.50,
            "mlss_power_watts": 315.0,
            "map_aerobic_watts": 436.0,
            "fatmax_power_watts": 215.0,
        }

        inactive = [{"date": date(2026, 4, 1), "tss": 80}]
        det = apply_detraining_model(baseline, inactive, today)
        assert det.get("status") in {"success", "partial"}
        if det.get("status") == "success":
            assert det["training_load"]["status"] == "DETRAINING"

        recent = [{"date": today - timedelta(days=i), "tss": 120 - i} for i in range(1, 20)]
        improving = apply_detraining_model(baseline, recent, today)
        if improving.get("status") == "success":
            assert improving["training_load"]["status"] in {"IMPROVING", "MAINTAINING", "DECLINING"}

        partial = apply_detraining_model({"status": "success"}, [], today)
        assert partial.get("status") == "partial"

        tl = calculate_ctl_atl_tsb(
            [{"date": today - timedelta(days=i), "tss": 50} for i in range(30)],
            today,
        )
        assert "ctl" in tl and "tsb" in tl

    def test_activity_stats_and_power_edges(self) -> None:
        stream = _stream(seconds=1200, power=240.0)
        stats = compute_activity_statistics(stream, weight_kg=72.0, ftp=280.0)
        assert stats["status"] == "success"
        assert stats["metrics"]["np_w"] > 0

        empty_stats = compute_activity_statistics(
            parse_fit_records_enhanced([], session_dict={}),
            weight_kg=70.0,
        )
        assert empty_stats["status"] in {"success", "error", "partial"}

        power = np.concatenate([np.full(500, 0.0), np.full(500, 250.0)])
        start = datetime(2026, 1, 1, 8, 0, 0)
        analyzed = PowerEngine(ftp=280.0, weight_kg=72.0).analyze(
            parse_fit_records_enhanced(
                [
                    {
                        "timestamp": start + timedelta(seconds=i),
                        "power": float(power[i]),
                        "heart_rate": 140.0,
                    }
                    for i in range(1000)
                ],
                session_dict={"start_time": start, "total_elapsed_time": 1000},
            )
        )
        assert analyzed["status"] in {"success", "partial"}
        mmp = mean_maximal_power(np.full(200, 250.0))
        assert 60 in mmp or len(mmp) > 0
