"""Port of tests/integration/test_v500_thermal.py for coverage."""

from __future__ import annotations

import random

import pytest

from engines.recovery.thermal_engine import (
    ThermalSessionReport,
    analyze_heat_acclimation,
    analyze_thermal_session,
)


@pytest.fixture(autouse=True)
def _seed() -> None:
    random.seed(42)


class TestThermalPort:
    def test_no_data_paths(self) -> None:
        empty = analyze_thermal_session(
            core_temp_stream=[float("nan")] * 3600,
            power_stream=[200.0] * 3600,
        )
        assert empty.data_quality == "no_data"

        short = analyze_thermal_session(
            core_temp_stream=[37.0] * 100,
            power_stream=[200.0] * 100,
        )
        assert short.data_quality == "no_data"

    def test_endurance_progressive_heating(self) -> None:
        n = 5400
        core: list[float] = []
        power: list[float] = []
        hr: list[float] = []
        for i in range(n):
            t_min = i / 60.0
            ct = 37.2 + (38.8 - 37.2) * (t_min / 90.0) + random.gauss(0, 0.05)
            core.append(ct)
            pw = 200 - max(0, (t_min - 60)) * 0.5 + random.gauss(0, 8)
            power.append(max(60, pw))
            hr.append(130 + (ct - 37.2) * 9 + max(0, t_min - 60) * 0.15 + random.gauss(0, 2))

        report = analyze_thermal_session(core, power, hr_stream=hr, ftp=250)
        assert report.data_quality in {"good", "partial"}
        assert report.thermal_rise_rate > 0
        assert report.cardiac_drift_total_bpm > 0
        assert report.time_in_zone_s is not None
        assert report.eta_correction_factor <= 1.0

    def test_hot_and_cool_sessions(self) -> None:
        n = 3600
        core_hot = [38.5 + (i / n) * 1.5 + random.gauss(0, 0.05) for i in range(n)]
        power_hot = [220 - max(0, (i / 60 - 30)) * 2 + random.gauss(0, 10) for i in range(n)]
        hr_hot = [150 + (core_hot[i] - 38.5) * 10 for i in range(n)]
        hot = analyze_thermal_session(core_hot, power_hot, hr_stream=hr_hot)
        assert hot.core_temp_peak > 39.5
        assert hot.time_in_zone_s["danger_above_39.5"] > 0

        cool = analyze_thermal_session(
            [37.1 + random.gauss(0, 0.03) for _ in range(3600)],
            [180.0] * 3600,
            hr_stream=[125.0] * 3600,
        )
        assert cool.data_quality in {"good", "partial", "limited"}
        assert cool.core_temp_peak < 38.0

    def test_heat_acclimation(self) -> None:
        sessions = [
            ThermalSessionReport(
                data_quality="good",
                n_valid_samples=3000,
                n_total_samples=3600,
                thermal_rise_rate=0.025 - i * 0.002,
                heat_tolerance_threshold=38.5 + i * 0.1,
            )
            for i in range(9)
        ]
        trend = analyze_heat_acclimation(sessions)
        assert trend.n_sessions == 9
        assert trend.trend == "acclimating"
        assert trend.delta_rise_rate < 0

        short = analyze_heat_acclimation(sessions[:2])
        assert short.trend is None
