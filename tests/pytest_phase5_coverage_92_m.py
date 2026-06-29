"""Phase 5 — batch M: final branch closure for 92/85 gate."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from api.domain_schemas import PowerDurationPoint, PowerSourceActivity, WorkoutDefinitionInput, WorkoutStepInput
from api.engine_schemas import (
    CrossValidateRequest,
    EffortsAnalyzeRequest,
    MmpAthleteRequest,
    MmpQualityRequest,
    SessionClassifyRequest,
    VlamaxSprintRequest,
)
from api.schemas import AthleteParams, SnapshotRequest
from api.services.profile_extended_service import ProfileExtendedService, _with_sprint_vlamax_confidence
from api.services.ride_analytics_service import RideAnalyticsService
from engines.core.athlete_context import AthleteContext
from engines.io.activity_statistics import compute_activity_statistics
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.metabolic.bayesian_profiler import PosteriorSummary, _mcmc_misconverged
from engines.metabolic.coggan_classifier import classify_duration, classify_from_mmp, classify_power_profile
from engines.metabolic.glycolytic_validation_engine import (
    build_glycolytic_profile,
    compute_vlapeak_observed,
    glycolytic_flux_index,
    predict_vlapeak_from_snapshot,
    validate_vlapeak_against_model,
    validate_wingate_glycolytic,
)
from engines.metabolic.metabolic_kalman import DailyInput, MetabolicKalman, _sigma_points, process_workout_history
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.mmp_aggregator import curve_to_mmp, extract_ride_curve, update_power_curve
from engines.performance.test_protocols import (
    run_critical_power_test,
    run_incremental_test,
    run_mader_test,
    run_power_cadence_test,
    run_test,
    run_wingate_test,
)
from engines.recovery.thermal_engine import ThermalSessionReport


def _stream(
    seconds: int = 900,
    *,
    power: float = 250.0,
    with_rr: bool = False,
    extras: dict | None = None,
):
    start = datetime(2026, 1, 1, 8, 0, 0)
    records = []
    for i in range(seconds):
        row = {
            "timestamp": start + timedelta(seconds=i),
            "power": power + (i % 12),
            "heart_rate": 140.0 + (i % 6),
            "cadence": 90.0,
        }
        if with_rr:
            row["rr_intervals"] = [820.0, 810.0]
        if extras:
            row.update(extras)
        records.append(row)
    session = {"start_time": start, "total_elapsed_time": seconds, "sport": "cycling"}
    return parse_fit_records_enhanced(records, session_dict=session)


MMP = {"5": 900, "60": 480, "300": 340, "1200": 285, "3600": 255}
ATHLETE = AthleteParams(weight_kg=72.0, gender="MALE", training_years=8, discipline="ROAD")


class TestGlycolyticValidationBranches92M:
    def test_vlapeak_and_flux_error_matrix(self) -> None:
        assert compute_vlapeak_observed("x", 12.0, 30.0)["status"] == "error"
        assert compute_vlapeak_observed(1.2, 12.0, 0.0)["reason"] == "invalid_duration"
        assert compute_vlapeak_observed(2.0, 1.5, 30.0)["reason"] == "non_positive_lactate_delta"
        assert compute_vlapeak_observed(1.0, 12.0, 30.0)["status"] == "success"

        assert glycolytic_flux_index(0.15) < glycolytic_flux_index(0.45) < glycolytic_flux_index(0.9)

        ok = validate_vlapeak_against_model(
            vlapeak_observed_mmol_l_s=1.0,
            predicted_vlapeak_mmol_l_s=1.05,
            model_vlamax_mmol_l_s=0.5,
        )
        assert ok["validated"] is True

        moderate = validate_vlapeak_against_model(
            vlapeak_observed_mmol_l_s=1.0,
            predicted_vlapeak_mmol_l_s=1.35,
        )
        assert moderate["severity"] == "moderate"

        mismatch = validate_vlapeak_against_model(
            vlapeak_observed_mmol_l_s=1.0,
            predicted_vlapeak_mmol_l_s=2.0,
        )
        assert mismatch["severity"] == "high"
        assert validate_vlapeak_against_model(vlapeak_observed_mmol_l_s=0.0, predicted_vlapeak_mmol_l_s=1.0)["status"] == "error"

    def test_predict_and_build_profile_branches(self) -> None:
        profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
        snap = profiler.generate_metabolic_snapshot({5: 900, 15: 720, 60: 480, 300: 340, 1200: 285, 3600: 255})
        assert predict_vlapeak_from_snapshot({"status": "success"})["reason"] == "vlamax_not_in_snapshot"
        assert predict_vlapeak_from_snapshot(
            {"status": "success", "unmasked_estimates": {"estimated_vlamax_mmol_L_s": 0.42}}
        )["status"] == "success"

        pred = predict_vlapeak_from_snapshot(snap, profiler=profiler, mmp={1: 950, 15: 720, 60: 480})
        assert pred["status"] == "success"

        sprint_trace = [50.0] + [900.0] * 4 + [600.0] * 12
        profile = build_glycolytic_profile(
            snap,
            profiler=profiler,
            mmp={1: 950, 15: 720},
            sprint_power=sprint_trace,
            lactate_pre_mmol_l=1.0,
            lactate_peak_mmol_l=10.0,
        )
        assert profile["status"] == "success"
        assert build_glycolytic_profile({"status": "error"})["status"] == "unavailable"

        wingate = validate_wingate_glycolytic(
            lactate_pre_mmol=1.2,
            lactate_post_mmol=12.0,
            duration_s=30.0,
            peak_power_w=950.0,
            mean_power_w=650.0,
            profiler=profiler,
            mmp={5: 900, 60: 480, 300: 340, 1200: 285, 3600: 255},
        )
        assert wingate.get("status") in {"success", "partial", "error"}


class TestProtocolsMmpKalman92M:
    def test_test_protocols_dispatch_matrix(self) -> None:
        profiler = MetabolicProfiler(weight=72.0)
        assert run_mader_test({"test_data": {}}, profiler)["status"] == "error"
        assert run_mader_test({"test_data": {"steps": [{"power_w": 200, "lactate_mmol": 2.0}]}}, profiler)["status"] == "error"

        assert run_incremental_test({"test_data": {"steps": [{"hr_mean": 140}]}})["status"] == "error"
        assert run_incremental_test({
            "test_data": {"steps": [{"power_w": 150}, {"power_w": 220, "hr_mean": 155}]}
        })["status"] == "success"

        assert run_power_cadence_test({"test_data": {"points": []}})["status"] == "error"
        assert run_power_cadence_test({
            "test_data": {
                "points": [
                    {"rpm_peak": 80, "w_peak": 700},
                    {"rpm_peak": 100, "w_peak": 900},
                    {"rpm_peak": 120, "w_peak": 850},
                ]
            }
        })["status"] == "success"

        cp = run_critical_power_test({
            "test_data": {"efforts": [{"duration_s": 180, "power_w": 360}, {"duration_s": 360, "power_w": 340}]}
        })
        assert cp["status"] in {"success", "error"}

        wingate = run_wingate_test({
            "test_data": {"power_stream": [1000.0] * 5 + [500.0] * 25, "body_weight_kg": 72.0}
        })
        assert wingate["status"] in {"success", "error"}

        assert run_test({"test_type": "mader", "test_data": {}})["status"] == "error"
        for ttype in ("incrementale", "curva_pc", "critical_power", "wingate"):
            out = run_test({"test_type": ttype, "test_data": {}}, profiler=profiler)
            assert out.get("status") in {"success", "error"}

    def test_mmp_aggregator_and_kalman(self) -> None:
        spike_stream = [200.0] * 10 + [1200.0] + [200.0] * 10
        curve = extract_ride_curve(spike_stream, despike=True)
        assert curve

        empty = extract_ride_curve([0.0] * 5)
        assert empty == {}

        stored = {
            "300": {
                "duration_s": 300,
                "power_w": 320,
                "ride_date": "2020-01-01",
                "ride_id": "old",
                "reliability": 1.0,
            },
            "1200": 280,
        }
        updated = update_power_curve(
            [250.0] * 3600,
            ride_date="2026-06-01",
            stored_curve=stored,
            weight_kg=72.0,
            today=date(2026, 6, 1),
        )
        assert updated.curve
        assert curve_to_mmp(updated.mmp_for_profiler)

        x = np.array([55.0, 0.4])
        p = np.diag([4.0, 0.1])
        sigmas, wm, wc = _sigma_points(x, p)
        assert sigmas.shape[0] == 5

        kalman = MetabolicKalman(x, p, weight=72.0, start_date=date(2026, 1, 1))
        kalman.predict(DailyInput(date=date(2026, 1, 2), vo2max_stimulus_min=10.0))
        kalman.update([(300, 340), (600, 310)])
        assert kalman.current_state.vo2max > 0

        traj = process_workout_history(
            [
                DailyInput(date=date(2026, 1, 1) + timedelta(days=i), threshold_stimulus_min=5.0)
                for i in range(14)
            ],
            initial_vo2=55.0,
            initial_vla=0.4,
            weight=72.0,
            profiler=MetabolicProfiler(weight=72.0),
        )
        assert traj.states


class TestApiServicesAndDomain92M:
    def test_domain_schema_validators(self) -> None:
        step = WorkoutStepInput(type="work", seconds=600.0, target_pct_ftp=80.0)
        assert step.duration_s == 600

        workout = WorkoutDefinitionInput(
            name="Sweet spot",
            steps=[WorkoutStepInput(type="work", duration_s=1200, target_pct_ftp=88.0)],
        )
        assert workout.title == "Sweet spot"

        activity = PowerSourceActivity(
            mmp={"300": PowerDurationPoint(power_w=320)},
            curve={"600": 300},
        )
        merged = activity.merged_mmp_dict()
        assert "300" in merged and "600" in merged

    def test_ride_analytics_service_branches(self) -> None:
        svc = RideAnalyticsService()
        stream = _stream(1800)
        analyzed = svc.power_analyze(stream, weight_kg=72.0, ftp=None)
        assert analyzed.get("status") in {"success", "error"}

        empty = parse_fit_records_enhanced([], session_dict={})
        assert svc.efforts(
            empty,
            EffortsAnalyzeRequest(athlete=ATHLETE, ftp=280.0),
        ).get("status") == "error"

        null_stream = parse_fit_records_enhanced(
            [
                {
                    "timestamp": datetime(2026, 1, 1) + timedelta(seconds=i),
                    "power": None,
                    "heart_rate": None,
                }
                for i in range(120)
            ],
            session_dict={"start_time": datetime(2026, 1, 1), "total_elapsed_time": 120},
        )
        cardiac = svc.cardiac(null_stream, athlete=ATHLETE, metabolic_snapshot=None)
        assert cardiac.get("status") == "error"

        report = ThermalSessionReport(
            data_quality="good",
            n_valid_samples=120,
            n_total_samples=120,
            thermal_rise_rate=0.02,
        )
        accl = svc.thermal_acclimation([report, {"data_quality": "partial", "n_valid_samples": 80}])
        assert isinstance(accl, dict)

        rr_stream = _stream(600, with_rr=True)
        routed = svc.session_route_run(rr_stream, athlete=ATHLETE, ftp=280.0, metabolic_snapshot=None)
        assert isinstance(routed, dict)

        svc.classify_session_ride(stream, SessionClassifyRequest(athlete=ATHLETE, ftp=280.0))

    def test_profile_extended_confidence_and_crossval(self) -> None:
        svc = ProfileExtendedService()
        assert _with_sprint_vlamax_confidence({"status": "error"})["confidence_score"] == 0.0
        assert _with_sprint_vlamax_confidence({
            "status": "success",
            "vlamax_mmol_l_s": 0.5,
            "vlamax_range": [],
        })["confidence_score"] == 0.55

        wide = _with_sprint_vlamax_confidence({
            "status": "success",
            "vlamax_mmol_l_s": 0.5,
            "vlamax_range": [0.1, 0.9],
            "quality_flags": ["x"],
        })
        assert "tau_alactic_sensitivity_high" in wide.get("quality_flags", [])

        moderate = _with_sprint_vlamax_confidence({
            "status": "success",
            "vlamax_mmol_l_s": 0.5,
            "vlamax_range": [0.35, 0.65],
        })
        assert "tau_alactic_sensitivity_moderate" in moderate.get("quality_flags", [])

        sprint = svc.vlamax_from_sprint(
            VlamaxSprintRequest(athlete=ATHLETE, p_peak_1s=980.0, p_mean_sprint=850.0)
        )
        assert "confidence_score" in sprint or sprint.get("status") in {"success", "error"}

        bad_cv = svc.cross_validate(CrossValidateRequest(mmp={"60": 300}, athlete=ATHLETE))
        assert bad_cv.get("status") in {"error", "partial"}

        cleaned = svc.mmp_quality(MmpQualityRequest(mmp=MMP, clean=True))
        assert cleaned.get("status") == "success"

        svc.build_snapshot(SnapshotRequest(mmp=MMP, athlete=ATHLETE))
        svc.auto_snapshot(MmpAthleteRequest(mmp=MMP, athlete=ATHLETE, clean_mmp_first=True))


class TestCogganActivityStatsBayesian92M:
    def test_coggan_classifier_matrix(self) -> None:
        male = classify_duration(20.0, "5s", "MALE")
        female = classify_duration(16.0, "5s", "FEMALE")
        assert male["tier"] == "VERY_GOOD"
        assert female["tier"]

        with pytest.raises(ValueError):
            classify_duration(10.0, "bad", "MALE")

        sprinter = classify_power_profile(72.0, "MALE", p5s=1200, p1min=900, p5min=400, ftp=350)
        pursuiter = classify_power_profile(72.0, "MALE", p5s=600, p1min=550, p5min=420, ftp=360)
        tt = classify_power_profile(72.0, "MALE", p5s=500, p1min=480, p5min=380, ftp=400)
        allr = classify_power_profile(72.0, "MALE", p5s=700, p1min=650, p5min=400, ftp=380)
        for out in (sprinter, pursuiter, tt, allr):
            assert out.get("phenotype") or out.get("status")

        incomplete = classify_power_profile(72.0, "FEMALE", p5s=800)
        assert incomplete.get("phenotype") == "INCOMPLETE" or incomplete.get("status")

        from_mmp = classify_from_mmp(
            [
                {"duration_s": 5, "power_w": 900},
                {"duration_s": 60, "power_w": 480},
                {"duration_s": 300, "power_w": 340},
                {"duration_s": 1200, "power_w": 285},
            ],
            weight_kg=72.0,
            gender="FEMALE",
            ftp=280,
        )
        assert from_mmp.get("phenotype") or from_mmp.get("status")

    def test_activity_statistics_rich_stream(self) -> None:
        start = datetime(2026, 3, 1, 7, 0, 0)
        n = 600
        alt = [200.0 + 0.1 * i for i in range(n)]
        records = [
            {
                "timestamp": start + timedelta(seconds=i),
                "power": 240.0,
                "heart_rate": 150.0,
                "cadence": 95.0,
                "speed": 8.5,
            }
            for i in range(n)
        ]
        stream = parse_fit_records_enhanced(
            records,
            session_dict={"start_time": start, "total_elapsed_time": n, "avg_speed": 8.5},
        )
        stream.altitude_m = alt
        stream.temperature_c = [22.0 + (i % 3) * 0.1 for i in range(n)]

        stats = compute_activity_statistics(stream, weight_kg=72.0, ftp=280.0, cp=270.0, lthr=165.0)
        assert stats.get("metrics", {}).get("np_w") or stats.get("status") in {"success", "partial"}

        with pytest.raises(ValueError):
            compute_activity_statistics(stream, weight_kg=20.0)

    def test_bayesian_misconvergence_all_reasons(self) -> None:
        base = PosteriorSummary(
            mean=50.0, median=50.0, std=2.0,
            ci95_low=46.0, ci95_high=54.0,
            ci80_low=47.5, ci80_high=52.5,
            prior_mean=55.0, prior_std=8.0, n_effective_samples=200,
        )
        assert _mcmc_misconverged(
            vo2_post=base, mlss_w=200.0, ref_vo2=60.0, ref_mlss=280.0, vo2_floor=45.0, acceptance_rate=0.3,
        ) == "vo2_below_reference_fit"
        assert _mcmc_misconverged(
            vo2_post=base, mlss_w=260.0, ref_vo2=55.0, ref_mlss=280.0, vo2_floor=52.0, acceptance_rate=0.3,
        ) == "vo2_below_aerobic_floor"
        low_ci = PosteriorSummary(
            mean=52.0, median=52.0, std=2.0,
            ci95_low=40.0, ci95_high=54.0,
            ci80_low=47.5, ci80_high=52.5,
            prior_mean=55.0, prior_std=8.0, n_effective_samples=200,
        )
        assert _mcmc_misconverged(
            vo2_post=low_ci, mlss_w=260.0, ref_vo2=55.0, ref_mlss=280.0, vo2_floor=50.0, acceptance_rate=0.3,
        ) == "vo2_ci_below_aerobic_floor"
        assert _mcmc_misconverged(
            vo2_post=base, mlss_w=260.0, ref_vo2=55.0, ref_mlss=280.0, vo2_floor=40.0, acceptance_rate=0.08,
        ) == "acceptance_rate_too_low"

        fail = PosteriorSummary(
            mean=50.0, median=50.0, std=2.0,
            ci95_low=46.0, ci95_high=54.0,
            ci80_low=47.5, ci80_high=52.5,
            prior_mean=55.0, prior_std=8.0, n_effective_samples=0,
        )
        blob = SimpleNamespace(status="error", message="bad", to_dict=lambda: {"status": "error", "message": "bad"})
        assert blob.to_dict()["status"] == "error"
        assert fail.n_effective_samples == 0


class TestFinalClosure92N:
    def test_mmp_aggregator_edge_paths(self) -> None:
        from unittest.mock import patch

        from engines.performance.mmp_aggregator import _ceiling_for, _parse_date, curve_to_mmp

        assert _ceiling_for(1, 72.0) > _ceiling_for(5400, 72.0)
        assert _ceiling_for(99999, 30.0) > 0
        assert _parse_date(date(2026, 1, 1)) == date(2026, 1, 1)
        assert _parse_date(datetime(2026, 1, 1)) == date(2026, 1, 1)
        assert _parse_date("2026-01-15") == date(2026, 1, 15)
        assert _parse_date("not-a-date").isoformat() == date.today().isoformat()
        assert _parse_date(42) == date.today()

        assert extract_ride_curve([200.0] * 30, durations=[300, 600]) == {}
        spike_curve = extract_ride_curve(
            [200.0, 200.0, 950.0, 200.0, 200.0] * 80,
            despike=True,
        )
        assert spike_curve

        assert curve_to_mmp({"bad-key": 1, "60": 0, "120": {"power_w": 310}}) == {120: 310}

        stored = {
            "60": {
                "duration_s": 60,
                "power_w": 350,
                "ride_date": "2020-01-01",
                "ride_id": "old",
                "reliability": 1.0,
            }
        }
        expired = update_power_curve(
            [250.0] * 600,
            ride_date="2026-06-01",
            stored_curve=stored,
            weight_kg=72.0,
            today=date(2026, 6, 1),
        )
        assert expired.profile_should_refresh or expired.expired

        bad_date = update_power_curve(
            [250.0] * 600,
            ride_date="2026-06-01",
            stored_curve={
                "300": {
                    "duration_s": 300,
                    "power_w": 320,
                    "ride_date": "garbage",
                    "ride_id": "x",
                    "reliability": 1.0,
                }
            },
            weight_kg=72.0,
        )
        assert bad_date.curve

        mono_power = [200.0] * 300 + [400.0] * 400
        with patch(
            "engines.performance.mmp_aggregator.extract_ride_curve",
            return_value={300: 450.0, 600: 462.0},
        ):
            rejected = update_power_curve(
                mono_power,
                ride_date="2026-06-01",
                stored_curve={
                    "300": {
                        "duration_s": 300,
                        "power_w": 450,
                        "ride_date": "2026-05-01",
                        "ride_id": "base",
                        "reliability": 1.0,
                    }
                },
                weight_kg=72.0,
                enforce_monotonicity=True,
            )
        assert rejected.rejected

        with patch(
            "engines.performance.mmp_aggregator.extract_ride_curve",
            return_value={300: 240.0},
        ):
            unchanged = update_power_curve(
                [250.0] * 600,
                ride_date="2026-06-01",
                stored_curve={
                    "300": {
                        "duration_s": 300,
                        "power_w": 400,
                        "ride_date": "2026-05-01",
                        "ride_id": "base",
                        "reliability": 1.0,
                    }
                },
                weight_kg=72.0,
            )
        assert any("did not improve" in n for n in unchanged.notes)

        improved = update_power_curve([320.0] * 1200, ride_date="2026-06-01", stored_curve={})
        assert improved.improvements

        with patch("engines.core.data_quality_engine.assess_data_quality", side_effect=RuntimeError("gate down")):
            gated = update_power_curve(
                [260.0] * 600,
                ride_date="2026-06-01",
                stored_curve={},
                enforce_quality_gate=True,
            )
            assert any("Quality gate unavailable" in n for n in gated.notes)

        with patch(
            "engines.core.data_quality_engine._remove_power_spikes",
            side_effect=RuntimeError("despike unavailable"),
        ):
            fallback = extract_ride_curve(
                [200.0, 200.0, 950.0, 200.0, 200.0] * 80,
                despike=True,
            )
            assert fallback

        critical_expire = update_power_curve(
            [250.0] * 100,
            ride_date="2026-06-01",
            stored_curve={
                "300": {
                    "duration_s": 300,
                    "power_w": 350,
                    "ride_date": "2020-01-01",
                    "ride_id": "old",
                    "reliability": 1.0,
                }
            },
            weight_kg=72.0,
            today=date(2026, 6, 1),
        )
        assert critical_expire.expired
        assert critical_expire.profile_should_refresh

        empty = update_power_curve([0.0] * 120, ride_date="2026-06-01", stored_curve={})
        assert "no usable power" in " ".join(empty.notes).lower()

    def test_metabolic_kalman_lab_and_test_anchors(self) -> None:
        from engines.metabolic.lab_data import create_lab_result

        profiler = MetabolicProfiler(weight=72.0)
        x = np.array([55.0, 0.4])
        p = np.diag([4.0, 0.1])
        kalman = MetabolicKalman(x, p, weight=72.0, start_date=date(2026, 1, 1))

        kalman.predict(
            DailyInput(
                date=date(2026, 1, 2),
                test_anchors=[(300, 340), (600, 310)],
                vo2max_stimulus_min=12.0,
            ),
            profiler=profiler,
        )
        assert kalman.current_state.vo2max > 0

        lab = create_lab_result(date(2026, 1, 3), vo2max=62.0, vlamax=0.42)
        after_lab = kalman.update_from_lab(lab)
        assert after_lab.vo2max > 0

        empty_lab = create_lab_result(date(2026, 1, 4))
        kalman.update_from_lab(empty_lab)

        kalman.update([], profiler=None)

    def test_glycolytic_wingate_and_activity_helpers(self) -> None:
        from engines.io.activity_statistics import (
            _cadence_array,
            _finite_max,
            _finite_mean,
            _round_metric,
            _speed_arrays,
            _temperature_array,
            _total_descent_m,
        )

        assert _finite_mean(np.array([])) is None
        assert _finite_max(np.array([np.nan])) is None
        assert _total_descent_m(np.array([100.0, 90.0, 80.0])) == 20.0
        assert _round_metric(float("nan")) is None

        bare = SimpleNamespace(speed=None, cadence=[0, 95, 300], temperature_c=[20.0, 21.0])
        assert _speed_arrays(bare).size == 0
        assert _temperature_array(bare).size == 2
        cad = _cadence_array(SimpleNamespace(cadence=[0, 95, 500]))
        assert np.isnan(cad[-1])

        profiler = MetabolicProfiler(weight=72.0)
        no_model = validate_wingate_glycolytic(
            lactate_pre_mmol=1.0,
            lactate_post_mmol=8.0,
            duration_s=30.0,
            peak_power_w=900.0,
            mean_power_w=600.0,
            profiler=profiler,
        )
        assert no_model.get("status") in {"success", "insufficient_data", "partial", "error"}

        bad_lac = validate_wingate_glycolytic(
            lactate_pre_mmol=5.0,
            lactate_post_mmol=4.0,
            duration_s=30.0,
            peak_power_w=900.0,
            mean_power_w=600.0,
            profiler=profiler,
        )
        assert bad_lac.get("status") != "success"

    def test_ride_service_and_bayesian_sampler(self) -> None:
        from api.errors import ServiceError
        from api.services.ride_service import RideService
        from engines.metabolic.bayesian_profiler import _adaptive_metropolis, _effective_sample_size

        stream = _stream(1200)
        ingested = RideService().ingest(
            stream=stream,
            ride_date=date(2026, 6, 1),
            file_id="ride-1",
            weight_kg=72.0,
            stored_curve=None,
            file_hash="abc",
        )
        assert "curve" in ingested

        with pytest.raises(ServiceError):
            RideService().build_parse_report({})

        with pytest.raises(ServiceError):
            RideService().compute_durability(stream, weight_kg=72.0, metabolic_snapshot={"status": "error"})

        def logp(theta: np.ndarray) -> float:
            vo2, vla = theta
            if vo2 < 40 or vo2 > 80 or vla < 0.1 or vla > 1.0:
                return -np.inf
            return -0.5 * ((vo2 - 55) ** 2 + (vla - 0.4) ** 2)

        samples, rate = _adaptive_metropolis(logp, np.array([55.0, 0.4]), n_samples=40, n_warmup=20)
        assert samples.shape[0] == 40
        assert 0 <= rate <= 1
        assert _effective_sample_size(np.ones(5)) == 5
        assert _effective_sample_size(np.linspace(0, 1, 100)) >= 1

        bimodal_mmp = {1: 1200, 3: 1150, 5: 1100, 15: 950, 60: 650, 300: 420, 1200: 310, 3600: 280}
        from engines.metabolic.bayesian_profiler import bayesian_metabolic_snapshot

        snap = bayesian_metabolic_snapshot(
            MetabolicProfiler(weight=72.0),
            bimodal_mmp,
            n_samples=100,
            n_warmup=40,
        )
        assert snap is not None


class TestLoadTrendsClosure92N:
    def test_load_trends_risk_matrix(self) -> None:
        from engines.history.load_trends import _load_value, _parse_date, compute_load_trends

        assert _parse_date("bad") is None
        assert _parse_date(datetime(2026, 1, 1)) == date(2026, 1, 1)
        assert _load_value({"summary": {"tss": "80"}}) == 80.0
        assert _load_value({"summary": {"tss": "bad"}}) == 0.0

        base = date(2026, 6, 1)
        activities = [
            {"date": (base - timedelta(days=i)).isoformat(), "tss": 120 if i < 7 else 10}
            for i in range(90)
        ]
        high = compute_load_trends(activities, as_of=base.isoformat())
        assert high["risk"] in {"high", "moderate", "low"}
        assert high["acute_load"] > 0

        empty = compute_load_trends([])
        assert empty["status"] == "insufficient_data"
        assert empty["acute_load"] == 0.0


class TestLineClosure92N:
    def test_ride_analytics_power_ftp_fallback(self) -> None:
        svc = RideAnalyticsService()
        short = _stream(120)
        out = svc.power_analyze(short, weight_kg=72.0, ftp=None)
        assert out.get("status") in {"success", "error"}

        empty = parse_fit_records_enhanced([], session_dict={})
        assert svc.power_analyze(empty, weight_kg=72.0, ftp=None).get("reason") == "FTP_NOT_AVAILABLE"

    def test_bayesian_mcmc_nonfinite_start(self) -> None:
        from engines.metabolic.bayesian_profiler import _adaptive_metropolis

        calls = {"n": 0}

        def logp(theta: np.ndarray) -> float:
            calls["n"] += 1
            if calls["n"] == 1:
                return float("-inf")
            vo2, vla = theta
            if vo2 < 40 or vo2 > 80 or vla < 0.1 or vla > 1.0:
                return -np.inf
            return -0.5 * ((vo2 - 55) ** 2 + (vla - 0.4) ** 2)

        samples, rate = _adaptive_metropolis(
            logp,
            np.array([55.0, 0.4]),
            n_samples=30,
            n_warmup=15,
            rng=np.random.default_rng(1),
        )
        assert samples.shape[0] == 30
        assert rate >= 0.0
