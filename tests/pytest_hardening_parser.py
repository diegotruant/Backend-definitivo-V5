from __future__ import annotations

from datetime import datetime, timedelta
import tempfile

import numpy as np
import pytest

from engines.io.activity_charts import (
    chart_elevation,
    chart_platform_offset,
    chart_power,
    chart_power_phase,
    chart_respiration,
)
from engines.io.fit_parser import (
    FITPARSE_AVAILABLE,
    FitFileError,
    QUALITY_FORWARD_FILLED,
    parse_fit_file_enhanced,
    parse_fit_records_enhanced,
)
from tests._hardening_utils import assert_json_safe, deadline


@pytest.mark.hardening
def test_parser_sparse_sensor_records_cycling_dynamics_and_gaps_do_not_crash() -> None:
    start = datetime(2026, 1, 1, 8, 0, 0)
    records = []
    for i in range(900):
        # Leave deterministic sensor dropouts and missing record timestamps in
        # place: parser should normalize the 1 Hz stream and mark quality flags.
        rec = {
            "timestamp": start + timedelta(seconds=i),
            "power": 240 if i % 97 else 0,
            "heart_rate": 145 if i % 83 else 0,
            "cadence": 88 if i % 71 else None,
            "enhanced_speed": 9.5,
            "enhanced_altitude": 220 + 0.02 * i,
            "distance": i * 9.5,
            "left_power_phase": {"value": 32.0 + (i % 20)},
            "right_power_phase": [210.0 + (i % 20)],
            "left_pco": -3.0,
            "right_pco": 4.0,
            "left_pedal_smoothness": 24.0,
            "right_torque_effectiveness": 72.0,
            "respiration_rate": 28.0,
            "cadence_position": "standing" if i % 120 < 10 else "seated",
        }
        if i % 211 == 0:
            rec.pop("timestamp")
        records.append(rec)

    with deadline(2.0):
        stream = parse_fit_records_enhanced(records, {"start_time": start, "total_elapsed_time": 900})

    assert stream.n_samples == 900
    assert stream.has_power
    assert stream.has_heart_rate
    assert stream.has_cycling_dynamics
    assert stream.has_respiration
    assert np.isfinite(stream.altitude).any()
    assert np.isfinite(stream.left_power_phase).any()
    assert np.isfinite(stream.right_pco).any()
    assert np.any(stream.quality_hr == QUALITY_FORWARD_FILLED) or stream.gap_summary["heart_rate"]["n_gaps"] > 0

    # Chart builders should never leak NaN/Inf or crash on this mixed stream.
    for chart in (chart_power(stream), chart_elevation(stream), chart_power_phase(stream), chart_platform_offset(stream), chart_respiration(stream)):
        assert chart.get("available", True) is not False
        assert_json_safe(chart)


@pytest.mark.hardening
def test_parser_returns_typed_error_for_corrupt_fit_bytes_when_backend_is_available() -> None:
    if not FITPARSE_AVAILABLE:
        pytest.skip("no FIT parser backend is installed in this environment")
    with tempfile.NamedTemporaryFile(suffix=".fit") as tmp:
        tmp.write(b"not a fit file" * 100)
        tmp.flush()
        with deadline(1.0), pytest.raises(FitFileError) as exc:
            parse_fit_file_enhanced(tmp.name)
    assert exc.value.reason in {"INVALID_HEADER", "MALFORMED_RECORDS", "UNKNOWN"}

@pytest.mark.hardening
@pytest.mark.stress
def test_large_rr_workout_summary_adapts_hrv_window_count_and_finishes() -> None:
    from engines.io.fit_parser import ActivityStreamEnhanced
    from engines.io.workout_summary import build_workout_summary
    from engines.core.athlete_context import AthleteContext

    n = 13_800  # close to the real large FIT that exposed the issue
    stream = ActivityStreamEnhanced(n_samples=n, sport="cycling", total_elapsed_s=float(n))
    stream.elapsed_s = np.arange(n, dtype=np.float32)
    stream.power = (205 + 35 * np.sin(np.arange(n) / 180.0)).astype(np.float32)
    stream.heart_rate = (138 + 10 * np.sin(np.arange(n) / 300.0)).astype(np.float32)
    stream.distance_m = np.linspace(0, 55_000, n, dtype=np.float32)
    stream.altitude_m = np.linspace(100, 1600, n, dtype=np.float32)
    # One RR beat per second is enough to trigger the HRV path and create many
    # potential DFA windows without making the synthetic fixture huge.
    stream.rr_intervals = [[800.0] for _ in range(n)]

    with deadline(18.0):
        summary = build_workout_summary(
            stream,
            weight_kg=70.0,
            ftp=260.0,
            context=AthleteContext(),
            hrv_max_windows=350,
        )
    assert summary["status"] == "success"
    hrv = summary["sections"]["hrv"]
    assert hrv["status"] == "success"
    assert hrv["adaptive_step_applied"] is True
    assert hrv["n_windows"] <= 360
    assert any(
        "All RR beats are preserved" in w or "HRV/DFA-alpha1 step increased" in w
        for w in summary["warnings"]
    )
    assert_json_safe(summary)
