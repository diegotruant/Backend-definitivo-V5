from __future__ import annotations

import numpy as np

from engines.core.athlete_context import AthleteContext
from engines.io.activity_intelligence import build_activity_intelligence
from engines.io.fit_parser import ActivityStreamEnhanced
from engines.io.workout_summary import build_workout_summary


def _stream(n: int = 3600) -> ActivityStreamEnhanced:
    s = ActivityStreamEnhanced(n_samples=n, sport="cycling", total_elapsed_s=float(n))
    s.elapsed_s = np.arange(n, dtype=np.float32)
    s.power = np.full(n, 220.0, dtype=np.float32)
    s.heart_rate = np.linspace(132.0, 154.0, n, dtype=np.float32)
    s.core_body_temp = np.linspace(37.2, 39.1, n, dtype=np.float32)
    s.skin_temp = np.linspace(32.0, 34.2, n, dtype=np.float32)
    s.ambient_temp = np.full(n, 30.5, dtype=np.float32)
    s.has_core_sensor = True
    return s


def test_core_temperature_reaches_summary_and_intelligence() -> None:
    s = _stream()
    summary = build_workout_summary(s, weight_kg=72.0, ftp=260.0, context=AthleteContext())
    intelligence = build_activity_intelligence(s, weight_kg=72.0, ftp=260.0)

    assert summary["sections"]["thermal"]["core_temp_peak"] >= 39.0
    assert summary["sections"]["cardiac"]["thermal_context"]["available"] is True
    assert summary["sections"]["thermal_adjusted_durability"]["available"] is True
    assert summary["headline"]["core_temp_peak_c"] >= 39.0
    assert intelligence["thermal_context"]["status"] == "success"
    assert intelligence["cardiac_decoupling"]["thermal_context"]["core_temp_peak_c"] >= 39.0
