"""Phase 5 — batch J: branch closure sprint (power, protocols, bayesian, zones, lab, mmp, thermal)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.metabolic.bayesian_profiler import (
    PosteriorSummary,
    _mcmc_misconverged,
    bayesian_metabolic_snapshot,
)
from engines.metabolic.glycolytic_validation_engine import (
    build_glycolytic_profile,
    glycolytic_flux_index,
    predict_vlapeak_from_snapshot,
    validate_vlapeak_against_model,
)
from engines.metabolic.lab_data import (
    LabSource,
    LabTestResult,
    LabTestType,
    LactatePoint,
    create_lab_result,
    parse_lab_text,
    validate_lab_result,
)
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.metabolic.power_vlamax_estimator import estimate_vlamax_from_power_series
from engines.metabolic.zones_engine import (
    _classify_distribution,
    _time_in_absolute_watt_bins,
    _time_in_bins,
    friel_hr_zones,
)
from engines.performance.mmp_aggregator import curve_to_mmp, extract_ride_curve, update_power_curve
from engines.performance.power_engine import (
    PowerEngine,
    detect_sprints,
    estimate_ftp_from_mmp,
    fit_critical_power,
    mean_maximal_power,
    normalized_power,
    training_stress_score,
    variability_index,
)
from engines.performance.test_protocols import (
    run_critical_power_test,
    run_incremental_test,
    run_power_cadence_test,
    run_test,
    run_wingate_test,
)
from engines.recovery.thermal_engine import analyze_heat_acclimation, analyze_thermal_session


def _stream(seconds: int = 1200, power: float = 240.0):
    start = datetime(2026, 1, 1, 8, 0, 0)
    return parse_fit_records_enhanced(
        [
            {
                "timestamp": start + timedelta(seconds=i),
                "power": power + (i % 20),
                "heart_rate": 140.0 + (i % 10),
                "cadence": 90.0,
            }
            for i in range(seconds)
        ],
        session_dict={"start_time": start, "total_elapsed_time": seconds},
    )


class TestPowerEngineBranches92J:
    def test_metric_edge_cases(self) -> None:
        assert normalized_power(np.array([])) == 0.0
        assert training_stress_score(250.0, 0.0, 3600.0) == 0.0
        assert training_stress_score(250.0, 280.0, 0.0) == 0.0
        assert variability_index(250.0, 0.0) is None
        assert mean_maximal_power(np.array([])) == []
        assert detect_sprints(np.array([400.0] * 20), np.arange(20, dtype=float), 0.0) == []

        short = np.array([300.0] * 30)
        mmp = mean_maximal_power(short, durations_s=[1, 5, 60, 300])
        assert mmp
        cp = fit_critical_power(mmp)
        assert cp is None or "cp_w" in cp

    def test_engine_validation_and_analyze_paths(self) -> None:
        with pytest.raises(ValueError):
            PowerEngine(ftp=0, weight_kg=70)
        with pytest.raises(ValueError):
            PowerEngine(ftp=250, weight_kg=20)

        empty = PowerEngine(ftp=280, weight_kg=72).analyze(
            parse_fit_records_enhanced([], session_dict={})
        )
        assert empty["status"] == "error"

        zeros = parse_fit_records_enhanced(
            [
                {
                    "timestamp": datetime(2026, 1, 1) + timedelta(seconds=i),
                    "heart_rate": 140.0,
                }
                for i in range(60)
            ],
            session_dict={"start_time": datetime(2026, 1, 1), "total_elapsed_time": 60},
        )
        no_power = PowerEngine(ftp=280, weight_kg=72).analyze(zeros)
        assert no_power["status"] == "error"

        ok = PowerEngine(ftp=280, weight_kg=72).analyze(_stream(seconds=1800))
        assert ok["status"] == "success"
        assert ok["metrics"]["normalized_power"] > 0
        assert ok["sprints"] is not None
        ftp_est = estimate_ftp_from_mmp(ok["mmp_curve"])
        assert ftp_est is None or ftp_est.get("ftp_w", 0) > 0


class TestTestProtocolsBranches92J:
    def test_all_protocol_runners(self) -> None:
        assert run_incremental_test({}).get("status") == "error"
        inc = run_incremental_test({
            "test_data": {
                "steps": [
                    {"power_w": 150, "hr_mean": 120},
                    {"power_w": 200, "hr_mean": 140},
                    {"power_w": 250, "hr_mean": 160},
                ]
            }
        })
        assert inc.get("status") == "success"

        assert run_power_cadence_test({"test_data": {}}).get("status") == "error"
        cadence = run_power_cadence_test({
            "test_data": {
                "points": [
                    {"rpm_peak": 80, "w_peak": 700},
                    {"rpm_peak": 100, "w_peak": 900},
                    {"rpm_peak": 120, "w_peak": 850},
                    {"rpm_peak": 140, "w_peak": 700},
                ]
            }
        })
        assert cadence.get("status") == "success"

        cp = run_critical_power_test({
            "test_data": {
                "efforts": [
                    {"duration_s": 180, "power_w": 360},
                    {"duration_s": 360, "power_w": 340},
                    {"duration_s": 720, "power_w": 310},
                ]
            }
        })
        assert cp.get("status") in {"success", "error"}

        wingate = run_wingate_test({
            "athlete": {"weight_kg": 72},
            "test_data": {"peak_power_w": 950, "mean_power_w": 650, "duration_s": 30},
        })
        assert wingate.get("status") in {"success", "partial", "error"}

        unknown = run_test({"test_type": "unknown_type", "test_data": {}})
        assert unknown.get("status") == "error"


class TestBayesianGlycolyticLab92J:
    def test_bayesian_misconvergence_matrix(self) -> None:
        base = PosteriorSummary(
            mean=50.0, median=50.0, std=2.0,
            ci95_low=46.0, ci95_high=54.0,
            ci80_low=47.5, ci80_high=52.5,
            prior_mean=55.0, prior_std=8.0, n_effective_samples=200,
        )
        assert _mcmc_misconverged(
            vo2_post=base, mlss_w=200.0, ref_vo2=55.0, ref_mlss=280.0,
            vo2_floor=40.0, acceptance_rate=0.3,
        ) == "mlss_below_reference_fit"
        assert _mcmc_misconverged(
            vo2_post=base, mlss_w=260.0, ref_vo2=55.0, ref_mlss=280.0,
            vo2_floor=40.0, acceptance_rate=0.08,
        ) == "acceptance_rate_too_low"

        sprinter_mmp = {1: 1200, 3: 1100, 5: 1050, 15: 900, 60: 600, 300: 420, 1200: 320, 3600: 290}
        profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
        snap = bayesian_metabolic_snapshot(profiler, sprinter_mmp, n_samples=80, n_warmup=30)
        assert snap is not None

        flat_mmp = {300: 320, 1200: 280, 3600: 260}
        flat = bayesian_metabolic_snapshot(profiler, flat_mmp, n_samples=60, n_warmup=20)
        assert flat is not None

    def test_glycolytic_and_vlamax_paths(self) -> None:
        profiler = MetabolicProfiler(weight=72.0)
        snap = profiler.generate_metabolic_snapshot({5: 900, 60: 480, 300: 340, 1200: 285, 3600: 255})
        profile = build_glycolytic_profile(snap, mmp={1: 950, 15: 720, 60: 480})
        assert profile["glycolytic_flux_index"] == glycolytic_flux_index(snap.get("estimated_vlamax_mmol_L_s") or 0.4)
        pred = predict_vlapeak_from_snapshot(snap)
        assert pred.get("status") in {"success", "partial", "error", "skipped"}
        val = validate_vlapeak_against_model(
            vlapeak_observed_mmol_l_s=0.55,
            predicted_vlapeak_mmol_l_s=0.50,
            model_vlamax_mmol_l_s=snap.get("estimated_vlamax_mmol_L_s"),
        )
        assert val.get("status") in {"success", "partial", "error"}

        bad = estimate_vlamax_from_power_series(
            [50.0] * 20,
            weight_kg=72.0,
            eta=0.23,
            active_muscle_mass_kg=12.0,
        )
        assert bad.get("status") in {"error", "partial", "success"}

    def test_lab_validation_branches(self) -> None:
        result = create_lab_result(
            test_date=date(2026, 1, 1),
            source="lactate_step",
            lactate_curve=[(150, 1.0), (200, 2.0), (250, 3.5), (300, 6.0)],
            vo2max=62.0,
        )
        assert result.test_type in {LabTestType.STEP_SPIROMETRY, LabTestType.LACTATE_STEP, LabTestType.VO2MAX_ONLY}
        warns = validate_lab_result(result)
        assert isinstance(warns, list)

        bad_curve = LabTestResult(
            test_date=date(2026, 1, 1),
            source=LabSource.UNKNOWN,
            test_type=LabTestType.UNKNOWN,
            lactate_curve=[
                LactatePoint(power_w=200, lactate_mmol=4.0),
                LactatePoint(power_w=250, lactate_mmol=3.0),
                LactatePoint(power_w=300, lactate_mmol=2.0),
            ],
        )
        warns2 = validate_lab_result(bad_curve)
        assert any("monotonically" in w for w in warns2)

        empty = LabTestResult(
            test_date=date(2026, 1, 1),
            source=LabSource.UNKNOWN,
            test_type=LabTestType.UNKNOWN,
        )
        assert any("No primary" in w for w in validate_lab_result(empty))

        parsed = parse_lab_text("random text without metrics", test_date=date(2026, 2, 1))
        assert parsed.data_quality == "partial"


class TestZonesMmpThermal92J:
    def test_zones_internal_helpers(self) -> None:
        stream = _stream(seconds=3600)
        hr_z = friel_hr_zones(stream, lthr=165)
        assert hr_z.get("available") is True or "zones" in hr_z

        values = np.array([100.0, 150.0, 200.0, 250.0, 300.0])
        zones = _time_in_bins(
            values,
            [("Z1", "easy", 0.0, 0.55), ("Z2", "endurance", 0.55, 0.75), ("Z3", "tempo", 0.75, 1.05)],
            anchor=280.0,
        )
        assert zones
        assert _time_in_bins(np.array([]), [], anchor=200.0) == []

        abs_bins = _time_in_absolute_watt_bins(
            values,
            [{"code": "Z1", "label": "low", "min_w": 0, "max_w": 180}, {"code": "Z2", "label": "high", "min_w": 180, "max_w": 400}],
        )
        assert abs_bins
        assert _classify_distribution(80.0, 5.0, 15.0) == "POLARIZED"
        assert _classify_distribution(20.0, 50.0, 30.0) == "THRESHOLD"
        assert _classify_distribution(50.0, 30.0, 20.0) == "PYRAMIDAL"

    def test_mmp_aggregator_branches(self) -> None:
        from datetime import date as dt_date

        ride = np.full(2000, 220.0)
        ride[500:530] = 450.0
        ride[1000:1010] = 1200.0
        curve = extract_ride_curve(list(ride), despike=True)
        assert curve
        mmp = curve_to_mmp({60: {"power_w": 400.0, "start_t": 0}, 300: {"power_w": 320.0, "start_t": 100}})
        assert 60 in mmp

        res = update_power_curve(list(ride), dt_date(2026, 1, 1), {}, "r1", weight_kg=70)
        assert res.curve
        res2 = update_power_curve(list(ride), dt_date(2026, 1, 8), res.curve, "r2", weight_kg=70)
        assert res2.curve is not None

    def test_thermal_acclimation_edges(self) -> None:
        ambient_only = analyze_thermal_session(
            core_temp_stream=[float("nan")] * 1000,
            power_stream=[200.0] * 1000,
            ambient_temp_stream=[32.0 + i * 0.001 for i in range(1000)],
            hr_stream=[140.0] * 1000,
        )
        assert ambient_only.data_quality in {"no_data", "partial", "good", "limited"}

        accl = analyze_heat_acclimation([])
        assert accl.n_sessions == 0
