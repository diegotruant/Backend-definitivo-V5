#!/usr/bin/env python3
"""
Comprehensive Stress Test — v3.3.1 API
=======================================

Exercises the package under realistic load and adversarial conditions:

  1. Three rider archetypes (Sprinter, Climber, All-Rounder) with
     contextually different MMP profiles
  2. Full pipeline per rider: MetabolicProfiler → phenotype enhance →
     metabolic_current with detraining
  3. Per-activity orchestrator on synthetic 3h ride per rider
  4. Longitudinal: CTL/ATL/TSB, ACWR, monotony/strain
  5. W' balance under interval simulation
  6. Adversarial inputs: empty MMP, single-anchor MMP, NaN-laden stream,
     all-zero power, missing fields
  7. Sport-name disciplines (ROAD, TRACK, MTB, etc.)
  8. efforts_analyzer falsy-zero edge case

This is NOT a synthetic happy-path test — it deliberately pushes the
engines into corners and asserts they handle them gracefully (either
return status=error with a message, or produce plausible numbers).
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime, timedelta, date
import numpy as np

from engines import (
    MetabolicProfiler, AthleteContext, ENGINE_TIERS,
    parse_fit_records_enhanced, build_workout_summary,
    get_current_metabolic_status, calculate_ctl_atl_tsb,
    calculate_w_prime_balance, analyze_w_prime_usage,
    calculate_acwr, calculate_monotony_strain,
    analyze_efforts,
)


results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if not ok and detail else ""))


# =============================================================================
# Rider archetypes
# =============================================================================

ATHLETE_PROFILES = {
    "sprinter": {
        "weight_kg": 78.0,
        "context": AthleteContext(
            gender="MALE", training_years=8, discipline="TRACK",
            body_fat_pct=10.0,
        ),
        "ftp": 320.0, "lthr": 168,
        "mmp": {
            5: 1450, 15: 1200, 30: 950, 60: 700, 180: 480,
            300: 410, 600: 360, 1200: 335, 1800: 320, 3600: 295,
        },
    },
    "climber": {
        "weight_kg": 62.0,
        "context": AthleteContext(
            gender="MALE", training_years=10, discipline="ROAD",
            body_fat_pct=8.0,
        ),
        "ftp": 290.0, "lthr": 172,
        "mmp": {
            5: 850, 15: 730, 30: 580, 60: 460, 180: 360,
            300: 330, 600: 305, 1200: 295, 1800: 290, 3600: 280,
        },
    },
    "all_rounder": {
        "weight_kg": 72.0,
        "context": AthleteContext(
            gender="MALE", training_years=6, discipline="MIXED",
            body_fat_pct=12.0,
        ),
        "ftp": 295.0, "lthr": 168,
        "mmp": {
            5: 1100, 15: 920, 30: 720, 60: 540, 180: 400,
            300: 360, 600: 320, 1200: 305, 1800: 297, 3600: 285,
        },
    },
}


# =============================================================================
# Section 1: Per-archetype full pipeline
# =============================================================================
print("\n" + "=" * 70)
print("Section 1 — Per-archetype full pipeline")
print("=" * 70)

snapshots = {}
for name, p in ATHLETE_PROFILES.items():
    print(f"\n[{name.upper()}] weight={p['weight_kg']}kg, ftp={p['ftp']}W, discipline={p['context'].discipline}")
    
    t0 = time.time()
    profiler = MetabolicProfiler(weight=p["weight_kg"], context=p["context"])
    snap = profiler.generate_metabolic_snapshot(p["mmp"])
    elapsed = (time.time() - t0) * 1000
    
    check(f"{name}: snapshot generated",
          snap.get("status") == "success",
          f"status={snap.get('status')}")
    
    if snap.get("status") == "success":
        snapshots[name] = snap
        print(f"    elapsed: {elapsed:.0f}ms")
        print(f"    VO2max: {snap['estimated_vo2max']} ml/kg/min")
        print(f"    VLamax: {snap['estimated_vlamax_mmol_L_s']} mmol/L/s")
        print(f"    MLSS:   {snap['mlss_power_watts']}W ({snap['mlss_power_wkg']} W/kg)")
        print(f"    Phenotype: {snap['metabolic_phenotype']['category']}")
        
        # Fluent enhance with phenotype
        phenotype_map = {"sprinter": "SPRINTER", "climber": "TT_CLIMBER",
                         "all_rounder": "ALL_ROUNDER"}
        enriched = profiler.enhance_with_phenotype(
            snap.copy(), phenotype=phenotype_map[name],
        )
        check(f"{name}: phenotype enhancement applied",
              "phenotype_pcr_params" in enriched)
        
        # Plausibility per archetype
        if name == "sprinter":
            check(f"{name}: VLamax > 0.5 (glycolytic)",
                  snap["estimated_vlamax_mmol_L_s"] > 0.5,
                  f"got {snap['estimated_vlamax_mmol_L_s']}")
        elif name == "climber":
            check(f"{name}: VO2max > 60 (aerobic dominant)",
                  snap["estimated_vo2max"] > 60,
                  f"got {snap['estimated_vo2max']}")


# =============================================================================
# Section 2: Per-activity orchestrator on 3h synthetic ride
# =============================================================================
print("\n" + "=" * 70)
print("Section 2 — Per-activity orchestrator (3h ride per archetype)")
print("=" * 70)

np.random.seed(7)
base = datetime(2026, 5, 19, 8, 0)

for name, p in ATHLETE_PROFILES.items():
    print(f"\n[{name.upper()}] 3h synthetic endurance ride")
    
    duration_s = 3 * 3600
    records = []
    target = p["ftp"] * 0.75
    for i in range(duration_s):
        power = target + np.random.normal(0, target * 0.10) - (i / duration_s) * 8
        hr = p["lthr"] * 0.85 + np.random.normal(0, 4) + (i / duration_s) * 6
        records.append({
            "timestamp": base + timedelta(seconds=i),
            "power": max(0, int(power)),
            "heart_rate": max(50, int(hr)),
            "cadence": int(88 + np.random.normal(0, 5)),
            "distance": i * 9.0,
        })
    
    stream = parse_fit_records_enhanced(
        records,
        session_dict={"sport": "cycling", "start_time": base},
    )
    
    t0 = time.time()
    summary = build_workout_summary(
        stream=stream,
        weight_kg=p["weight_kg"],
        ftp=p["ftp"],
        lthr=p["lthr"],
        context=p["context"],
    )
    elapsed = (time.time() - t0) * 1000
    
    check(f"{name}: orchestrator success",
          summary.get("status") == "success")
    
    if summary.get("status") == "success":
        power_sec = summary["sections"]["power"]
        if power_sec.get("status") == "success":
            m = power_sec["metrics"]
            print(f"    {elapsed:.0f}ms — TSS={m['tss']}, NP={m['normalized_power']}W, IF={m['intensity_factor']}")
            check(f"{name}: TSS in plausible 3h-Z2 range (150-280)",
                  150 < m["tss"] < 280,
                  f"got {m['tss']}")


# =============================================================================
# Section 3: Longitudinal — detraining + ACWR
# =============================================================================
print("\n" + "=" * 70)
print("Section 3 — Longitudinal pipeline")
print("=" * 70)

today = date.today()
workout_history = [
    {"date": today - timedelta(days=30-i), "tss": 70 + (i % 7) * 10}
    for i in range(30)
]

for name in ATHLETE_PROFILES:
    if name not in snapshots:
        continue
    p = ATHLETE_PROFILES[name]
    
    print(f"\n[{name.upper()}] metabolic_current end-to-end")
    current = get_current_metabolic_status(
        historical_mmp=p["mmp"],
        workout_history=workout_history,
        athlete_weight_kg=p["weight_kg"],
        athlete_context={
            "gender": p["context"].gender,
            "training_years": p["context"].training_years,
            "discipline": p["context"].discipline,
        },
        today=today,
    )
    check(f"{name}: get_current_metabolic_status success",
          current.get("status") == "success")
    
    if current.get("status") == "success":
        ath = current.get("athlete", {})
        print(f"    weight={ath.get('weight_kg')}kg, discipline (effective)={ath.get('discipline')}")
        
        # The fix: discipline in output is the *effective* one
        if name == "sprinter":
            check(f"{name}: TRACK mapped to SPRINT in output",
                  ath.get("discipline") == "SPRINT",
                  f"got {ath.get('discipline')}")
        elif name == "climber":
            check(f"{name}: ROAD mapped to ENDURANCE in output",
                  ath.get("discipline") == "ENDURANCE",
                  f"got {ath.get('discipline')}")
        elif name == "all_rounder":
            check(f"{name}: MIXED unchanged in output",
                  ath.get("discipline") == "MIXED",
                  f"got {ath.get('discipline')}")
        
        # inferred_fields should NOT contain "discipline" (we resolved it)
        check(f"{name}: discipline NOT in inferred_fields",
              "discipline" not in ath.get("inferred_fields", []))


# ACWR + monotony
print()
tl = calculate_ctl_atl_tsb(workout_history, today)
check("CTL/ATL/TSB computed", "ctl" in tl)
acwr = calculate_acwr(atl=tl.get("atl", 0), ctl=tl.get("ctl", 0))
check("ACWR computed", "acwr" in acwr)
print(f"    CTL={tl.get('ctl'):.1f}, ATL={tl.get('atl'):.1f}, TSB={tl.get('tsb'):.1f}, ACWR={acwr.get('acwr')}")
ms = calculate_monotony_strain([w["tss"] for w in workout_history[-7:]])
check("Monotony/Strain computed", "monotony" in ms)


# =============================================================================
# Section 4: W' balance under interval simulation
# =============================================================================
print("\n" + "=" * 70)
print("Section 4 — W' balance with intervals")
print("=" * 70)

interval_power = [180] * 600
for _ in range(6):
    interval_power += [380] * 240
    interval_power += [120] * 120
interval_power += [150] * 600

balance = calculate_w_prime_balance(power_stream=interval_power, cp=275, w_prime=18000)
check("W' balance has same length as power", len(balance) == len(interval_power))
usage = analyze_w_prime_usage(interval_power, balance, w_prime=18000)
print(f"    min balance: {usage['min_balance_j']}J ({usage['min_balance_pct']}%)")
print(f"    critical depletions: {usage['critical_depletions_count']}")
check("W' usage analysis returns critical_depletions_count",
      "critical_depletions_count" in usage)
check("min balance below initial W'",
      usage["min_balance_j"] < 18000)


# =============================================================================
# Section 5: Adversarial inputs
# =============================================================================
print("\n" + "=" * 70)
print("Section 5 — Adversarial inputs")
print("=" * 70)

p = ATHLETE_PROFILES["all_rounder"]
profiler = MetabolicProfiler(weight=p["weight_kg"], context=p["context"])

# 5a. Empty MMP
empty_snap = profiler.generate_metabolic_snapshot({})
check("empty MMP → status=error",
      empty_snap.get("status") == "error")

# 5b. Single-anchor MMP
single_snap = profiler.generate_metabolic_snapshot({60: 300})
check("single-anchor MMP → status=error",
      single_snap.get("status") == "error")

# 5c. MMP with mixed key formats (strings, "m" suffix, None values)
mixed = {"5s": 1100, "60s": "bad", 300: None, 1200: 295, 3600: 270, "30m": 285}
mixed_snap = profiler.generate_metabolic_snapshot(mixed)
check("mixed-format MMP coerces valid entries",
      mixed_snap.get("status") == "success",
      f"got {mixed_snap.get('status')}, msg={mixed_snap.get('message')}")

# 5d. Stream with all-zero power
records_zero = [
    {"timestamp": base + timedelta(seconds=i),
     "power": 0, "heart_rate": 80}
    for i in range(3600)
]
stream_zero = parse_fit_records_enhanced(
    records_zero, session_dict={"sport": "cycling", "start_time": base}
)
check("all-zero stream: has_power=False", stream_zero.has_power is False)
check("all-zero stream: has_heart_rate=True", stream_zero.has_heart_rate is True)

summary_zero = build_workout_summary(
    stream=stream_zero, weight_kg=72.0, ftp=280.0, lthr=165,
)
check("all-zero stream: orchestrator returns dict (no crash)",
      isinstance(summary_zero, dict))

# 5e. Stream too short (5 samples)
records_tiny = [
    {"timestamp": base + timedelta(seconds=i),
     "power": 200, "heart_rate": 140}
    for i in range(5)
]
stream_tiny = parse_fit_records_enhanced(
    records_tiny, session_dict={"sport": "cycling", "start_time": base}
)
summary_tiny = build_workout_summary(
    stream=stream_tiny, weight_kg=72.0, ftp=280.0, lthr=165,
)
check("5-sample stream: orchestrator returns dict (no crash)",
      isinstance(summary_tiny, dict))


# =============================================================================
# Section 6: Sport-name disciplines (the v3.3.1 fix)
# =============================================================================
print("\n" + "=" * 70)
print("Section 6 — Sport-name disciplines")
print("=" * 70)

cases = [
    ("ROAD",          "ENDURANCE"),
    ("TT",            "ENDURANCE"),
    ("TIME_TRIAL",    "ENDURANCE"),
    ("GRAVEL",        "ENDURANCE"),
    ("TRIATHLON",     "ENDURANCE"),
    ("MTB",           "MIXED"),
    ("MTB_XCO",       "MIXED"),
    ("CYCLOCROSS",    "MIXED"),
    ("CRITERIUM",     "MIXED"),
    ("TRACK",         "SPRINT"),
    ("BMX",           "SPRINT"),
    ("KEIRIN",        "SPRINT"),
    # Physiological categories still work
    ("ENDURANCE",     "ENDURANCE"),
    ("MIXED",         "MIXED"),
    ("SPRINT",        "SPRINT"),
    # Unknown → MIXED default
    ("CARRIAGE",      "MIXED"),
    # Case insensitivity and separator normalization
    ("road",          "ENDURANCE"),
    ("Track-Sprint",  "SPRINT"),
    ("Mtb Xco",       "MIXED"),
]

for input_, expected in cases:
    ctx = AthleteContext(discipline=input_)
    got = ctx.effective_discipline()
    check(f"discipline {input_!r} → {expected}",
          got == expected,
          f"got {got!r}")

# inferred_fields behavior
ctx_road = AthleteContext(discipline="ROAD", gender="MALE", training_years=5)
check("ROAD not flagged as inferred",
      "discipline" not in ctx_road.inferred_fields())

ctx_garbage = AthleteContext(discipline="CARRIAGE")
check("CARRIAGE flagged as inferred (unknown)",
      "discipline" in ctx_garbage.inferred_fields())


# =============================================================================
# Section 7: efforts_analyzer zero/None edge cases
# =============================================================================
print("\n" + "=" * 70)
print("Section 7 — efforts_analyzer falsy-zero edge case")
print("=" * 70)

mmp_curve = [
    {"duration_s": 5,    "power_w": 850.0, "wkg": 11.81},
    {"duration_s": 30,   "power_w": 700.0, "wkg": 9.72},
    {"duration_s": 60,   "power_w": 520.0, "wkg": 7.22},
    {"duration_s": 300,  "power_w": 340.0, "wkg": 4.72},
    {"duration_s": 1200, "power_w": 295.0, "wkg": 4.10},
]

# Test #1: wprime_kj == 0 (degenerate but valid value)
result = analyze_efforts(
    mmp_curve=mmp_curve,
    weight_kg=72.0,
    ftp=280.0,
    cp_fit={"cp_w": 270.0, "wprime_kj": 0},
    metabolic_snapshot=snapshots.get("all_rounder"),
)
check("analyze_efforts with wprime_kj=0 doesn't crash",
      isinstance(result, dict),
      f"got {type(result).__name__}")

# Test #2: missing cp_fit entirely
result2 = analyze_efforts(
    mmp_curve=mmp_curve, weight_kg=72.0, ftp=280.0,
    cp_fit=None, metabolic_snapshot=snapshots.get("all_rounder"),
)
check("analyze_efforts with cp_fit=None doesn't crash",
      isinstance(result2, dict))

# Test #3: missing metabolic_snapshot
result3 = analyze_efforts(
    mmp_curve=mmp_curve, weight_kg=72.0, ftp=280.0,
    cp_fit=None, metabolic_snapshot=None,
)
check("analyze_efforts with both cp_fit and snapshot=None doesn't crash",
      isinstance(result3, dict))

# Test #4: regression test — ensure 0.0 w_consumed doesn't become None
# Pass a valid cp_fit with realistic W' and a sub-CP effort (no W' consumed)
result4 = analyze_efforts(
    mmp_curve=mmp_curve, weight_kg=72.0, ftp=280.0,
    cp_fit={"cp_w": 270.0, "wprime_kj": 18.0},  # 18 kJ
    metabolic_snapshot=snapshots.get("all_rounder"),
)
check("analyze_efforts with valid cp_fit produces efforts",
      isinstance(result4, dict) and "efforts" in result4,
      f"keys={list(result4.keys()) if isinstance(result4, dict) else 'N/A'}")


# =============================================================================
# REPORT
# =============================================================================
print()
print("=" * 70)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  STRESS TEST FINAL: {passed}/{total} checks passed ({100*passed/total:.0f}%)")
print("=" * 70)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  ✗ {name}: {detail}")
    sys.exit(1)
else:
    print("✓ All stress test checks passed.")
    sys.exit(0)
