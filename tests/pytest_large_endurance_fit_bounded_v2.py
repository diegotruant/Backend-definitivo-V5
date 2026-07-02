from __future__ import annotations

import numpy as np

from api.services.ride_analytics_service import RideAnalyticsService
from engines.io.fit_parser import ActivityStreamEnhanced


def test_ride_analytics_hrv_service_bounds_long_rr_stream_with_explicit_step() -> None:
    n = 21_600
    stream = ActivityStreamEnhanced(n_samples=n, sport="cycling", total_elapsed_s=float(n))
    stream.elapsed_s = np.arange(n, dtype=np.float32)
    stream.power = (210 + 35 * np.sin(np.arange(n) / 240.0)).astype(np.float32)
    stream.heart_rate = (132 + 8 * np.sin(np.arange(n) / 420.0)).astype(np.float32)
    stream.rr_intervals = [[800.0] for _ in range(n)]

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
