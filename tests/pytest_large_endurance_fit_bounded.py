"""Regression tests for long endurance FIT/HRV processing bounds.

Endurance and ultra files are first-class inputs. The backend must preserve
long-duration power/endurance information while bounding high-cost HRV/DFA
window density so large FIT files do not time out the whole athlete report.
"""

from __future__ import annotations

import numpy as np

from api.services.ride_analytics_service import RideAnalyticsService
from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import ActivityStreamEnhanced
from engines.io.workout_summary import build_workout_summary


def _long_rr_stream(n: int = 21_600) -> ActivityStreamEnhanced:
    stream = ActivityStreamEnhanced(n_samples=n, sport="cycling", total_elapsed_s=float(n))
    stream.elapsed_s = np.arange(n, dtype=np.float32)
    # Long steady endurance with mild terrain-like modulation.
    stream.power = (210 + 35 * np.sin(np.arange(n) / 240.0)).astype(np.float32)
    stream.heart_rate = (132 + 8 * np.sin(np.arange(n) / 420.0)).astype(np.float32)
    stream.distance_m = np.linspace(0, 125_000, n, dtype=np.float32)
    stream.altitude_m = np.linspace(120, 1800, n, dtype=np.float32)
    stream.rr_intervals = [[800.0] for _ in range(n)]
    return stream


def test_workout_summary_bounds_hrv_even_when_step_is_explicit() -> None:
    stream = _long_rr_stream()

    summary = build_workout_summary(
        stream,
        weight_kg=72.0,
        ftp=260.0,
        context=AthleteContext(),
        hrv_step_seconds=10.0,
        hrv_max_windows=300,
    )

    assert summary["status"] == "success"
    hrv = summary["sections"]["hrv"]
    assert hrv["available"] is True
    assert hrv["adaptive_step_applied"] is True
    assert hrv["n_windows"] <= 305
    assert any("Long-endurance analysis is preserved" in warning for warning in summary["warnings"])
    # The endurance signal is not discarded just because HRV windows are thinned.
    assert summary["stream_metadata"]["duration_s"] == 21_600
    assert summary["sections"]["power"]["status"] == "success"


def test_ride_analytics_hrv_endpoint_service_bounds_long_rr_stream() -> None:
    stream = _long_rr_stream()
    result = RideAnalyticsService().hrv_analyze(
        stream,
        window_seconds=120,
        step_seconds=10.0,
        max_windows=250,
    )

    assert result["status"] == "success"
    assert result["adaptive_step_applied"] is True
    assert result["expected_windows_at_requested_step"] > 2_000
    assert result["n_windows"] <= 255
    assert result["step_seconds"] > 10.0
