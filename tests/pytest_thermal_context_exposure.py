from __future__ import annotations

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.io import workout_summary as ws
from engines.io.activity_intelligence import build_activity_intelligence
from engines.io.fit_parser import ActivityStreamEnhanced
from engines.io.workout_summary import build_workout_summary
from engines.recovery import hrv_engine


class _ThermalReport:
    def to_dict(self):
        return {
            "core_temp_peak": 37.8,
            "core_temp_mean": 37.4,
            "core_temp_start": 37.1,
            "core_temp_end": 37.8,
            "thermal_rise_rate": 0.02,
            "thermal_drift_pct": 10.0,
            "cardiac_drift_total_bpm": 8.0,
            "cardiac_drift_thermal_bpm": 2.0,
            "cardiac_drift_fatigue_bpm": 4.0,
            "power_decay_raw_pct": 6.0,
            "power_decay_thermal_adjusted_pct": 4.0,
            "heat_tolerance_threshold": 38.8,
            "heat_tolerance_classification": "stable",
            "eta_correction_factor": 0.8,
        }


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


def test_workout_summary_argument_and_stream_helpers() -> None:
    assert ws._argument(("a", "b"), {}, 1, "x") == "b"
    assert ws._argument((), {"x": 3}, 1, "x") == 3
    assert ws._argument((), {}, 1, "x", default="fallback") == "fallback"

    class Dirty:
        n_samples = 5
        values = ["1", "bad", np.nan, None, 4]
        core_body_temp = [29.0, 37.0]

    assert ws._stream_series(Dirty(), "missing", 5) == []
    assert ws._stream_series(Dirty(), "values", 5) == [1.0, None, None, None, 4.0]
    assert ws._has_core_temperature(Dirty(), 2) is True


def test_thermal_report_and_attach_edge_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ws._build_thermal_report(None, ftp=260.0) is None
    assert ws._build_thermal_report(ActivityStreamEnhanced(n_samples=0), ftp=260.0) is None

    no_core = ActivityStreamEnhanced(n_samples=3, sport="cycling", total_elapsed_s=3.0)
    no_core.core_body_temp = np.array([np.nan, np.nan, np.nan], dtype=np.float32)
    assert ws._build_thermal_report(no_core, ftp=260.0) is None

    poor = ActivityStreamEnhanced(n_samples=3, sport="cycling", total_elapsed_s=3.0)
    poor.core_body_temp = np.array([37.0, 37.1, 37.2], dtype=np.float32)
    assert ws._build_thermal_report(poor, ftp=260.0) is None

    s = _stream(n=60)
    monkeypatch.setattr(ws, "analyze_thermal_session", lambda **_: _ThermalReport())
    report = ws._build_thermal_report(s, ftp=260.0)
    assert report["core_temp_peak"] == 37.8

    out = {"sections": {"cardiac": {}}, "warnings": ["Core-temperature data already present"]}
    ws._attach_thermal_context(out, s, ftp=260.0)
    assert out["sections"]["cardiac"]["thermal_context"]["available"] is True
    assert out["sections"]["thermal_adjusted_durability"]["interpretation"] == "fatigue_residual_dominant"
    assert len(out["warnings"]) == 1

    monkeypatch.setattr(ws, "_build_thermal_report", lambda *_args, **_kwargs: {"data_quality": "no_data"})
    out = {}
    ws._attach_thermal_context(out, s, ftp=260.0)
    assert out["sections"]["thermal"]["data_quality"] == "no_data"


def test_thermal_interpretation_variants() -> None:
    heat = ws._thermal_interpretation({"core_temp_peak": 39.0, "thermal_drift_pct": 5.0})
    assert heat["interpretation"] == "heat_strain_dominant"

    drift = ws._thermal_interpretation({"core_temp_peak": 37.5, "thermal_drift_pct": 60.0})
    assert drift["heat_strain_compatible"] is True

    fatigue = ws._thermal_interpretation({"core_temp_peak": 37.5, "cardiac_drift_fatigue_bpm": 4.0})
    assert fatigue["interpretation"] == "fatigue_residual_dominant"

    neutral = ws._thermal_interpretation({"core_temp_peak": 37.5, "cardiac_drift_fatigue_bpm": 1.0})
    assert neutral["interpretation"] == "thermal_context_available"


def test_build_summary_adds_adaptive_schedule_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_legacy(*_args, **_kwargs):
        hrv_engine.analyze_rr_stream([{"rr": [800.0]}], window_seconds=120, step_seconds=10.0, context=None)
        return {
            "status": "success",
            "sections": {"hrv": {"available": True, "timeline": []}},
            "warnings": [],
        }

    def fake_schedule(*_args, **_kwargs):
        return [], {
            "mode": "single_phase",
            "dense_step_seconds": 20.0,
            "sparse_step_seconds": None,
            "dense_until_seconds": 3600.0,
            "adaptive_step_applied": True,
        }

    monkeypatch.setattr(ws, "_legacy_build_workout_summary", fake_legacy)
    monkeypatch.setattr(ws, "analyze_rr_stream_endurance_scheduled", fake_schedule)
    monkeypatch.setattr(ws, "_attach_thermal_context", lambda *_args, **_kwargs: None)

    summary = build_workout_summary(_stream(n=10), weight_kg=72.0, ftp=260.0)
    hrv = summary["sections"]["hrv"]
    assert hrv["adaptive_step_applied"] is True
    assert any("HRV/DFA-alpha1 step increased" in warning for warning in summary["warnings"])
    assert any("two-phase endurance schedule" in warning for warning in summary["warnings"])
