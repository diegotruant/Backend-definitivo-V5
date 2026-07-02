"""Regression tests for long endurance FIT/HRV processing bounds.

Endurance and ultra files are first-class inputs. The backend must preserve all
RR data and long-duration power/endurance information while bounding only the
high-cost DFA-alpha1 window placement density.
"""

from __future__ import annotations

import numpy as np

from api.services.ride_analytics_service import RideAnalyticsService
from engines.io.fit_parser import ActivityStreamEnhanced
from engines.recovery.hrv_endurance_schedule import plan_endurance_hrv_schedule


def _long_rr_stream(n: int = 21_600) -> ActivityStreamEnhanced:
    stream = ActivityStreamEnhanced(n_samples=n, sport="cycling", total_elapsed_s=float(n))
    stream.elapsed_s = np.arange(n, dtype=np.float32)
    stream.power = (210 + 35 * np.sin(np.arange(n) / 240.0)).astype(np.float32)
    stream.heart_rate = (132 + 8 * np.sin(np.arange(n) / 420.0)).astype(np.float32)
    stream.distance_m = np.linspace(0, 125_000, n, dtype=np.float32)
    stream.altitude_m = np.linspace(120, 1800, n, dtype=np.float32)
    stream.rr_intervals = [[float(800 + 35 * np.sin(i / 17.0) + 12 * np.sin(i / 5.0))] for i in range(n)]
    return stream


def test_endurance_hrv_schedule_is_dense_first_hour_then_sparse_decay() -> None:
    schedule = plan_endurance_hrv_schedule(
        duration_s=21_600,
        window_seconds=120,
        requested_step_seconds=10,
        max_windows=500,
    )

    assert schedule["mode"] == "two_phase_endurance"
    assert schedule["dense_until_seconds"] == 3600.0
    assert schedule["dense_step_seconds"] <= 12.0
    assert schedule["sparse_step_seconds"] >= 60.0
    assert schedule["sparse_step_seconds"] > schedule["dense_step_seconds"]


def test_ride_analytics_hrv_service_uses_two_phase_schedule_with_explicit_step() -> None:
    stream = _long_rr_stream()
    result = RideAnalyticsService().hrv_analyze(
        stream,
        window_seconds=120,
        step_seconds=10.0,
        max_windows=500,
    )

    assert result["status"] == "success"
    assert result["schedule_mode"] == "two_phase_endurance"
    assert result["adaptive_step_applied"] is True
    assert result["expected_windows_at_requested_step"] > 2_000
    assert result["n_windows"] <= 505
    assert result["dense_step_seconds"] <= 12.0
    assert result["sparse_step_seconds"] > result["dense_step_seconds"]


def test_session_router_long_endurance_uses_two_phase_hrv() -> None:
    from engines.io.session_router import route_and_run

    stream = _long_rr_stream()
    power = [float(stream.power[i] or 0) for i in range(stream.n_samples)]
    rr = [
        {"elapsed": float(stream.elapsed_s[i]), "rr": stream.rr_intervals[i]}
        for i in range(stream.n_samples)
        if stream.rr_intervals[i]
    ]
    out = route_and_run(
        power,
        rr_samples=rr,
        elapsed_s=[float(stream.elapsed_s[i]) for i in range(stream.n_samples)],
        weight_kg=72.0,
        filename="endurance_long_ride.fit",
        ftp=260.0,
        hrv_max_windows=500,
    )

    assert out["routing"]["route"] == "ride_monitoring"
    durability = out["results"]["hrv_durability"]
    assert durability["status"] == "ok"
    assert durability["schedule_mode"] == "two_phase_endurance"
    assert durability["n_windows"] <= 505
    assert durability["sparse_step_seconds"] > durability["dense_step_seconds"]
