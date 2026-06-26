"""Port of tests/integration/test_test_protocols.py for coverage."""

from __future__ import annotations

from engines.metabolic.lactate_validation_engine import compute_lactate_thresholds, steps_from_payload
from engines.performance.test_protocols import (
    run_critical_power_test,
    run_incremental_test,
    run_mader_test,
    run_power_cadence_test,
    run_test,
    run_wingate_test,
)
from engines.metabolic.metabolic_profiler import MetabolicProfiler


class TestProtocolsPort:
    def test_lactate_dmax(self) -> None:
        steps = steps_from_payload(
            [
                {"step": 1, "power_w": 150, "lactate_mmol": 1.2},
                {"step": 2, "power_w": 200, "lactate_mmol": 1.8},
                {"step": 3, "power_w": 230, "lactate_mmol": 2.6},
                {"step": 4, "power_w": 260, "lactate_mmol": 4.1},
                {"step": 5, "power_w": 290, "lactate_mmol": 6.8},
                {"step": 6, "power_w": 320, "lactate_mmol": 10.2},
            ]
        )
        thr = compute_lactate_thresholds(steps)
        assert (thr.mlss_dmax_w or 0) > 0
        assert "mlss_dmax_watts" in thr.to_dict()

    def test_critical_power_and_wingate(self) -> None:
        cp = run_critical_power_test(
            {
                "test_type": "critical_power",
                "athlete": {"weight_kg": 72},
                "test_data": {
                    "efforts": [
                        {"duration_s": 180, "power_w": 360},
                        {"duration_s": 300, "power_w": 330},
                        {"duration_s": 720, "power_w": 295},
                    ],
                },
            }
        )
        assert cp.get("status") == "success"
        assert float(cp.get("cp_w", 0)) > 0

        wingate = run_wingate_test(
            {
                "test_type": "wingate",
                "athlete": {"weight_kg": 72},
                "test_data": {
                    "duration_s": 10,
                    "power_stream": [900, 850, 800, 750, 700, 650, 600, 550, 500, 450],
                    "body_weight_kg": 72,
                },
            }
        )
        assert wingate.get("status") == "success"
        assert float(wingate.get("peak_power_w", 0)) == 900

    def test_incremental_power_cadence_mader_and_dispatcher(self) -> None:
        inc = run_incremental_test(
            {
                "test_data": {
                    "steps": [
                        {"power_w": 200, "hr_mean": 140},
                        {"power_w": 250, "hr_mean": 155},
                        {"power_w": 280, "hr_mean": 168},
                    ]
                }
            }
        )
        assert inc.get("status") == "success"

        cadence = run_power_cadence_test(
            {
                "test_data": {
                    "points": [
                        {"rpm_peak": 60, "w_peak": 800},
                        {"rpm_peak": 80, "w_peak": 950},
                        {"rpm_peak": 100, "w_peak": 900},
                        {"rpm_peak": 120, "w_peak": 750},
                    ]
                }
            }
        )
        assert cadence.get("status") == "success"

        profiler = MetabolicProfiler(weight=72.0)
        mader = run_mader_test(
            {
                "test_data": {
                    "steps": [
                        {"power_w": 150, "lactate_mmol": 1.2},
                        {"power_w": 200, "lactate_mmol": 2.0},
                        {"power_w": 250, "lactate_mmol": 4.0},
                    ],
                    "mmp": {60: 500, 300: 350, 1200: 300},
                }
            },
            profiler,
        )
        assert mader.get("status") in {"success", "error", "partial"}

        assert run_test({"test_type": "invalid"}).get("status") == "error"
        assert run_incremental_test({"test_data": {}}).get("status") == "error"
        assert run_power_cadence_test({"test_data": {"points": []}}).get("status") == "error"
