#!/usr/bin/env python3
"""
Regression checks for the high-priority scientific bug fixes.
"""

import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))


print("\n[1] W' recovery uses remaining deficit")
from engines import calculate_w_prime_balance, analyze_w_prime_usage

w_prime = 1000.0
tau = 10.0
power = [100.0] + [200.0] * 5 + [50.0]
balance = calculate_w_prime_balance(power, cp=100.0, w_prime=w_prime, tau=tau)
expected_after_recovery = 500.0 + (w_prime - 500.0) * (1.0 - np.exp(-1.0 / tau))
check(
    "W' recovery matches deficit-based equation",
    abs(balance[-1] - expected_after_recovery) < 1e-6,
    f"got={balance[-1]:.6f} expected={expected_after_recovery:.6f}",
)
usage = analyze_w_prime_usage(power, balance, w_prime=w_prime)
check("fully_depleted uses relative threshold", usage["fully_depleted"] is False)


print("\n[2] Kalman passes profiler into automatic test-anchor update")
from engines import DailyInput, process_workout_history


class _FakeContext:
    def expected_eta(self):
        return 0.22


class _FakeConst:
    w_min = 50
    w_step = 50


class _FakeProfiler:
    def __init__(self):
        self.context = _FakeContext()
        self.const = _FakeConst()
        self.pred_calls = 0

    def _pcr_prior_watts(self):
        return 0.0

    def _compute_grid_state(self, vo2, vla, eta, w_grid):
        map_est = vo2 * 72.0 * 0.075
        return 400.0 / max(vla, 0.1), map_est, np.zeros_like(w_grid), np.zeros_like(w_grid)

    def _pred_power(self, t, la_cap, tau, map_est, w_grid, vo2_act, net):
        self.pred_calls += 1
        return map_est * np.exp(-float(t) / tau)


fake_profiler = _FakeProfiler()
di = DailyInput(date=date(2026, 1, 1), test_anchors=[(300, 340), (600, 305)])
traj = process_workout_history(
    [di],
    initial_vo2=55.0,
    initial_vla=0.40,
    weight=72.0,
    profiler=fake_profiler,
)
check("profiler forward model was called", fake_profiler.pred_calls > 0)
check("trajectory recorded a test update", traj.n_update_steps == 1)


print("\n[3] Masked metabolic fields do not crash or silently default")
from engines import apply_detraining_model, enhance_metabolic_snapshot_with_phenotype
from engines.cardiac_engine import ActivitySample, CardiacResponseAnalyzer

masked_snapshot = {
    "status": "success",
    "estimated_vo2max": None,
    "estimated_vlamax_mmol_L_s": None,
    "mlss_power_watts": None,
    "map_aerobic_watts": 400.0,
    "expressiveness": {"fully_expressive": False},
    "unmasked_estimates": {
        "estimated_vo2max": 55.0,
        "estimated_vlamax_mmol_L_s": 0.4,
        "mlss_power_watts": 280.0,
    },
}

enhanced = enhance_metabolic_snapshot_with_phenotype(masked_snapshot.copy(), "SPRINTER")
check("phenotype enhancement reports insufficient fields",
      enhanced.get("phenotype_enhancement_status") == "insufficient_metabolic_fields")
check("phenotype enhancement does not synthesize energy defaults",
      enhanced.get("energy_contributions") is None)

detrained = apply_detraining_model(masked_snapshot.copy(), [], date(2026, 1, 1))
check("detraining returns partial for masked core fields",
      detrained.get("status") == "partial",
      f"got={detrained.get('status')}")
check("detraining does not apply defaults",
      detrained.get("detraining_applied") is False)

samples = [ActivitySample(t=float(i), power=220.0, hr=145.0) for i in range(180)]
cardiac = CardiacResponseAnalyzer(weight=72.0, metabolic_snapshot=masked_snapshot).analyze(samples)
check("cardiac analysis tolerates masked MLSS", cardiac.get("status") == "success")


print("\n[4] HRV threshold power uses elapsed-time interpolation")
from hrv_engine import _detect_threshold_crossing

threshold_results = [
    {"timestamp": 100.0, "alpha1_smoothed": 0.80},
    {"timestamp": 110.0, "alpha1_smoothed": 0.70},
    {"timestamp": 120.0, "alpha1_smoothed": 0.65},
]
_, t_cross, p_cross = _detect_threshold_crossing(
    threshold_results,
    threshold=0.75,
    power_data=[200.0, 300.0, 400.0],
    power_timestamps=[100.0, 110.0, 120.0],
    persistence_windows=2,
)
check("threshold time preserved on RR elapsed axis", t_cross == 110)
check("threshold power interpolated on explicit power timestamps",
      abs(p_cross - 250.0) < 1e-6,
      f"got={p_cross}")


print("\n[5] Durability preserves elapsed-time zeros")
from engines import calculate_durability_index

power_stream = [0.0] * 1800 + [200.0] * 1800 + [200.0] * 3600 + [100.0] * 3600
durability = calculate_durability_index(power_stream, duration_seconds=len(power_stream))
check("durability computed", durability.get("status") == "success")
check("first hour includes zero-power elapsed samples",
      durability.get("first_hour_avg") == 100.0,
      f"got={durability.get('first_hour_avg')}")
check("last hour uses real final hour",
      durability.get("last_hour_avg") == 100.0,
      f"got={durability.get('last_hour_avg')}")


print("\n[6] Phase 1 weak-code fixes")
from power_engine import normalized_power
from engines import calculate_np_drift, calculate_monotony_strain, estimate_fat_oxidation_rate

rng = np.random.default_rng(42)
power_45m = np.clip(180 + 40 * rng.standard_normal(2700), 0, None)
mid = power_45m.size // 2
np_drift = calculate_np_drift(power_45m.tolist(), duration_seconds=power_45m.size)
expected_first = normalized_power(power_45m[:mid])
expected_second = normalized_power(power_45m[mid:])
check("np drift uses canonical normalized_power", np_drift.get("np_method") == "power_engine.normalized_power")
check(
    "np drift first half matches power_engine",
    abs(np_drift["np_first_half"] - round(expected_first, 0)) < 1.0,
    f"got={np_drift.get('np_first_half')} expected~{round(expected_first, 0)}",
)
check(
    "np drift has api_contract",
    "api_contract" in np_drift and np_drift["api_contract"]["module"] == "durability_engine",
)

flat_week = calculate_monotony_strain([50.0] * 7)
check("flat TSS week flags unstable monotony", flat_week.get("status") == "unstable")
check(
    "flat TSS week exposes edge_case_flags",
    "near_zero_daily_tss_variance" in flat_week.get("edge_case_flags", []),
)

fat_ox = estimate_fat_oxidation_rate(fatmax_watts=210, weight_kg=70)
check("fat oxidation uses weight_kg", fat_ox.get("fat_oxidation_mg_per_kg_per_min") is not None)
check(
    "fat oxidation mass-normalized value consistent",
    abs(fat_ox["fat_oxidation_mg_per_kg_per_min"] - (210 * 0.001 * 1000 / 70)) < 0.01,
)


print("\n" + "=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  {passed}/{total} scientific bug-fix checks passed")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL {name}: {detail}")
    sys.exit(1)

print("PASS Scientific bug-fix regressions passed.")
sys.exit(0)
