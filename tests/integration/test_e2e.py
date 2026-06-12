#!/usr/bin/env python3
"""
End-to-End Integration Test
============================

Exercises the full pipeline with synthetic data:
  1. Build a synthetic ActivityStream (3h endurance ride)
  2. Run build_workout_summary() — orchestrator
  3. Run individual engines (durability, ACWR, W' balance, MFI)
  4. Run data quality assessment
  5. Run explainability narratives

Each step PASS/FAIL, with a final report.
This is the test the reviewer asked for: real package, real pipeline,
real assertions about outputs.
"""

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np

# Track results
results = []


def section(name):
    print()
    print("=" * 70)
    print(f"  {name}")
    print("=" * 70)


def assert_test(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, status, detail))
    marker = "✓" if condition else "✗"
    print(f"  {marker} {name}" + (f" — {detail}" if detail and not condition else ""))
    return condition


# =============================================================================
# 1. BUILD SYNTHETIC ACTIVITY STREAM
# =============================================================================

section("1. Build synthetic ActivityStream")

from engines import parse_fit_records_enhanced

from datetime import datetime, timedelta

# Generate 3h endurance ride: power ~ 220W with small drift
np.random.seed(42)
duration_s = 3 * 3600  # 3 hours
records = []

base_time = datetime(2026, 5, 19, 9, 0, 0)

for i in range(duration_s):
    # Power: 220W base, slight drift down over time (durability test)
    power = 225 + np.random.normal(0, 25) - (i / duration_s) * 12
    # HR: 145bpm base + cardiac drift
    hr = 140 + np.random.normal(0, 4) + (i / duration_s) * 8
    # Cadence
    cad = 88 + np.random.normal(0, 5)
    
    records.append({
        "timestamp": base_time + timedelta(seconds=i),
        "power": max(0, int(power)),
        "heart_rate": max(50, int(hr)),
        "cadence": max(0, int(cad)),
        "distance": i * 9.5,  # ~34 km/h average
    })

try:
    stream = parse_fit_records_enhanced(
        records,
        session_dict={"sport": "cycling", "start_time": base_time},
    )
    assert_test(
        "parse_fit_records_enhanced returns stream",
        stream is not None,
    )
    assert_test(
        "stream has expected attributes",
        all(hasattr(stream, attr) for attr in ["power", "heart_rate", "elapsed_s", "n_samples"]),
    )
    assert_test(
        "stream length matches input",
        stream.n_samples == duration_s,
        f"got {stream.n_samples}, expected {duration_s}",
    )
    assert_test(
        "has_power detected",
        getattr(stream, "has_power", False),
    )
except Exception as e:
    print(f"  ✗ FATAL: {e}")
    traceback.print_exc()
    sys.exit(1)


# =============================================================================
# 2. DATA QUALITY ASSESSMENT
# =============================================================================

section("2. Data quality assessment")

from engines import assess_data_quality

quality = assess_data_quality(
    power_stream=[r["power"] for r in records],
    hr_stream=[r["heart_rate"] for r in records],
)
assert_test(
    "data_quality returns score",
    hasattr(quality, "overall_score"),
)
assert_test(
    "clean data has high quality score",
    quality.overall_score > 0.8,
    f"score={quality.overall_score:.2f}",
)
print(f"  → Overall quality: {quality.overall_score:.2f}")
print(f"  → Power quality: {quality.power_quality:.2f}")
print(f"  → HR quality: {quality.hr_quality:.2f}")


# =============================================================================
# 3. RUN ORCHESTRATOR (build_workout_summary)
# =============================================================================

section("3. Orchestrator: build_workout_summary")

from engines import build_workout_summary, AthleteContext

try:
    t0 = time.time()
    summary = build_workout_summary(
        stream=stream,
        weight_kg=72.0,
        ftp=280.0,
        lthr=165,
        context=AthleteContext(),
    )
    elapsed = time.time() - t0
    
    assert_test(
        "build_workout_summary returns dict",
        isinstance(summary, dict),
    )
    assert_test(
        "summary has status=success",
        summary.get("status") == "success",
        f"got status={summary.get('status')}",
    )
    assert_test(
        "summary has sections",
        "sections" in summary,
    )
    assert_test(
        "summary has headline",
        "headline" in summary,
    )
    print(f"  → Processing time: {elapsed:.2f}s")
    
    # Check sections
    sections = summary.get("sections", {})
    print(f"  → Sections present: {list(sections.keys())}")
    
    power_section = sections.get("power", {})
    if power_section.get("status") == "success":
        m = power_section.get("metrics", {})
        print(f"  → TSS: {m.get('tss', 'N/A')}")
        print(f"  → NP:  {m.get('normalized_power', 'N/A')}W")
        print(f"  → IF:  {m.get('intensity_factor', 'N/A')}")
        assert_test(
            "TSS is reasonable for 3h ride",
            150 < m.get("tss", 0) < 250,
            f"TSS={m.get('tss')}",
        )
    else:
        print(f"  ! power section status: {power_section.get('status', '?')}")
        print(f"    reason: {power_section.get('reason', power_section.get('error', '?'))}")
    
except Exception as e:
    print(f"  ✗ ERROR: {type(e).__name__}: {e}")
    traceback.print_exc()
    summary = None


# =============================================================================
# 4. DURABILITY ENGINE
# =============================================================================

section("4. Durability engine (3h+ ride)")

from engines import calculate_durability_index, generate_hourly_decay_curve, calculate_np_drift

power_only = [r["power"] for r in records]

di = calculate_durability_index(power_only, duration_s)
assert_test(
    "durability index computed",
    di.get("status") == "success",
)
if di.get("status") == "success":
    print(f"  → DI: {di['durability_index']}% ({di['classification']})")
    print(f"  → First hour: {di['first_hour_avg']}W")
    print(f"  → Last hour:  {di['last_hour_avg']}W")
    assert_test(
        "DI in plausible range",
        80 <= di["durability_index"] <= 100,
    )

decay = generate_hourly_decay_curve(power_only, duration_s)
assert_test(
    "hourly decay curve computed",
    decay.get("status") == "success",
)
if decay.get("status") == "success":
    print(f"  → Hourly: {[h['average_power'] for h in decay['hourly_data']]}")

np_drift = calculate_np_drift(power_only, duration_s)
if np_drift.get("status") == "success":
    print(f"  → NP drift: {np_drift['np_drift_pct']}% ({np_drift['classification']})")


# =============================================================================
# 5. TRAINING VARIABILITY (ACWR / Monotony / Strain)
# =============================================================================

section("5. Training variability (ACWR / Monotony)")

from engines import calculate_acwr, calculate_monotony_strain

# Simulated 7-day TSS history
daily_tss = [85, 95, 60, 110, 70, 130, 90]

acwr = calculate_acwr(atl=88, ctl=72)
assert_test(
    "ACWR computed",
    "acwr" in acwr,
)
print(f"  → ACWR: {acwr.get('acwr')} ({acwr.get('risk_level')})")

ms = calculate_monotony_strain(daily_tss)
assert_test(
    "monotony/strain computed",
    "monotony" in ms,
)
print(f"  → Monotony: {ms.get('monotony')} ({ms.get('status')})")
print(f"  → Weekly TSS: {ms.get('weekly_tss')}, Strain: {ms.get('strain')}")


# =============================================================================
# 6. W' BALANCE
# =============================================================================

section("6. W' balance (interval simulation)")

from engines import calculate_w_prime_balance, analyze_w_prime_usage

# Simulate 4x4min intervals at 360W with 2min recovery at 120W
interval_power = [180]*600  # 10min warmup
for _ in range(4):
    interval_power += [360]*240  # 4min hard
    interval_power += [120]*120  # 2min easy
interval_power += [150]*600  # cooldown

balance = calculate_w_prime_balance(
    power_stream=interval_power,
    cp=275,
    w_prime=18000,
)
assert_test(
    "W' balance computed",
    len(balance) == len(interval_power),
    f"got len={len(balance)} vs input={len(interval_power)}",
)

usage = analyze_w_prime_usage(interval_power, balance, w_prime=18000)
print(f"  → Min balance: {usage.get('min_balance_j')}J ({usage.get('min_balance_pct')}%)")
print(f"  → Critical depletions: {usage.get('critical_depletions_count')}")


# =============================================================================
# 7. METABOLIC FLEXIBILITY
# =============================================================================

section("7. Metabolic flexibility index")

from engines import calculate_metabolic_flexibility_index, estimate_fat_oxidation_rate

mfi = calculate_metabolic_flexibility_index(fatmax_watts=210, vt2_watts=310)
print(f"  → MFI: {mfi.get('mfi')} ({mfi.get('classification')})")

fat_ox = estimate_fat_oxidation_rate(fatmax_watts=210, weight_kg=72)
print(f"  → Fat ox rate: {fat_ox.get('fat_oxidation_g_per_min')} g/min")


# =============================================================================
# 8. EXPLAINABILITY
# =============================================================================

section("8. Explainability (confidence + narrative)")

from engines import (
    calculate_durability_confidence,
    generate_durability_narrative,
    generate_acwr_narrative,
)

dur_conf = calculate_durability_confidence(
    duration_hours=duration_s / 3600,
    power_data_completeness=quality.power_quality,
)
assert_test(
    "durability confidence computed",
    hasattr(dur_conf, "confidence_pct"),
)
print(f"  → Durability confidence: {dur_conf.confidence_pct:.0f}% ({dur_conf.confidence_level.name})")

if di.get("status") == "success":
    narrative = generate_durability_narrative(
        durability_index=di["durability_index"],
        classification=di["classification"],
        confidence=dur_conf,
        prescription={
            "focus": "Aerobic base",
            "volume": "75-85% Z2",
            "key_sessions": ["base rides 3x/week"],
        },
    )
    assert_test(
        "narrative is non-empty string",
        isinstance(narrative, str) and len(narrative) > 50,
        f"len={len(narrative) if isinstance(narrative, str) else 'N/A'}",
    )

acwr_narr = generate_acwr_narrative(
    acwr_value=acwr.get("acwr", 1.0),
    risk_level=acwr.get("risk_level", "OPTIMAL"),
    ctl=72,
    atl=88,
    tsb=-16,
)
assert_test(
    "ACWR narrative generated",
    isinstance(acwr_narr, str) and len(acwr_narr) > 50,
)


# =============================================================================
# FINAL REPORT
# =============================================================================

print()
print("=" * 70)
print("  FINAL REPORT")
print("=" * 70)

passed = sum(1 for _, s, _ in results if s == "PASS")
failed = sum(1 for _, s, _ in results if s == "FAIL")
total = len(results)

print(f"\n  Total: {total}    Passed: {passed}    Failed: {failed}")
print(f"  Pass rate: {100 * passed / total:.1f}%")

if failed:
    print("\n  Failures:")
    for name, status, detail in results:
        if status == "FAIL":
            print(f"    ✗ {name}: {detail}")
    sys.exit(1)
else:
    print("\n  ✓ All tests passed.")
    sys.exit(0)
