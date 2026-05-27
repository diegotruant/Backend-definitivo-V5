#!/usr/bin/env python3
"""
Test: MetabolicProfiler integration
====================================

Verifies:
  1. The class imports and instantiates
  2. generate_metabolic_snapshot returns a valid snapshot from synthetic MMP
  3. All fields consumed by other engines are present in the output
  4. The phenotype enhancement layer runs without crashing on the real snapshot
  5. metabolic_current.get_current_metabolic_status works end-to-end
  6. detraining_engine.apply_detraining_model accepts the snapshot
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if not ok and detail else ""))


# =============================================================================
# 1. Import + instantiate
# =============================================================================
print("\n[1] Import + instantiate")

from engines import MetabolicProfiler, AthleteContext, MaderConstants

ctx = AthleteContext(
    gender="MALE",
    training_years=5,
    body_fat_pct=12.0,
    discipline="ROAD",
)
profiler = MetabolicProfiler(weight=72.0, context=ctx)

check("MetabolicProfiler instantiated", profiler is not None)
check("profiler.weight set correctly", profiler.weight == 72.0)
check("profiler.const is MaderConstants", isinstance(profiler.const, MaderConstants))
check("profiler.active_muscle_mass computed", profiler.active_muscle_mass > 0)


# =============================================================================
# 2. generate_metabolic_snapshot with realistic MMP
# =============================================================================
print("\n[2] generate_metabolic_snapshot with realistic MMP")

# Realistic MMP for a trained cyclist (W at duration in seconds)
mmp = {
    5:    1100,
    15:    900,
    30:    700,
    60:    520,
    180:   380,
    300:   340,
    600:   310,
    1200:  295,
    1800:  285,
    3600:  270,
}

snapshot = profiler.generate_metabolic_snapshot(mmp)

check("snapshot status == success",
      snapshot.get("status") == "success",
      f"got status={snapshot.get('status')}, message={snapshot.get('message')}")

if snapshot.get("status") == "success":
    # All required fields
    required_fields = [
        "estimated_vo2max",
        "estimated_vlamax_mmol_L_s",
        "metabolic_phenotype",
        "assumed_la_capacity_mmol_L",
        "mlss_power_watts",
        "mlss_power_wkg",
        "fatmax_power_watts",
        "map_aerobic_watts",
        "confidence_score",
        "context_used",
        "zones",
        "combustion_curve",
        "calculated_at",
    ]
    for f in required_fields:
        check(f"snapshot has '{f}'", f in snapshot)
    
    # Physiological plausibility
    vo2 = snapshot["estimated_vo2max"]
    vla = snapshot["estimated_vlamax_mmol_L_s"]
    mlss = snapshot["mlss_power_watts"]
    fatmax = snapshot["fatmax_power_watts"]
    map_w = snapshot["map_aerobic_watts"]
    conf = snapshot["confidence_score"]
    
    print(f"    VO2max:  {vo2} ml/kg/min")
    print(f"    VLamax:  {vla} mmol/L/s")
    print(f"    MLSS:    {mlss}W ({snapshot['mlss_power_wkg']} W/kg)")
    print(f"    FatMax:  {fatmax}W")
    print(f"    MAP:     {map_w}W")
    print(f"    Phenotype: {snapshot['metabolic_phenotype']['category']}")
    print(f"    Confidence: {conf}")
    
    check("VO2max in plausible range [40, 90]", 40 <= vo2 <= 90,
          f"got {vo2}")
    check("VLamax in plausible range [0.1, 1.5]", 0.1 <= vla <= 1.5,
          f"got {vla}")
    check("MLSS > FatMax", mlss > fatmax,
          f"MLSS={mlss}, FatMax={fatmax}")
    check("MAP > MLSS", map_w > mlss,
          f"MAP={map_w}, MLSS={mlss}")
    check("confidence in [0, 1]", 0 <= conf <= 1)
    check("zones list non-empty", isinstance(snapshot["zones"], list) and len(snapshot["zones"]) > 0)
    check("combustion_curve non-empty",
          isinstance(snapshot["combustion_curve"], list) and len(snapshot["combustion_curve"]) > 0)


# =============================================================================
# 3. Insufficient MMP rejected gracefully
# =============================================================================
print("\n[3] Insufficient MMP handled")

bad_snapshot = profiler.generate_metabolic_snapshot({60: 300, 300: 250})  # only 2
check("status == error when <3 anchors",
      bad_snapshot.get("status") == "error",
      f"got status={bad_snapshot.get('status')}")


# =============================================================================
# 4. Phenotype enhancement layer runs on real snapshot
# =============================================================================
print("\n[4] Phenotype enhancement layer")

from engines import enhance_metabolic_snapshot_with_phenotype

if snapshot.get("status") == "success":
    enhanced = enhance_metabolic_snapshot_with_phenotype(
        snapshot.copy(),  # don't mutate
        phenotype="ALL_ROUNDER",
    )
    check("enhanced snapshot returns dict",
          isinstance(enhanced, dict))
    check("phenotype_pcr_params added to snapshot",
          "phenotype_pcr_params" in enhanced)
    check("energy_contributions added to snapshot",
          "energy_contributions" in enhanced)
    
    # Note: phenotype enhancement reads `vo2max_mlkgmin` and `athlete_weight_kg`
    # but MetabolicProfiler produces `estimated_vo2max`. The enhancement falls
    # back to defaults silently — documented schema drift.
    print(f"    [note] phenotype enhancement uses default VO2max/weight because of name mismatch")
    print(f"           (snapshot has 'estimated_vo2max', enhancement reads 'vo2max_mlkgmin')")


# =============================================================================
# 5. metabolic_current uses MetabolicProfiler end-to-end
# =============================================================================
print("\n[5] metabolic_current end-to-end")

from engines import get_current_metabolic_status
from datetime import date

# 30 days of training (synthetic) — use date objects, not ISO strings
from datetime import timedelta
today = date.today()
workout_history = [
    {"date": today - timedelta(days=30-i), "tss": 70 + (i % 7) * 10}
    for i in range(30)
]

try:
    current = get_current_metabolic_status(
        historical_mmp=mmp,
        workout_history=workout_history,
        athlete_weight_kg=72.0,
        athlete_context=None,
    )
    check("get_current_metabolic_status returns dict",
          isinstance(current, dict))
    check("status == success",
          current.get("status") == "success",
          f"got {current.get('status')}, error={current.get('error', current.get('message'))}")
    if current.get("status") == "success":
        print(f"    keys: {list(current.keys())[:10]}")
except Exception as e:
    import traceback
    print(f"    EXCEPTION: {type(e).__name__}: {e}")
    traceback.print_exc()
    check("get_current_metabolic_status didn't crash", False, str(e))


# =============================================================================
# 6. detraining_engine accepts the snapshot
# =============================================================================
print("\n[6] detraining_engine integration")

from engines import calculate_ctl_atl_tsb, apply_detraining_model

if snapshot.get("status") == "success":
    # CTL/ATL/TSB from workout history
    tl = calculate_ctl_atl_tsb(workout_history, today)
    check("CTL/ATL/TSB computed", isinstance(tl, dict) and "ctl" in tl)
    if "ctl" in tl:
        print(f"    CTL: {tl.get('ctl'):.1f}, ATL: {tl.get('atl'):.1f}, TSB: {tl.get('tsb'):.1f}")
    
    # Apply detraining model: check real signature first
    import inspect
    sig = inspect.signature(apply_detraining_model)
    print(f"    apply_detraining_model{sig}")
    try:
        decayed = apply_detraining_model(
            baseline_snapshot=snapshot,
            workout_history=workout_history,
            today=today,
        )
        check("detraining applied", isinstance(decayed, dict))
        if isinstance(decayed, dict) and decayed.get("status") == "success":
            print(f"    decayed VO2max: {decayed.get('current_vo2max', '?')} "
                  f"(baseline: {decayed.get('baseline_vo2max', '?')})")
    except Exception as e:
        import traceback
        traceback.print_exc()
        check("detraining applied", False, str(e))


# =============================================================================
# REPORT
# =============================================================================
print("\n" + "=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  {passed}/{total} checks passed ({100*passed/total:.0f}%)")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  ✗ {name}" + (f": {detail}" if detail else ""))
    sys.exit(1)
else:
    print("✓ All MetabolicProfiler integration checks passed.")
    sys.exit(0)
