#!/usr/bin/env python3
"""Tests for in-person test protocols and lactate validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))


print("\n[1] Lactate D-max thresholds")
from engines.metabolic.lactate_validation_engine import compute_lactate_thresholds, steps_from_payload

steps = steps_from_payload([
    {"step": 1, "power_w": 150, "lactate_mmol": 1.2},
    {"step": 2, "power_w": 200, "lactate_mmol": 1.8},
    {"step": 3, "power_w": 230, "lactate_mmol": 2.6},
    {"step": 4, "power_w": 260, "lactate_mmol": 4.1},
    {"step": 5, "power_w": 290, "lactate_mmol": 6.8},
    {"step": 6, "power_w": 320, "lactate_mmol": 10.2},
])
thr = compute_lactate_thresholds(steps)
check("mlss dmax present", (thr.mlss_dmax_w or 0) > 0)
check("to_dict works", "mlss_dmax_watts" in thr.to_dict())


print("\n[2] Critical power via test_protocols")
from engines.performance.test_protocols import run_critical_power_test

cp_env = {
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
cp = run_critical_power_test(cp_env)
check("CP test success", cp.get("status") == "success")
check("CP watts positive", float(cp.get("cp_w", 0)) > 0)


print("\n[3] Wingate via test_protocols")
from engines.performance.test_protocols import run_wingate_test

wingate = run_wingate_test({
    "test_type": "wingate",
    "athlete": {"weight_kg": 72},
    "test_data": {
        "duration_s": 10,
        "power_stream": [900, 850, 800, 750, 700, 650, 600, 550, 500, 450],
        "body_weight_kg": 72,
    },
})
check("Wingate success", wingate.get("status") == "success")
check("peak power", float(wingate.get("peak_power_w", 0)) == 900)


print("\n[4] Dispatcher run_test")
from engines import run_in_person_test

unknown = run_in_person_test({"test_type": "invalid"})
check("unknown type errors", unknown.get("status") == "error")

print("\n" + "=" * 50)
passed = sum(1 for _, ok, _ in results if ok)
print(f"  {passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
