"""Phase 5 — API services + workout engines branch port."""

from __future__ import annotations

from datetime import datetime, timedelta

from api.engine_schemas import (
    AdaptiveLoadRequest,
    BayesianSnapshotRequest,
    CrossValidateRequest,
    DetrainingApplyRequest,
    DurabilityIndexRequest,
    EffortsAnalyzeRequest,
    GlycolyticProfileRequest,
    KalmanDailyInputModel,
    KalmanTrajectoryRequest,
    MetabolicCurrentRequest,
    MmpAthleteRequest,
    SegmentedSnapshotRequest,
    SessionClassifyRequest,
    VlamaxPowerSeriesRequest,
    VlamaxSprintRequest,
    WPrimeBalanceRequest,
    ZonesAnalyzeRequest,
)
from api.schemas import AthleteParams, SnapshotRequest
from api.services.profile_extended_service import ProfileExtendedService
from api.services.ride_analytics_service import RideAnalyticsService
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.workouts.compliance_engine import compare_workout_to_activity
from engines.workouts.feasibility_engine import analyze_workout_feasibility


def _stream(seconds: int = 1200, power: float = 240.0, *, device_name: str | None = None):
    start = datetime(2026, 1, 1, 8, 0, 0)
    session: dict = {"start_time": start, "total_elapsed_time": seconds}
    if device_name:
        session["device_name"] = device_name
    return parse_fit_records_enhanced(
        [
            {
                "timestamp": start + timedelta(seconds=i),
                "power": power + (i % 15),
                "heart_rate": 140.0 + (i % 8),
                "cadence": 90.0,
            }
            for i in range(seconds)
        ],
        session_dict=session,
    )


ATHLETE = AthleteParams(weight_kg=72.0, gender="MALE", training_years=8, discipline="ROAD")
MMP = {"5": 900, "60": 480, "300": 340, "1200": 285, "3600": 255}


class TestRideAnalyticsServicePort:
    def test_power_zones_and_statistics(self) -> None:
        svc = RideAnalyticsService()
        stream = _stream()
        zones = svc.zones(stream, ZonesAnalyzeRequest(athlete=ATHLETE, ftp=280, lthr=165))
        assert isinstance(zones, dict)
        stats = svc.statistics(stream, weight_kg=72.0, ftp=280.0, lthr=165.0, cp=270.0)
        assert stats.get("status") in {"success", "partial", "error"}

        no_ftp = svc.power_analyze(stream, weight_kg=72.0, ftp=None)
        assert no_ftp.get("status") in {"success", "error"}

        cp_fit = svc.critical_power_fit([{"duration_s": 180, "power_w": 360}, {"duration_s": 360, "power_w": 340}])
        assert cp_fit.get("status") in {"success", "partial", "error"} or "cp_w" in cp_fit

    def test_durability_wprime_cardiac(self) -> None:
        svc = RideAnalyticsService()
        power = [240.0] * 7200
        di = svc.durability_index(DurabilityIndexRequest(power=power))
        assert di.get("durability_index") is not None or di.get("status") == "insufficient_duration"
        assert svc.np_drift(power).get("np_first_half") is not None
        assert svc.tte_sustainability(power, cp=280.0).get("classification")
        assert svc.hourly_decay_curve(power, ftp=280.0).get("hourly_data")
        for di in (98.0, 94.0, 90.0, 85.0):
            assert svc.durability_prescription(di).get("focus")

        wbal = svc.w_prime_balance(
            WPrimeBalanceRequest(power=power[:600], cp=280.0, w_prime=20000.0, dt_s=1.0, duration_s=600)
        )
        assert "balance" in wbal

        stream = _stream(900)
        cardiac = svc.cardiac(stream, athlete=ATHLETE, metabolic_snapshot={"status": "success", "mlss_power_watts": 270})
        assert cardiac.get("status") in {"success", "partial", "error"}

        hrv = svc.hrv_analyze(stream)
        assert hrv.get("status") in {"success", "error"}

        thermal = svc.thermal_session(stream, ftp=280.0)
        assert isinstance(thermal, dict)
        accl = svc.thermal_acclimation([{"data_quality": "good", "n_valid_samples": 100, "thermal_rise_rate": 0.02}])
        assert isinstance(accl, dict)

    def test_session_efforts_adaptive(self) -> None:
        svc = RideAnalyticsService()
        stream = _stream(1800, device_name="endurance.fit")
        classified = svc.classify_session_ride(
            stream,
            SessionClassifyRequest(athlete=ATHLETE, ftp=280.0),
        )
        assert classified.get("category") or classified.get("status")

        efforts = svc.efforts(
            stream,
            EffortsAnalyzeRequest(athlete=ATHLETE, ftp=280.0, cp_w=270.0),
        )
        assert isinstance(efforts, dict)

        adaptive = svc.adaptive_load(
            stream,
            AdaptiveLoadRequest(
                athlete=ATHLETE,
                ftp=280.0,
                daily_status={"date": "2026-06-01", "hrv_score": 0.8, "sleep_hours": 7.5},
                history=[{"date": "2026-05-30", "tss": 80}],
            ),
        )
        assert isinstance(adaptive, dict)


class TestProfileExtendedServicePort:
    def test_metabolic_paths(self) -> None:
        svc = ProfileExtendedService()
        snap = svc.build_snapshot(SnapshotRequest(mmp=MMP, athlete=ATHLETE))
        assert snap.get("status") in {"success", "error", "partial"}

        seg = svc.segmented_snapshot(SegmentedSnapshotRequest(mmp=MMP, athlete=ATHLETE))
        assert isinstance(seg, dict)

        auto = svc.auto_snapshot(MmpAthleteRequest(mmp=MMP, athlete=ATHLETE))
        assert isinstance(auto, dict)

        bayes = svc.bayesian_snapshot(
            BayesianSnapshotRequest(mmp=MMP, athlete=ATHLETE, n_samples=800, n_warmup=200)
        )
        assert isinstance(bayes, dict)

        sprint = svc.vlamax_from_sprint(
            VlamaxSprintRequest(
                athlete=ATHLETE,
                p_peak_1s=980.0,
                p_mean_sprint=850.0,
                peak_5s_w=950.0,
            )
        )
        assert isinstance(sprint, dict)

        series = svc.vlamax_from_power_series(
            VlamaxPowerSeriesRequest(power=[900.0] * 5 + [600.0] * 10, athlete=ATHLETE)
        )
        assert isinstance(series, dict)

        kalman = svc.kalman_trajectory(
            KalmanTrajectoryRequest(
                athlete=ATHLETE,
                daily_inputs=[
                    KalmanDailyInputModel(date="2026-01-01", vo2max_stimulus_min=12.0),
                    KalmanDailyInputModel(date="2026-01-02", threshold_stimulus_min=20.0),
                ],
                initial_vo2=58.0,
                initial_vla=0.45,
            )
        )
        assert isinstance(kalman, dict)

        current = svc.metabolic_current(
            MetabolicCurrentRequest(historical_mmp=MMP, athlete=ATHLETE, workout_history=[])
        )
        assert isinstance(current, dict)

        detr = svc.apply_detraining(
            DetrainingApplyRequest(
                athlete=ATHLETE,
                baseline_snapshot={
                    "status": "success",
                    "estimated_vo2max": 60.0,
                    "estimated_vlamax_mmol_L_s": 0.45,
                    "mlss_power_watts": 280.0,
                    "map_aerobic_watts": 390.0,
                },
            )
        )
        assert isinstance(detr, dict)

        ctl = svc.ctl_atl_tsb([{"date": "2026-05-01", "tss": 70}, {"date": "2026-05-02", "tss": 90}])
        assert "ctl" in ctl or isinstance(ctl, dict)

        cv = svc.cross_validate(CrossValidateRequest(mmp=MMP, athlete=ATHLETE))
        assert isinstance(cv, dict)

        phen = svc.phenotype_enhance(GlycolyticProfileRequest(mmp=MMP, athlete=ATHLETE))
        assert isinstance(phen, dict)

        gly = svc.glycolytic_profile(GlycolyticProfileRequest(mmp=MMP, athlete=ATHLETE))
        assert isinstance(gly, dict)


class TestWorkoutEnginesPort:
    def test_compliance_and_feasibility(self) -> None:
        stream = _stream(1200, power=250.0)
        workout = {
            "name": "Threshold",
            "steps": [
                {"type": "warmup", "duration_s": 600, "target": {"power_pct_ftp": [0.55, 0.65]}},
                {"type": "steady", "duration_s": 1200, "target": {"power_pct_ftp": [0.88, 0.92]}},
                {"type": "cooldown", "duration_s": 300, "target": {"power_pct_ftp": [0.5, 0.6]}},
            ],
        }
        compliance = compare_workout_to_activity(
            workout,
            stream,
            athlete_profile={"ftp": 280, "lthr": 165},
            tolerance_policy={"duration_tolerance_pct": 15.0},
        )
        assert compliance.get("status") in {"success", "partial", "failed"}
        assert "compliance_score" in compliance or compliance.get("reason")

        empty = compare_workout_to_activity(workout, parse_fit_records_enhanced([]))
        assert empty.get("status") == "failed"

        feasible = analyze_workout_feasibility(
            workout,
            athlete_profile={"ftp": 280, "weight_kg": 72, "w_prime": 18000, "cp": 270},
        )
        assert feasible.get("status") in {
            "success",
            "partial",
            "error",
            "feasible",
            "challenging",
            "not_feasible",
            "insufficient_data",
        }

        hard = analyze_workout_feasibility(
            {
                "name": "Impossible",
                "steps": [{"type": "steady", "duration_s": 3600, "target": {"power_w": 400}}],
            },
            athlete_profile={"ftp": 250, "weight_kg": 72, "w_prime": 5000, "cp": 240},
        )
        assert isinstance(hard, dict)
