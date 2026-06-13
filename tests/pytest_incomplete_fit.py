"""
Regression tests for robust handling of incomplete / degenerate FIT data.

These guard against crashes and schema inconsistencies when a real-world FIT
file is missing channels (no power, no HR), has degenerate timestamps (all
equal, non-monotonic, NaN), or contains too few samples. The pipeline must
always return status="success" with every section carrying a coherent `status`
field — never raise, never emit a section without a status.
"""

from __future__ import annotations

import numpy as np

from engines.io.fit_parser import ActivityStreamEnhanced
from engines.io.workout_summary import build_workout_summary


def _make_stream(n: int = 600) -> ActivityStreamEnhanced:
    """A minimal but complete synthetic stream: 10 min at ~200 W, 90 bpm-ish."""
    s = ActivityStreamEnhanced(n_samples=n)
    s.elapsed_s = np.arange(n, dtype=np.float32)
    s.power = np.full(n, 200.0, dtype=np.float32)
    s.heart_rate = np.full(n, 140.0, dtype=np.float32)
    s.cadence = np.full(n, 85.0, dtype=np.float32)
    s.speed_mps = np.full(n, 8.0, dtype=np.float32)
    return s


def _all_sections_have_status(report: dict) -> bool:
    for sec in report.get("sections", {}).values():
        if isinstance(sec, dict) and sec.get("status") in (None, "?"):
            return False
    return True


def test_complete_stream_succeeds() -> None:
    r = build_workout_summary(_make_stream(), weight_kg=75.0, ftp=250.0)
    assert r["status"] == "success"
    assert _all_sections_have_status(r)
    assert "statistics_page" in r
    assert r["sections"]["statistics"]["status"] == "success"


def test_no_power_does_not_crash() -> None:
    s = _make_stream()
    s.power = np.zeros(s.n_samples, dtype=np.float32)
    r = build_workout_summary(s, weight_kg=75.0, ftp=250.0)
    assert r["status"] == "success"
    assert r["sections"]["power"]["status"] == "unavailable"
    assert _all_sections_have_status(r)


def test_no_hr_does_not_crash() -> None:
    s = _make_stream()
    s.heart_rate = np.zeros(s.n_samples, dtype=np.float32)
    r = build_workout_summary(s, weight_kg=75.0, ftp=250.0)
    assert r["status"] == "success"
    assert r["sections"]["power"]["status"] == "success"
    assert _all_sections_have_status(r)


def test_no_power_no_hr_does_not_crash() -> None:
    s = _make_stream()
    s.power = np.zeros(s.n_samples, dtype=np.float32)
    s.heart_rate = np.zeros(s.n_samples, dtype=np.float32)
    r = build_workout_summary(s, weight_kg=75.0, ftp=250.0)
    assert r["status"] == "success"
    assert _all_sections_have_status(r)


def test_degenerate_timestamps_all_zero() -> None:
    s = _make_stream()
    s.elapsed_s = np.zeros(s.n_samples, dtype=np.float32)
    r = build_workout_summary(s, weight_kg=75.0, ftp=250.0)
    assert r["status"] == "success"
    assert _all_sections_have_status(r)


def test_degenerate_timestamps_constant() -> None:
    s = _make_stream()
    s.elapsed_s = np.full(s.n_samples, 5.0, dtype=np.float32)
    r = build_workout_summary(s, weight_kg=75.0, ftp=250.0)
    assert r["status"] == "success"


def test_degenerate_timestamps_nan() -> None:
    s = _make_stream()
    s.elapsed_s = np.full(s.n_samples, np.nan, dtype=np.float32)
    r = build_workout_summary(s, weight_kg=75.0, ftp=250.0)
    assert r["status"] == "success"


def test_non_monotonic_timestamps() -> None:
    s = _make_stream()
    s.elapsed_s = np.arange(s.n_samples, 0, -1, dtype=np.float32)
    r = build_workout_summary(s, weight_kg=75.0, ftp=250.0)
    assert r["status"] == "success"


def test_single_sample_does_not_crash() -> None:
    s = _make_stream(n=1)
    r = build_workout_summary(s, weight_kg=75.0, ftp=250.0)
    assert r["status"] == "success"
    assert _all_sections_have_status(r)


def test_no_start_time() -> None:
    s = _make_stream()
    s.start_time = None
    r = build_workout_summary(s, weight_kg=75.0, ftp=250.0)
    assert r["status"] == "success"
    assert r["stream_metadata"]["start_time"] is None


def test_power_all_nan() -> None:
    s = _make_stream()
    s.power = np.full(s.n_samples, np.nan, dtype=np.float32)
    r = build_workout_summary(s, weight_kg=75.0, ftp=250.0)
    assert r["status"] == "success"
    assert _all_sections_have_status(r)


def test_ftp_not_provided_does_not_crash() -> None:
    # With FTP not provided the engine attempts estimation from the MMP curve.
    # On a flat power profile estimation may legitimately fail; either outcome
    # is acceptable as long as the pipeline returns cleanly with a status.
    s = _make_stream()
    r = build_workout_summary(s, weight_kg=75.0, ftp=None)
    assert r["status"] == "success"
    assert r["sections"]["power"]["status"] in ("success", "unavailable")
    assert _all_sections_have_status(r)
