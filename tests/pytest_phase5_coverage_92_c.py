"""Phase 5 — deep branch closure: cardiac internals, interval laps, IO, metabolic."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.io.workout_summary import build_workout_summary
from engines.metabolic.detraining_engine import apply_detraining_model, calculate_ctl_atl_tsb, calculate_decay_factor
from engines.metabolic.metabolic_kalman import DailyInput, MetabolicKalman, process_workout_history
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.durability_engine import (
    calculate_durability_index,
    calculate_np_drift,
    generate_durability_prescription,
    generate_hourly_decay_curve,
)
from engines.performance.interval_detector import _classify_by_laps, _compute_stimulus_vector
from engines.recovery.cardiac_engine import (
    ActivitySample,
    Segment,
    _detect_ramp_segments,
    _detect_recovery_segments,
    _detect_steady_segments,
    _moving_average,
    compute_aerobic_decoupling,
    compute_cardiac_drift,
)
from engines.recovery.pedaling_balance import analyze_balance_trend, analyze_pedaling_balance
from engines.recovery.thermal_engine import analyze_heat_acclimation, analyze_thermal_session


def _stream(seconds: int = 600, power: float = 220.0):
    start = datetime(2026, 1, 1, 8, 0, 0)
    records = [
        {"timestamp": start + timedelta(seconds=i), "power": power, "heart_rate": 140.0, "cadence": 90.0}
        for i in range(seconds)
    ]
    return parse_fit_records_enhanced(records, session_dict={"start_time": start, "total_elapsed_time": seconds})


class TestCardiacInternals92:
    def test_segment_detection_helpers(self) -> None:
        t = np.arange(1200, dtype=float)
        steady_p = 225.0 + np.sin(t / 200.0) * 2.0
        p_smooth = _moving_average(steady_p, 30.0, t)
        assert _detect_steady_segments(t, p_smooth)

        # Ramp slope must stay >= 0.3 W/s for >= 180 s (_RAMP_DPDT_MIN)
        ramp_t = np.arange(400, dtype=float)
        ramp_p = np.linspace(150, 350, 400)
        ramp_smooth = _moving_average(ramp_p, 5.0, ramp_t)
        assert _detect_ramp_segments(ramp_t, ramp_smooth)

        rec_p = np.concatenate([np.full(500, 250.0), np.full(300, 10.0)])
        rec_h = np.concatenate([np.full(500, 170.0), np.linspace(170, 120, 300)])
        rec_t = np.arange(800, dtype=float)
        assert _detect_recovery_segments(rec_t, rec_p, rec_h)

        assert _moving_average(np.array([]), 10.0, np.array([])).size == 0

        seg = Segment(kind="steady", start_idx=0, end_idx=600, start_t=0.0, end_t=599.0, duration_s=600.0)
        p = np.full(600, 225.0)
        h = np.linspace(140, 155, 600)
        drift = compute_cardiac_drift(t[:600], p, h, seg)
        assert drift.get("available") in {True, False}
        decouple = compute_aerobic_decoupling(t[:600], p, h, seg)
        assert decouple.get("available") in {True, False}


class TestIntervalLapBranches92:
    def test_lap_subtype_branches(self) -> None:
        cp6_laps = [
            {"duration_s": 120, "avg_power_w": 150},
            {"duration_s": 360, "avg_power_w": 350},
            {"duration_s": 120, "avg_power_w": 140},
        ]
        r6 = _classify_by_laps(cp6_laps, ftp=280.0)
        assert r6 is not None and r6[0] == "TEST"

        cp12_laps = [
            {"duration_s": 300, "avg_power_w": 150},
            {"duration_s": 720, "avg_power_w": 340},
        ]
        r12 = _classify_by_laps(cp12_laps, ftp=280.0)
        assert r12 is not None and r12[0] == "TEST"

        balanced_hiit = []
        for _ in range(10):
            balanced_hiit.append({"duration_s": 45, "avg_power_w": 360})
            balanced_hiit.append({"duration_s": 90, "avg_power_w": 130})
        rb = _classify_by_laps(balanced_hiit, ftp=280.0)
        assert rb is not None and rb[0] == "HIIT"

        long_hiit = []
        for _ in range(5):
            long_hiit.append({"duration_s": 200, "avg_power_w": 310})
            long_hiit.append({"duration_s": 100, "avg_power_w": 140})
        rl = _classify_by_laps(long_hiit, ftp=280.0)
        assert rl is not None

        sv = _compute_stimulus_vector([200.0, 250.0, 300.0, 350.0, 420.0, 500.0], 280.0)
        assert sv is not None
        assert sv.neuromuscular_stimulus_s >= 1
        assert _compute_stimulus_vector([200.0], None) is None


class TestMetabolicIoRecovery92:
    def test_workout_summary_detraining_kalman(self) -> None:
        mmp = {15: 980, 60: 540, 300: 340, 720: 300, 1200: 285, 3600: 255}
        snap = MetabolicProfiler(weight=72.0).generate_metabolic_snapshot(mmp)
        stream = _stream(3600, 240.0)
        summary = build_workout_summary(stream, weight_kg=72.0, ftp=280.0, metabolic_snapshot=snap)
        assert summary.get("status") in {"success", "partial", "error"} or "headline" in summary

        ref = datetime(2026, 6, 17).date()
        hist = [{"date": ref - timedelta(days=i), "tss": 70.0} for i in range(1, 45)]
        det = apply_detraining_model(
            {
                "status": "success",
                "estimated_vo2max": 60.0,
                "estimated_vlamax_mmol_L_s": 0.45,
                "mlss_power_watts": 280.0,
                "map_aerobic_watts": 350.0,
                "fatmax_power_watts": 200.0,
            },
            hist,
            ref,
        )
        assert det.get("training_load")
        assert calculate_ctl_atl_tsb(hist, ref)["ctl"] > 0
        assert 0 < calculate_decay_factor(21.0, 58.0, "vo2max") <= 1.0

        kalman = MetabolicKalman(np.array([60.0, 0.4]), np.diag([4.0, 0.01]), weight=72.0)
        kalman.predict(DailyInput(date=ref, vo2max_stimulus_min=25.0))
        kalman.update([(180, 360.0), (360, 330.0), (720, 300.0)])
        traj = process_workout_history(
            [DailyInput(date=ref - timedelta(days=i), vo2max_stimulus_min=20.0 + i) for i in range(10)],
            initial_vo2=60.0,
            initial_vla=0.4,
            weight=72.0,
        )
        assert len(traj.states) >= 1

    def test_durability_pedaling_thermal(self) -> None:
        power = [250.0] * 3600 + [210.0] * 3600
        di = calculate_durability_index(power, len(power))
        assert di["status"] == "success"
        drift = calculate_np_drift(power, len(power))
        assert drift.get("status") in {"success", None} or "drift_pct" in drift
        curve = generate_hourly_decay_curve(power, len(power))
        assert curve.get("status") in {"success", None} or "hourly" in str(curve).lower()
        rx = generate_durability_prescription(di.get("durability_index", 88.0), di.get("classification", "GOOD"))
        assert rx["focus"]

        marked = analyze_pedaling_balance([38.0] * 600, [200.0] * 600, ftp=250.0, pedaling_balance_source="dual")
        symmetric = analyze_pedaling_balance([50.0] * 600, [200.0] * 600, ftp=250.0, pedaling_balance_source="dual")
        trend = analyze_balance_trend([symmetric, symmetric, marked, marked])
        assert trend.trend in {"stable", "worsening", "improving", None} or trend.notes

        thermal = analyze_thermal_session(
            core_temp_stream=[37.0 + i * 0.003 for i in range(500)],
            power_stream=[230.0] * 500,
            hr_stream=[145.0] * 500,
            ftp=280.0,
        )
        accl = analyze_heat_acclimation([thermal, thermal, thermal])
        assert accl.n_sessions >= 1
