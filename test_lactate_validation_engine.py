#!/usr/bin/env python3
"""Verify lactate_validation_engine (uploaded version) and test_protocols wiring."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))


print("\n[1] D-max thresholds (LactateStep API)")
from engines.metabolic.lactate_validation_engine import LactateStep, compute_lactate_thresholds, steps_from_payload

steps = steps_from_payload([
    {"step": 1, "power_w": 150, "lactate_mmol": 1.2},
    {"step": 2, "power_w": 200, "lactate_mmol": 1.8},
    {"step": 3, "power_w": 230, "lactate_mmol": 2.6},
    {"step": 4, "power_w": 260, "lactate_mmol": 4.1},
    {"step": 5, "power_w": 290, "lactate_mmol": 6.8},
    {"step": 6, "power_w": 320, "lactate_mmol": 10.2},
])
thr = compute_lactate_thresholds(steps)
check("returns LactateThresholds", hasattr(thr, "mlss_dmax_w"))
check("mlss dmax in plausible range", 200 <= (thr.mlss_dmax_w or 0) <= 280)
check("obla 4mmol present", thr.obla_4mmol_w is not None)


print("\n[2] Insufficient steps guard")
from engines.metabolic.lactate_validation_engine import validate_model_against_lactate
from engines import MetabolicProfiler, AthleteContext

profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
short = [LactateStep(power_w=200, lactate_mmol=2.0)] * 3
err = validate_model_against_lactate(short, profiler, {1200: 280, 1800: 270, 3600: 255})
check("rejects <5 steps", err.get("status") == "error")
check("reason set", err.get("reason") == "insufficient_lactate_steps")


print("\n[3] Full Mader validation (CONTRATTO example)")
mmp = {15: 980, 60: 540, 300: 340, 720: 300, 1200: 285, 3600: 255}
result = validate_model_against_lactate(steps, profiler, mmp)
check("validation success", result.get("status") == "success")
check("has verdict", bool(result.get("verdict")))
check("lactate_thresholds dict", "mlss_dmax_watts" in (result.get("lactate_thresholds") or {}))
check("api_contract present", "api_contract" in result)
print(f"    validated={result.get('validated')} severity={result.get('severity')} "
      f"mlss_true={result.get('mlss_true_watts')} model={result.get('mlss_model_watts')} "
      f"err%={result.get('error_pct')}")


print("\n[4] test_protocols.run_mader_test")
from engines.performance.test_protocols import run_mader_test

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
check("run_mader_test success", mader.get("status") == "success")
check("run_mader_test validated flag", "validated" in mader)


print("\n[5] Module self-demo")
import subprocess
demo_script = Path(__file__).parent / "engines" / "metabolic" / "lactate_validation_engine.py"
r = subprocess.run([sys.executable, str(demo_script)], capture_output=True, text=True, cwd=str(Path(__file__).parent))
check("demo script exits 0", r.returncode == 0, r.stderr[:200] if r.returncode else "")

print("\n" + "=" * 50)
passed = sum(1 for _, ok, _ in results if ok)
print(f"  {passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
