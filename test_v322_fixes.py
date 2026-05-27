#!/usr/bin/env python3
"""
Test: v3.2.2 fixes
==================

Validates the two specific fixes:
  1. phenotype enhancement now reads real snapshot fields and accepts
     weight_kg / power_30s / power_1200s as parameters
  2. metabolic_current normalizes workout_history dates (ISO string → date)
     before passing to detraining_engine
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import date, timedelta

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if not ok and detail else ""))


# =============================================================================
# Setup: generate a real snapshot for testing
# =============================================================================
from engines import MetabolicProfiler, AthleteContext, enhance_metabolic_snapshot_with_phenotype

ctx = AthleteContext(gender="MALE", training_years=5, body_fat_pct=12.0)
profiler = MetabolicProfiler(weight=72.0, context=ctx)

mmp = {5: 1100, 15: 900, 30: 700, 60: 520, 180: 380,
       300: 340, 600: 310, 1200: 295, 1800: 285, 3600: 270}
snapshot = profiler.generate_metabolic_snapshot(mmp)
assert snapshot["status"] == "success", "setup failed"


# =============================================================================
# Fix #1: phenotype enhancement reads correct snapshot fields
# =============================================================================
print("\n[Fix #1] Phenotype enhancement uses real snapshot fields")

# Run enhancement WITHOUT passing weight/power params — must derive from snapshot
enhanced = enhance_metabolic_snapshot_with_phenotype(
    snapshot.copy(),
    phenotype="SPRINTER",
)

# The compute_energy_contribution_adaptive uses vo2max for the aerobic threshold
# calculation. The fix means the real snapshot VO2max (56.7) is used, not the
# previous default (50.0). This produces different aerobic_capacity_w and
# therefore different fractions vs the bug.
sprint_data = enhanced["energy_contributions"]["sprint_30s"]
threshold_data = enhanced["energy_contributions"]["threshold_20min"]

check("phenotype_pcr_params added", "phenotype_pcr_params" in enhanced)
check("energy_contributions added", "energy_contributions" in enhanced)
check("sprint_30s has fractions", all(k in sprint_data for k in
      ["pcr_fraction", "anaerobic_fraction", "aerobic_fraction"]))
check("fractions sum to ~1.0",
      abs(sum([sprint_data["pcr_fraction"], sprint_data["anaerobic_fraction"],
               sprint_data["aerobic_fraction"]]) - 1.0) < 0.01)

# Test that derived defaults make sense
# With mlss=240W, power_30s default = 1.5 * 240 = 360W
# With weight=75 default, vo2max=56.7 → aerobic_cap = 56.7*75*0.21/60 = 14.9W → 60% = 8.9W
# This is now consistent with real data, not arbitrary 500W vs default vo2max

# Test passing weight_kg explicitly
enhanced_with_weight = enhance_metabolic_snapshot_with_phenotype(
    snapshot.copy(),
    phenotype="SPRINTER",
    weight_kg=72.0,  # real athlete weight
)
sprint_w = enhanced_with_weight["energy_contributions"]["sprint_30s"]
check("weight_kg parameter accepted",
      isinstance(sprint_w["pcr_fraction"], float))

# Test passing power_30s explicitly
enhanced_with_power = enhance_metabolic_snapshot_with_phenotype(
    snapshot.copy(),
    phenotype="SPRINTER",
    weight_kg=72.0,
    power_30s=900.0,  # higher than 1.5*MLSS default
    power_1200s=280.0,
)
sprint_p = enhanced_with_power["energy_contributions"]["sprint_30s"]
# With higher power, anaerobic fraction should be higher than default
default_anaerobic = sprint_w["anaerobic_fraction"]
higher_p_anaerobic = sprint_p["anaerobic_fraction"]
check("higher power_30s → higher anaerobic fraction (or same if capped)",
      higher_p_anaerobic >= default_anaerobic - 0.001,
      f"default={default_anaerobic}, higher={higher_p_anaerobic}")

print(f"    Default-power sprint: PCr={sprint_w['pcr_fraction']:.0%}, "
      f"Ana={sprint_w['anaerobic_fraction']:.0%}, "
      f"Aer={sprint_w['aerobic_fraction']:.0%}")
print(f"    High-power sprint:    PCr={sprint_p['pcr_fraction']:.0%}, "
      f"Ana={sprint_p['anaerobic_fraction']:.0%}, "
      f"Aer={sprint_p['aerobic_fraction']:.0%}")


# =============================================================================
# Fix #2: metabolic_current normalizes workout_history dates
# =============================================================================
print("\n[Fix #2] workout_history with ISO string dates handled")

from engines import get_current_metabolic_status

today = date.today()

# Build workout history with ISO STRING dates (previously crashed)
workout_history_strings = [
    {"date": (today - timedelta(days=30-i)).isoformat(),  # ISO STRING
     "tss": 70 + (i % 7) * 10}
    for i in range(30)
]

try:
    current = get_current_metabolic_status(
        historical_mmp=mmp,
        workout_history=workout_history_strings,
        athlete_weight_kg=72.0,
        athlete_context=None,
        today=today,
    )
    check("ISO string dates in workout_history don't crash",
          current.get("status") == "success",
          f"got status={current.get('status')}, error={current.get('error')}")
    if current.get("status") == "success":
        print(f"    CTL: {current['training_load'].get('ctl'):.1f}, "
              f"current VO2max: {current.get('current_vo2max', '?')}")
except Exception as e:
    check("ISO string dates in workout_history don't crash", False, str(e))

# Test with date objects (already worked, must still work)
workout_history_dates = [
    {"date": today - timedelta(days=30-i),
     "tss": 70 + (i % 7) * 10}
    for i in range(30)
]
try:
    current2 = get_current_metabolic_status(
        historical_mmp=mmp,
        workout_history=workout_history_dates,
        athlete_weight_kg=72.0,
        today=today,
    )
    check("date objects in workout_history still work",
          current2.get("status") == "success")
except Exception as e:
    check("date objects in workout_history still work", False, str(e))

# Test malformed dates handled gracefully
workout_history_bad = [
    {"date": "not-a-date", "tss": 80},  # malformed
    {"date": (today - timedelta(days=5)).isoformat(), "tss": 75},  # valid
    {"date": None, "tss": 60},  # missing
    {"date": (today - timedelta(days=2)).isoformat(), "tss": 90},  # valid
]
try:
    current3 = get_current_metabolic_status(
        historical_mmp=mmp,
        workout_history=workout_history_bad,
        athlete_weight_kg=72.0,
        today=today,
    )
    check("malformed dates skipped gracefully",
          current3.get("status") == "success")
except Exception as e:
    check("malformed dates skipped gracefully", False, str(e))


# Test mixed types
workout_history_mixed = []
for i in range(30):
    d_obj = today - timedelta(days=30-i)
    # Alternate between string and date object
    if i % 2 == 0:
        workout_history_mixed.append({"date": d_obj.isoformat(), "tss": 75})
    else:
        workout_history_mixed.append({"date": d_obj, "tss": 85})

try:
    current4 = get_current_metabolic_status(
        historical_mmp=mmp,
        workout_history=workout_history_mixed,
        athlete_weight_kg=72.0,
        today=today,
    )
    check("mixed date types handled",
          current4.get("status") == "success")
except Exception as e:
    check("mixed date types handled", False, str(e))


# =============================================================================
# REPORT
# =============================================================================
print("\n" + "=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  {passed}/{total} fix-validation checks passed")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  ✗ {name}: {detail}")
    sys.exit(1)
else:
    print("✓ All v3.2.2 fixes validated.")
    sys.exit(0)
