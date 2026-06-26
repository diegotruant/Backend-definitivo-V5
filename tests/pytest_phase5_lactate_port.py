"""Port of tests/integration/test_lactate_validation_engine.py for coverage."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from engines.core.athlete_context import AthleteContext
from engines.metabolic.lactate_validation_engine import (
    LactateStep,
    compute_lactate_thresholds,
    steps_from_payload,
    validate_model_against_lactate,
)
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.test_protocols import run_mader_test


class TestLactateValidationPort:
    def test_dmax_thresholds(self) -> None:
        steps = steps_from_payload([
            {"step": 1, "power_w": 150, "lactate_mmol": 1.2},
            {"step": 2, "power_w": 200, "lactate_mmol": 1.8},
            {"step": 3, "power_w": 230, "lactate_mmol": 2.6},
            {"step": 4, "power_w": 260, "lactate_mmol": 4.1},
            {"step": 5, "power_w": 290, "lactate_mmol": 6.8},
            {"step": 6, "power_w": 320, "lactate_mmol": 10.2},
        ])
        thr = compute_lactate_thresholds(steps)
        assert hasattr(thr, "mlss_dmax_w")
        assert 200 <= (thr.mlss_dmax_w or 0) <= 280
        assert thr.obla_4mmol_w is not None

    def test_insufficient_steps_and_full_validation(self) -> None:
        profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
        short = [LactateStep(power_w=200, lactate_mmol=2.0)] * 3
        err = validate_model_against_lactate(short, profiler, {1200: 280, 3600: 255})
        assert err.get("status") == "error"
        assert err.get("reason") == "insufficient_lactate_steps"

        mmp = {15: 980, 60: 540, 300: 340, 720: 300, 1200: 285, 3600: 255}
        steps = steps_from_payload([
            {"step": 1, "power_w": 150, "lactate_mmol": 1.2},
            {"step": 2, "power_w": 200, "lactate_mmol": 1.8},
            {"step": 3, "power_w": 230, "lactate_mmol": 2.6},
            {"step": 4, "power_w": 260, "lactate_mmol": 4.1},
            {"step": 5, "power_w": 290, "lactate_mmol": 6.8},
            {"step": 6, "power_w": 320, "lactate_mmol": 10.2},
        ])
        result = validate_model_against_lactate(steps, profiler, mmp)
        assert result.get("status") == "success"
        assert result.get("verdict")
        assert "mlss_dmax_watts" in (result.get("lactate_thresholds") or {})
        assert "api_contract" in result

    def test_run_mader_test_and_demo(self) -> None:
        profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
        envelope = {
            "test_type": "mader",
            "athlete": {"weight_kg": 72},
            "test_data": {
                "steps": [
                    {"step": 1, "power_w": 150, "lactate_mmol": 1.2},
                    {"step": 2, "power_w": 200, "lactate_mmol": 1.8},
                    {"step": 3, "power_w": 230, "lactate_mmol": 2.6},
                    {"step": 4, "power_w": 260, "lactate_mmol": 4.1},
                    {"step": 5, "power_w": 290, "lactate_mmol": 6.8},
                    {"step": 6, "power_w": 320, "lactate_mmol": 10.2},
                ],
                "mmp": {"1200": 285, "3600": 255, "300": 340, "720": 300, "60": 540, "15": 980},
            },
        }
        mader = run_mader_test(envelope, profiler)
        assert mader.get("status") == "success"
        assert "validated" in mader

        demo_script = Path(__file__).resolve().parents[1] / "engines" / "metabolic" / "lactate_validation_engine.py"
        r = subprocess.run(
            [sys.executable, str(demo_script)],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert r.returncode == 0
