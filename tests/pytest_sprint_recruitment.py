"""Recruitment-aware sprint peak analysis and VLamax decomposition."""

from __future__ import annotations

import numpy as np

from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.sprint_peak_analysis import analyze_sprint_power
from engines.performance.test_protocols import run_wingate_test


def _delayed_sprint_15s() -> list[float]:
    """Slow ramp: true peak after ~6 s (amateur-like recruitment)."""
    ramp = [300 + i * 70 for i in range(8)]  # 300..790 over 8 s
    hold = [800, 820, 815, 810, 780, 760, 740]
    return (ramp + hold)[:15]


def _early_sprint_15s() -> list[float]:
    """Explosive start: peak in first second."""
    return [950, 900, 860, 820, 800, 780, 760, 740, 720, 700, 680, 660, 640, 620, 600]


class TestSprintPeakAnalysis:
    def test_early_recruitment_profile(self) -> None:
        analysis = analyze_sprint_power(_early_sprint_15s())
        assert analysis is not None
        assert analysis.recruitment_profile == "early"
        assert analysis.t_p_peak_s <= 3.0
        assert analysis.neuromuscular_peak_w == analysis.peak_1s_w
        assert analysis.neuromuscular_peak_window_s == 1

    def test_delayed_recruitment_profile(self) -> None:
        power = _delayed_sprint_15s()
        analysis = analyze_sprint_power(power)
        assert analysis is not None
        assert analysis.recruitment_profile == "delayed"
        assert analysis.t_p_peak_s > 3.0
        assert analysis.neuromuscular_peak_w >= analysis.peak_1s_w
        assert analysis.peak_3s_w > 0

    def test_wingate_payload_includes_sprint_peak_contract(self) -> None:
        out = run_wingate_test(
            {
                "test_type": "wingate",
                "athlete": {"weight_kg": 72},
                "test_data": {"duration_s": 15, "power_stream": _delayed_sprint_15s()},
            }
        )
        assert out["status"] == "success"
        contract = out["sprint_peak_contract"]
        assert contract["recruitment_profile"] == "delayed"
        assert "t_p_peak_s" in contract
        assert out["neuromuscular_peak_w"] == contract["neuromuscular_peak_w"]


class TestVlamaxRecruitmentAware:
    def test_delayed_sprint_uses_neuromuscular_peak_in_output(self) -> None:
        power = _delayed_sprint_15s()
        analysis = analyze_sprint_power(power)
        assert analysis is not None
        profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
        out = profiler.vlamax_from_sprint(
            analysis.peak_1s_w,
            float(np.mean(power)),
            sprint_duration_s=len(power),
            power=power,
        )
        assert out["status"] == "success"
        assert out["inputs"]["neuromuscular_peak_w"] == analysis.neuromuscular_peak_w
        assert out["sprint_peak_contract"]["recruitment_profile"] == "delayed"
        assert "delayed_motor_recruitment" in out.get("quality_flags", [])

    def test_explicit_delayed_peaks_match_power_series_path(self) -> None:
        power = _delayed_sprint_15s()
        analysis = analyze_sprint_power(power)
        assert analysis is not None
        profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
        from_series = profiler.vlamax_from_sprint(
            analysis.peak_1s_w,
            float(np.mean(power)),
            sprint_duration_s=len(power),
            power=power,
        )
        from_fields = profiler.vlamax_from_sprint(
            analysis.peak_1s_w,
            float(np.mean(power)),
            sprint_duration_s=len(power),
            t_p_peak_s=analysis.t_p_peak_s,
            peak_3s_w=analysis.peak_3s_w,
            peak_5s_w=analysis.peak_5s_w,
        )
        assert from_series["status"] == from_fields["status"] == "success"
        assert from_series["vlamax_mmol_l_s"] == from_fields["vlamax_mmol_l_s"]
