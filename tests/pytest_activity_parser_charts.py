from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from engines.io.activity_charts import chart_power, chart_elevation, chart_power_phase, chart_platform_offset
from engines.io.fit_parser import parse_fit_records_enhanced


def _records(n: int, power: list[float] | None = None):
    start = datetime(2026, 1, 1, 8, 0, 0)
    power = power or [200.0] * n
    out = []
    for i in range(n):
        out.append(
            {
                "timestamp": start + timedelta(seconds=i),
                "power": power[i],
                "enhanced_altitude": 100.0 + i * 0.5,
                "altitude": 50.0,  # should be ignored when enhanced_altitude exists
                "speed": 9.0,
                "heart_rate": 140,
                "left_power_phase": 30.0 + i * 0.1,
                "left_pco": -2.0,
                "left_pedal_smoothness": 22.0,
                "left_torque_effectiveness": 70.0,
                "respiration_rate": 31.0,
            }
        )
    return out, {"sport": "cycling", "start_time": start, "total_elapsed_time": n}


def test_chart_power_uses_correct_np_and_vi_without_changing_chart_contract():
    # 30s @ 100 W + 30s @ 300 W. Correct NP uses 30s rolling averages,
    # not raw fourth-power average. VI is NP / arithmetic average power.
    records, session = _records(60, [100.0] * 30 + [300.0] * 30)
    stream = parse_fit_records_enhanced(records, session_dict=session)
    chart = chart_power(stream)

    y = np.asarray([100.0] * 30 + [300.0] * 30)
    rolling_30s = np.convolve(y, np.ones(30) / 30, mode="valid")
    expected_np = float(np.mean(rolling_30s ** 4) ** 0.25)
    expected_vi = expected_np / float(np.mean(y))

    assert chart["x_axis"]["data"]
    assert chart["summary"]["normalized_power_w"] == round(expected_np, 1)
    assert chart["summary"]["np_w"] == round(expected_np, 1)
    assert chart["summary"]["variability_index"] == round(expected_vi, 3)
    assert chart["summary"]["vi"] == round(expected_vi, 3)
    assert chart["summary"]["np_method"] == "30s_rolling_fourth_power"


def test_fit_parser_exposes_enhanced_altitude_and_cycling_dynamics_for_charts():
    records, session = _records(10)
    stream = parse_fit_records_enhanced(records, session_dict=session)

    assert np.isclose(stream.altitude_m[0], 100.0)
    assert np.isclose(stream.altitude[0], 100.0)  # compatibility alias
    assert np.isclose(stream.time[3], 3.0)
    assert np.isclose(stream.left_power_phase[0], 30.0)
    assert np.isclose(stream.left_pco[0], -2.0)
    assert np.isclose(stream.respiration_rate[0], 31.0)

    assert chart_elevation(stream).get("available", True) is True
    assert chart_power_phase(stream).get("available", True) is True
    assert chart_platform_offset(stream).get("available", True) is True
