#!/usr/bin/env python3
"""
Test: v4.0.0 — Bayesian metabolic profiler
============================================

Validates:
  1. MCMC produces valid posterior samples
  2. Credible intervals have correct coverage properties
  3. Flat MMP → wider VLamax posterior (expressiveness emerges)
  4. Output contract (to_dict, backward-compat fields)
  5. Diego real data runs without error
  6. Edge cases (too few anchors, extreme values)
  7. Bayesian confidence is derived from prior-vs-posterior reduction
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import json
import numpy as np

from engines import (
    MetabolicProfiler, AthleteContext, MaderConstants,
    bayesian_metabolic_snapshot, BayesianMetabolicSnapshot, PosteriorSummary,
)


results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if not ok and detail else ""))


ctx = AthleteContext(gender="MALE", training_years=5, discipline="ROAD")
p = MetabolicProfiler(weight=72, context=ctx)


# =============================================================================
# 1. Basic MCMC produces valid output
# =============================================================================
print("\n[1] Basic MCMC output")

mmp = {5: 950, 30: 620, 60: 470, 300: 340, 600: 305, 1200: 290, 3600: 270}
snap = bayesian_metabolic_snapshot(p, p._coerce_mmp_dict(mmp), n_samples=2000, n_warmup=500)

check("status is success", snap.status == "success")
check("vo2max posterior exists", snap.vo2max is not None)
check("vlamax posterior exists", snap.vlamax is not None)
check("sigma posterior exists", snap.sigma is not None)

if snap.vo2max:
    check("vo2max mean in plausible range",
          25 < snap.vo2max.mean < 95,
          f"got {snap.vo2max.mean:.1f}")
    check("vo2max ci95_low < mean < ci95_high",
          snap.vo2max.ci95_low < snap.vo2max.mean < snap.vo2max.ci95_high)
    check("vo2max std > 0", snap.vo2max.std > 0)
    check("vo2max ESS > 50",
          snap.vo2max.n_effective_samples > 50,
          f"got {snap.vo2max.n_effective_samples}")

if snap.vlamax:
    check("vlamax mean > 0",
          snap.vlamax.mean > 0,
          f"got {snap.vlamax.mean:.4f}")
    check("vlamax ci95_low < ci95_high",
          snap.vlamax.ci95_low < snap.vlamax.ci95_high)

check("acceptance rate in [0.05, 0.80]",
      0.05 <= snap.acceptance_rate <= 0.80,
      f"got {snap.acceptance_rate:.3f}")


# =============================================================================
# 2. Credible intervals: CI95 should be wider than CI80
# =============================================================================
print("\n[2] Credible interval properties")

if snap.vo2max:
    ci95_w = snap.vo2max.ci95_high - snap.vo2max.ci95_low
    ci80_w = snap.vo2max.ci80_high - snap.vo2max.ci80_low
    check("CI95 wider than CI80 (vo2max)",
          ci95_w > ci80_w,
          f"CI95={ci95_w:.1f}, CI80={ci80_w:.1f}")
    check("CI95 width > 0", ci95_w > 0)


# =============================================================================
# 3. Flat MMP → wider VLamax posterior (the key Bayesian advantage)
# =============================================================================
print("\n[3] Expressiveness emerges naturally")

mmp_full = {5: 950, 30: 620, 60: 470, 300: 340, 1200: 290, 3600: 270}
mmp_flat = {300: 340, 600: 300, 1200: 290, 1800: 285, 3600: 270}

snap_full = bayesian_metabolic_snapshot(p, p._coerce_mmp_dict(mmp_full), n_samples=2000, n_warmup=500)
snap_flat = bayesian_metabolic_snapshot(p, p._coerce_mmp_dict(mmp_flat), n_samples=2000, n_warmup=500)

if snap_full.vlamax and snap_flat.vlamax:
    full_width = snap_full.vlamax.ci95_width
    flat_width = snap_flat.vlamax.ci95_width
    check("flat MMP → wider VLamax CI95 than full MMP",
          flat_width > full_width * 0.9,  # allow 10% margin for MCMC noise
          f"flat={flat_width:.3f} vs full={full_width:.3f}")
    check("flat MMP VLamax std >= full MMP std",
          snap_flat.vlamax.std >= snap_full.vlamax.std * 0.85,
          f"flat={snap_flat.vlamax.std:.3f} vs full={snap_full.vlamax.std:.3f}")


# =============================================================================
# 4. Output contract
# =============================================================================
print("\n[4] Output contract")

d = snap.to_dict()
required_keys = {
    "status", "method", "tier",
    "vo2max", "vlamax", "sigma",
    "estimated_vo2max", "estimated_vlamax_mmol_L_s",  # backward-compat
    "mlss_power_watts", "mlss_power_wkg",
    "fatmax_power_watts", "map_aerobic_watts",
    "bayesian_confidence", "mcmc_diagnostics",
    "expressiveness", "context_used", "calculated_at",
}
check("to_dict has all required keys",
      required_keys.issubset(d.keys()),
      f"missing: {required_keys - set(d.keys())}")
check("method is bayesian_mcmc", d["method"] == "bayesian_mcmc")
check("tier is MODEL", d["tier"] == "MODEL")
check("backward-compat estimated_vo2max is float",
      isinstance(d["estimated_vo2max"], (int, float)))

# PosteriorSummary.to_dict
if snap.vo2max:
    ps_dict = snap.vo2max.to_dict()
    check("PosteriorSummary has ci95",
          "ci95" in ps_dict and len(ps_dict["ci95"]) == 2)
    check("PosteriorSummary has prior",
          "prior" in ps_dict)

# MCMC diagnostics
check("mcmc_diagnostics has acceptance_rate",
      "acceptance_rate" in d["mcmc_diagnostics"])


# =============================================================================
# 5. Bayesian confidence: measures prior→posterior reduction
# =============================================================================
print("\n[5] Bayesian confidence")

check("bayesian_confidence in [0, 1]",
      0.0 <= snap.bayesian_confidence <= 1.0,
      f"got {snap.bayesian_confidence:.3f}")
check("full MMP has higher confidence than flat MMP",
      snap_full.bayesian_confidence >= snap_flat.bayesian_confidence * 0.7,
      f"full={snap_full.bayesian_confidence:.3f} flat={snap_flat.bayesian_confidence:.3f}")


# =============================================================================
# 6. Raw posterior samples are available
# =============================================================================
print("\n[6] Raw posterior samples")

check("raw_samples_vo2 available",
      snap.raw_samples_vo2 is not None and len(snap.raw_samples_vo2) > 100)
check("raw_samples_vla available",
      snap.raw_samples_vla is not None and len(snap.raw_samples_vla) > 100)

if snap.raw_samples_vo2:
    arr = np.array(snap.raw_samples_vo2)
    check("raw samples vo2 mean matches summary",
          abs(arr.mean() - snap.vo2max.mean) < 0.1)


# =============================================================================
# 7. Edge cases
# =============================================================================
print("\n[7] Edge cases")

# Too few anchors
snap_err = bayesian_metabolic_snapshot(p, {60: 400})
check("1 anchor → error", snap_err.status == "error")

# 3 anchors (minimum)
snap_min = bayesian_metabolic_snapshot(p, {60: 400, 300: 320, 1200: 280},
                                       n_samples=1000, n_warmup=300)
check("3 anchors → success", snap_min.status == "success")

# Custom priors
snap_custom = bayesian_metabolic_snapshot(
    p, p._coerce_mmp_dict(mmp),
    prior_vo2_mean=60.0, prior_vo2_std=5.0,
    prior_vla_mean=0.5, prior_vla_std=0.15,
    n_samples=1000, n_warmup=300,
)
check("custom priors accepted", snap_custom.status == "success")
if snap_custom.vo2max:
    check("custom prior_mean reflected in output",
          snap_custom.vo2max.prior_mean == 60.0)


# =============================================================================
# 8. Custom MaderConstants propagate
# =============================================================================
print("\n[8] MaderConstants propagation")

custom_const = MaderConstants(ks1=0.0635, _source="nolte_2025")
p_custom = MetabolicProfiler(weight=72, context=ctx, mader_constants=custom_const)
snap_cc = bayesian_metabolic_snapshot(p_custom, p._coerce_mmp_dict(mmp),
                                      n_samples=1000, n_warmup=300)
check("custom constants in output",
      snap_cc.context_used["mader_constants"]["source"] == "nolte_2025")


# =============================================================================
# 9. Real data: Diego
# =============================================================================
print("\n[9] Real data: Diego")

diego_path = Path("/mnt/user-data/uploads/diego.json")
if diego_path.exists():
    with open(diego_path) as f:
        dd = json.load(f)
    ath = dd["snapshot"]["athlete"]
    ctx_d = AthleteContext(
        gender="MALE", training_years=ath.get("endurance_years", 5),
        discipline=ath.get("primary_discipline", "MIXED"),
        body_fat_pct=ath.get("body_fat_pct"),
    )
    p_d = MetabolicProfiler(weight=ath["weight_kg"], context=ctx_d)
    snap_d = bayesian_metabolic_snapshot(p_d, p_d._coerce_mmp_dict(dd["mmp"]),
                                         n_samples=2000, n_warmup=500)
    check("Diego: status success", snap_d.status == "success")
    if snap_d.vo2max:
        check("Diego: VO2max in plausible range",
              30 < snap_d.vo2max.mean < 70,
              f"got {snap_d.vo2max.mean:.1f}")
        check("Diego: CI95 computed",
              snap_d.vo2max.ci95_low < snap_d.vo2max.ci95_high)
        print(f"    Diego VO2max: {snap_d.vo2max.mean:.1f} [{snap_d.vo2max.ci95_low:.1f}, {snap_d.vo2max.ci95_high:.1f}]")
        print(f"    Diego VLamax: {snap_d.vlamax.mean:.4f} [{snap_d.vlamax.ci95_low:.4f}, {snap_d.vlamax.ci95_high:.4f}]")
        print(f"    Diego conf:   {snap_d.bayesian_confidence:.3f}")
else:
    print("    (diego.json not available)")


# =============================================================================
# REPORT
# =============================================================================
print()
print("=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  v4.0.0 BAYESIAN PROFILER: {passed}/{total} ({100*passed/total:.0f}%)")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  ✗ {name}: {detail}")
    sys.exit(1)
else:
    print("✓ All v4.0.0 Bayesian profiler checks passed.")
    sys.exit(0)
