#!/usr/bin/env python3
"""
Test: v3.3.2 — MMP quality + display gating + time window
==========================================================

Validates:
  1. analyze_mmp_quality detects identical_plateau, sprint_outlier,
     flat_long_region, non_monotonic, rolling_window_redundant
  2. clean_mmp drops plateau and rolling-window-redundant by default
     and keeps the rest as warnings
  3. MetabolicProfiler.generate_metabolic_snapshot(clean_mmp_first=True)
     includes the audit in the output
  4. filter_mmp_by_window correctly applies a 90-day cutoff
  5. should_display + mask_low_confidence implement the analysis-platform-style gate
  6. Real Diego data: confirms quality_score is low and explains why
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datetime import date, timedelta

from engines import (
    analyze_mmp_quality, clean_mmp, filter_mmp_by_window,
    MetabolicProfiler, AthleteContext,
    should_display, mask_low_confidence,
)


results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if not ok and detail else ""))


# =============================================================================
# 1. Plateau detection
# =============================================================================
print("\n[1] Plateau detection")

mmp_with_plateaus = {60: 400, 120: 350, 600: 300, 720: 300, 1200: 300, 1800: 280}
r = analyze_mmp_quality(mmp_with_plateaus)
cats = {i.category for i in r.issues}
check("plateau detected", "identical_plateau" in cats)
plateau_issues = [i for i in r.issues if i.category == "identical_plateau"]
check("at least 2 plateau pairs flagged", len(plateau_issues) >= 2)
check("quality_score reduced", r.quality_score < 1.0)


# =============================================================================
# 2. Sprint outlier detection
# =============================================================================
print("\n[2] Sprint outlier detection")

# Sprint 1500W with MLSS proxy ~280W → ratio ~5.4 (above threshold 3.5)
mmp_sprint_outlier = {5: 1500, 60: 600, 300: 380, 1200: 280, 3600: 260}
r = analyze_mmp_quality(mmp_sprint_outlier)
cats = {i.category for i in r.issues}
check("sprint outlier detected", "sprint_outlier" in cats)

# Normal sprint should not trigger
normal_mmp = {5: 800, 60: 450, 300: 340, 1200: 280, 3600: 260}
r2 = analyze_mmp_quality(normal_mmp)
check("normal sprint not flagged", "sprint_outlier" not in {i.category for i in r2.issues})


# =============================================================================
# 3. Non-monotonic detection
# =============================================================================
print("\n[3] Non-monotonic detection")

# Power INCREASES with duration → physically impossible
bad_mmp = {60: 300, 120: 320}
r = analyze_mmp_quality(bad_mmp)
check("non-monotonic detected", any(i.category == "non_monotonic" for i in r.issues))


# =============================================================================
# 4. Rolling-window redundant cluster (requires source-file info)
# =============================================================================
print("\n[4] Rolling-window redundant cluster")

# 6 long-duration anchors from a single file = obvious rolling redundancy
mmp = {60: 400, 300: 350, 600: 320, 720: 315, 900: 310,
       1200: 305, 1800: 295, 3600: 280, 5400: 270}
samples = [
    {"duration_s": 60,   "power_w": 400, "filename": "interval-set.fit", "date": "2026-04-01"},
    {"duration_s": 300,  "power_w": 350, "filename": "interval-set.fit", "date": "2026-04-01"},
    # 6 long-duration from one ride
    {"duration_s": 600,  "power_w": 320, "filename": "long-ride.fit", "date": "2026-05-10"},
    {"duration_s": 720,  "power_w": 315, "filename": "long-ride.fit", "date": "2026-05-10"},
    {"duration_s": 900,  "power_w": 310, "filename": "long-ride.fit", "date": "2026-05-10"},
    {"duration_s": 1200, "power_w": 305, "filename": "long-ride.fit", "date": "2026-05-10"},
    {"duration_s": 1800, "power_w": 295, "filename": "long-ride.fit", "date": "2026-05-10"},
    {"duration_s": 3600, "power_w": 280, "filename": "long-ride.fit", "date": "2026-05-10"},
    {"duration_s": 5400, "power_w": 270, "filename": "long-ride.fit", "date": "2026-05-10"},
]
r = analyze_mmp_quality(mmp, samples)
cats = {i.category for i in r.issues}
check("rolling_window_redundant detected", "rolling_window_redundant" in cats)
check("source files counted", r.total_source_files == 2)


# =============================================================================
# 5. Cleaning drops plateaus and rolling-redundant
# =============================================================================
print("\n[5] Cleaning behavior")

dirty_mmp = {
    5: 950, 60: 470, 300: 330, 600: 305,
    720: 305,  # plateau with 600
    900: 305,  # plateau extension
    1200: 295, 1500: 290, 1800: 285, 3600: 270,
}
dirty_samples = [
    {"duration_s": 5,    "power_w": 950, "filename": "a.fit", "date": "2026-04-01"},
    {"duration_s": 60,   "power_w": 470, "filename": "a.fit", "date": "2026-04-01"},
    {"duration_s": 300,  "power_w": 330, "filename": "b.fit", "date": "2026-04-15"},
    # Single source for all the long anchors
    {"duration_s": 600,  "power_w": 305, "filename": "long.fit", "date": "2026-05-10"},
    {"duration_s": 720,  "power_w": 305, "filename": "long.fit", "date": "2026-05-10"},
    {"duration_s": 900,  "power_w": 305, "filename": "long.fit", "date": "2026-05-10"},
    {"duration_s": 1200, "power_w": 295, "filename": "long.fit", "date": "2026-05-10"},
    {"duration_s": 1500, "power_w": 290, "filename": "long.fit", "date": "2026-05-10"},
    {"duration_s": 1800, "power_w": 285, "filename": "long.fit", "date": "2026-05-10"},
    {"duration_s": 3600, "power_w": 270, "filename": "long.fit", "date": "2026-05-10"},
]

clean, audit = clean_mmp(dirty_mmp, dirty_samples)
check("clean_mmp returns dict + audit", isinstance(clean, dict) and isinstance(audit, dict))
check("original_anchors recorded", audit["original_anchors"] == 10)
check("anchors actually dropped", audit["cleaned_anchors"] < audit["original_anchors"])
check("dropped list populated", len(audit["dropped"]) > 0)

# Sprint should NOT have been touched (only flagged in kept_warnings if outlier; here it's fine)
check("sprint 5s kept", 5 in clean)


# =============================================================================
# 6. clean_mmp_first integrated in MetabolicProfiler
# =============================================================================
print("\n[6] MetabolicProfiler with clean_mmp_first")

ctx = AthleteContext(gender="MALE", training_years=5, discipline="ROAD")
profiler = MetabolicProfiler(weight=72, context=ctx)

snap = profiler.generate_metabolic_snapshot(
    dirty_mmp,
    mmp_samples=dirty_samples,
    clean_mmp_first=True,
)
check("snapshot has mmp_quality audit", "mmp_quality" in snap)
check("mmp_quality has analysis subkey", "analysis" in snap["mmp_quality"])
check("mmp_quality has dropped list", "dropped" in snap["mmp_quality"])

# Without cleaning, no audit
snap_no_clean = profiler.generate_metabolic_snapshot(dirty_mmp)
check("snapshot WITHOUT clean_mmp_first has no audit", "mmp_quality" not in snap_no_clean)


# =============================================================================
# 7. filter_mmp_by_window
# =============================================================================
print("\n[7] filter_mmp_by_window")

today = date(2026, 5, 20)
samples_with_old = [
    {"duration_s": 60,  "power_w": 450, "date": "2026-05-15"},   # recent
    {"duration_s": 300, "power_w": 350, "date": "2026-05-01"},   # recent
    {"duration_s": 600, "power_w": 320, "date": "2025-11-01"},   # old (200+ days)
    {"duration_s": 1200, "power_w": 290, "date": "2025-08-15"},  # very old
    {"duration_s": 60,  "power_w": 420, "date": "2024-12-01"},   # old; max should ignore
]

mmp_90d, kept = filter_mmp_by_window(samples_with_old, today=today, window_days=90)
check("filter returns dict + kept list", isinstance(mmp_90d, dict) and isinstance(kept, list))
check("recent samples kept (60s, 300s)", set(mmp_90d.keys()) == {60, 300})
check("old samples excluded", 600 not in mmp_90d and 1200 not in mmp_90d)
check("kept count matches", len(kept) == 2)

# Test with date object instead of ISO string
samples_with_date_objs = [
    {"duration_s": 60, "power_w": 400, "date": today - timedelta(days=30)},
    {"duration_s": 300, "power_w": 350, "date": today - timedelta(days=180)},
]
mmp_d, _ = filter_mmp_by_window(samples_with_date_objs, today=today, window_days=90)
check("date objects accepted", 60 in mmp_d and 300 not in mmp_d)

# Test with no samples in window
old_only = [{"duration_s": 60, "power_w": 400, "date": "2025-01-01"}]
mmp_empty, _ = filter_mmp_by_window(old_only, today=today, window_days=90)
check("empty window returns empty MMP", len(mmp_empty) == 0)


# =============================================================================
# 8. Display gating
# =============================================================================
print("\n[8] Display gating")

# should_display
check("should_display(0.80) → True", should_display(0.80) is True)
check("should_display(0.20) → False", should_display(0.20) is False)
check("should_display(None) → False", should_display(None) is False)
check("should_display(0.50, threshold=0.4) → True", should_display(0.50, threshold=0.4) is True)

# mask_low_confidence
payload = {
    "confidence_score": 0.14,
    "estimated_vo2max": 50.5,
    "mlss_power_watts": 255,
    "fatmax_power_watts": 160,
    "context_used": {"gender": "MALE"},
}
masked = mask_low_confidence(payload)
check("low-conf vo2max masked", masked["estimated_vo2max"] == "—")
check("low-conf mlss masked", masked["mlss_power_watts"] == "—")
check("non-numeric fields kept", masked["context_used"]["gender"] == "MALE")
check("_display meta added", "_display" in masked)
check("_display.shown is False", masked["_display"]["shown"] is False)
check("hidden_fields listed", "estimated_vo2max" in masked["_display"]["hidden_fields"])

# High conf → no masking
payload_high = dict(payload)
payload_high["confidence_score"] = 0.85
masked_high = mask_low_confidence(payload_high)
check("high-conf vo2max kept", masked_high["estimated_vo2max"] == 50.5)
check("high-conf _display.shown is True", masked_high["_display"]["shown"] is True)

# Original payload not mutated
check("input payload not mutated", payload["estimated_vo2max"] == 50.5)


# =============================================================================
# 9. Real Diego data — sanity
# =============================================================================
print("\n[9] Real Diego data — quality classification")

import json
diego_path = Path("/mnt/user-data/uploads/diego.json")
if diego_path.exists():
    with open(diego_path) as f:
        diego = json.load(f)
    r = analyze_mmp_quality(diego["mmp"], diego.get("mmp_samples"))
    cats = {i.category for i in r.issues}
    print(f"    Diego quality_score: {r.quality_score:.2f} ({r.classification})")
    print(f"    Issues found: {sorted(cats)}")
    check("Diego: plateaus identified", "identical_plateau" in cats)
    check("Diego: rolling-window cluster identified", "rolling_window_redundant" in cats)
    check("Diego: sprint outlier identified", "sprint_outlier" in cats)
    check("Diego: classification is 'fair' or 'poor'",
          r.classification in {"fair", "poor"})


# =============================================================================
# REPORT
# =============================================================================
print()
print("=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  v3.3.2 FEATURES: {passed}/{total} checks passed ({100*passed/total:.0f}%)")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  ✗ {name}: {detail}")
    sys.exit(1)
else:
    print("✓ All v3.3.2 feature checks passed.")
    sys.exit(0)
