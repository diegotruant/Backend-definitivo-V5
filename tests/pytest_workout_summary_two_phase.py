from __future__ import annotations

import numpy as np

from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import ActivityStreamEnhanced
from engines.io.workout_summary import build_workout_summary


def _long_rr_stream(n: int = 21_600) -> ActivityStreamEnhanced:
    stream = ActivityStreamEnhanced(n_samples=n, sport="cycling", total_elapsed_s=float(n))
    stream.elapsed_s = np.arange(n, dtype=np.float32)
    stream.power = (210 + 35 * np.sin(np.arange(n) / 240.0)).astype(np.float32)
    stream.heart_rate = (132 + 8 * np.sin(np.arange(n) / 420.0)).astype(np.float32)
    stream.distance_m = np.linspace(0, 125_000, n, dtype=np.float32)
    stream.altitude_m = np.linspace(120, 1800, n, dtype=np.float32)
    stream.rr_intervals = [[float(800 + 35 * np.sin(i / 17.0) + 12 * np.sin(i / 5.0))] for i in range(n)]
    return stream


def test_workout_summary_uses_two_phase_hrv_without_truncating_endurance_signal() -> None:
    summary = build_workout_summary(
        _long_rr_stream(),
        weight_kg=72.0,
        ftp=260.0,
        context=AthleteContext(),
        hrv_step_seconds=10.0,
        hrv_max_windows=500,
    )

    assert summary["status"] == "success"
    hrv = summary["sections"]["hrv"]
    assert hrv["available"] is True
    assert hrv["schedule_mode"] == "two_phase_endurance"
    assert hrv["dense_step_seconds"] <= 12.0
    assert hrv["sparse_step_seconds"] > hrv["dense_step_seconds"]
    assert hrv["n_windows"] <= 505
    phases = {row.get("metadata", {}).get("schedule_phase") for row in hrv["timeline"]}
    assert "dense_first_hour" in phases
    assert "sparse_endurance_decay" in phases
    assert any("All RR beats are preserved" in warning for warning in summary["warnings"])
    assert summary["stream_metadata"]["duration_s"] == 21_600
    assert summary["sections"]["power"]["status"] == "success"
