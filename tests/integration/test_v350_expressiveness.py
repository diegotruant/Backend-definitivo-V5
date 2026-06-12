#!/usr/bin/env python3
"""
Test: v3.5.0 — Expressiveness gate + Mader constants override
==============================================================

Validates the two methodological-honesty fixes triggered by the review:

  1. **Expressiveness gate**: when MMP coverage is missing for a parameter,
     the corresponding output is set to None (not silently distorted).
     Specifically:
       - no anchor in 20-60s window → vlamax masked, fatmax masked,
         phenotype masked, combustion_curve masked
       - no anchor in 1200-3600s window → mlss masked, fatmax masked,
         vo2max masked, zones masked
       - no anchor in 180-480s window → vo2max masked
  
  2. **Mader constants override**: profiler accepts custom MaderConstants
     and reports them in the output for reproducibility, addressing the
     dogmatic-constants critique.

The unmasked estimates are still available under `unmasked_estimates`
for audit / debugging.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engines import (
    MetabolicProfiler, MaderConstants, AthleteContext,
    ExpressivenessReport,
)


results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if not ok and detail else ""))


ctx = AthleteContext(gender="MALE", training_years=5, discipline="ROAD")


# =============================================================================
# 1. ExpressivenessReport API
# =============================================================================
print("\n[1] ExpressivenessReport detection")

# Fully expressive
r = ExpressivenessReport.from_mmp({5: 800, 60: 450, 300: 320, 1200: 280})
check("expressive MMP: fully_expressive", r.fully_expressive)
check("expressive MMP: vlamax_reliable", r.vlamax_reliable)
check("expressive MMP: vo2max_reliable", r.vo2max_reliable)
check("expressive MMP: mlss_reliable", r.mlss_reliable)

# Missing glycolytic window (review's main scenario)
r = ExpressivenessReport.from_mmp({300: 340, 1200: 290, 3600: 270})
check("flat MMP: NOT fully_expressive", not r.fully_expressive)
check("flat MMP: vlamax NOT reliable", not r.vlamax_reliable)
check("flat MMP: mlss reliable (threshold present)", r.mlss_reliable)
check("flat MMP: vo2max reliable (vo2max window present)", r.vo2max_reliable)

# Missing threshold window
r = ExpressivenessReport.from_mmp({5: 800, 60: 450, 300: 320})
check("no-threshold MMP: mlss NOT reliable", not r.mlss_reliable)
check("no-threshold MMP: vo2max NOT reliable (needs threshold corroboration)",
      not r.vo2max_reliable)

# Empty
r = ExpressivenessReport.from_mmp({})
check("empty MMP: nothing reliable",
      not r.vlamax_reliable and not r.mlss_reliable)

# to_dict shape
r = ExpressivenessReport.from_mmp({5: 800, 60: 450, 1200: 280})
d = r.to_dict()
check("to_dict has all required keys",
      {"coverage", "reliability", "n_anchors",
       "missing_windows", "unreliable_parameters",
       "fully_expressive", "tier"}.issubset(d.keys()))
check("to_dict tier is REFERENCE", d["tier"] == "REFERENCE")


# =============================================================================
# 2. Expressiveness gate in MetabolicProfiler — flat MMP
# =============================================================================
print("\n[2] Gate behavior on FLAT MMP (review's exact scenario)")

p = MetabolicProfiler(weight=72, context=ctx)
# Athlete who only did Z2 endurance — no short anchors
mmp_flat = {300: 340, 600: 300, 1200: 290, 1800: 285, 3600: 270}
snap = p.generate_metabolic_snapshot(mmp_flat)

check("status success", snap.get("status") == "success")
check("vlamax masked to None", snap.get("estimated_vlamax_mmol_L_s") is None,
      f"got {snap.get('estimated_vlamax_mmol_L_s')}")
check("phenotype masked", snap.get("metabolic_phenotype") is None)
check("fatmax masked (depends on vlamax)", snap.get("fatmax_power_watts") is None)
check("combustion_curve masked", snap.get("combustion_curve") is None)
check("mlss preserved (threshold present)", snap.get("mlss_power_watts") is not None)
check("vo2max preserved (window present)", snap.get("estimated_vo2max") is not None)
check("confidence capped at 0.40", snap["confidence_score"] <= 0.40)

# Audit data
check("expressiveness in output", "expressiveness" in snap)
check("missing_windows reported",
      len(snap["expressiveness"]["missing_windows"]) > 0)
check("vlamax in unreliable_parameters",
      "vlamax" in snap["expressiveness"]["unreliable_parameters"])

# CRITICAL: unmasked estimates preserved for audit
check("unmasked_estimates present", "unmasked_estimates" in snap)
check("unmasked vlamax is a number",
      isinstance(snap["unmasked_estimates"]["estimated_vlamax_mmol_L_s"], (int, float)))


# =============================================================================
# 3. Gate behavior — no threshold window
# =============================================================================
print("\n[3] Gate behavior on NO-THRESHOLD MMP")

mmp_short = {5: 950, 30: 620, 60: 470, 180: 380}  # missing 1200+s
snap = p.generate_metabolic_snapshot(mmp_short)

check("vlamax preserved (sprint anchor present)",
      snap.get("estimated_vlamax_mmol_L_s") is not None)
check("mlss masked (no threshold anchor)", snap.get("mlss_power_watts") is None)
check("vo2max masked (needs threshold corroboration)",
      snap.get("estimated_vo2max") is None)
check("zones masked", snap.get("zones") is None)


# =============================================================================
# 4. Gate behavior — fully expressive MMP
# =============================================================================
print("\n[4] Gate behavior on FULLY EXPRESSIVE MMP")

mmp_good = {5: 950, 30: 620, 60: 470, 300: 340, 1200: 290, 3600: 270}
snap = p.generate_metabolic_snapshot(mmp_good)

check("all primary outputs populated",
      snap["estimated_vo2max"] is not None and
      snap["estimated_vlamax_mmol_L_s"] is not None and
      snap["mlss_power_watts"] is not None and
      snap["fatmax_power_watts"] is not None)
check("expressiveness.fully_expressive True",
      snap["expressiveness"]["fully_expressive"])
check("no missing_windows",
      len(snap["expressiveness"]["missing_windows"]) == 0)


# =============================================================================
# 5. Mader constants override
# =============================================================================
print("\n[5] Mader constants override")

# Default constants
p_default = MetabolicProfiler(weight=72, context=ctx)
check("default ks1 = 0.0631", p_default.const.ks1 == 0.0631)
check("default _source label", p_default.const._source == "mader_heck_1986_default")

# Custom constants
custom = MaderConstants(ks1=0.0635, ks2=1.30, _source="nolte_2025_review")
p_custom = MetabolicProfiler(weight=72, context=ctx, mader_constants=custom)
check("custom ks1 used", p_custom.const.ks1 == 0.0635)
check("custom ks2 used", p_custom.const.ks2 == 1.30)
check("custom source preserved", p_custom.const._source == "nolte_2025_review")

# Constants tracked in output
snap = p_custom.generate_metabolic_snapshot(mmp_good)
check("mader_constants in output context",
      "mader_constants" in snap["context_used"])
check("output reports custom ks1",
      snap["context_used"]["mader_constants"]["ks1"] == 0.0635)
check("output reports custom source",
      snap["context_used"]["mader_constants"]["source"] == "nolte_2025_review")

# MaderConstants to_dict
d = custom.to_dict()
check("MaderConstants.to_dict has source", "source" in d)
check("MaderConstants.to_dict has ks1 and ks2",
      "ks1" in d and "ks2" in d)


# =============================================================================
# 6. Gate combined with clean_mmp_first
# =============================================================================
print("\n[6] Gate combined with clean_mmp_first")

# MMP with both artifacts AND missing glycolytic window
mmp_bad = {
    300: 340,
    600: 300,
    720: 300,   # plateau
    1200: 290,
    1800: 285,
    3600: 270,
}

snap = p.generate_metabolic_snapshot(mmp_bad, clean_mmp_first=True)
check("clean + gate: both audits present",
      "mmp_quality" in snap and "expressiveness" in snap)
check("vlamax still masked (cleaning doesn't add anchors)",
      snap["estimated_vlamax_mmol_L_s"] is None)


# =============================================================================
# 7. Edge case: very small MMP
# =============================================================================
print("\n[7] Edge cases")

# 1 anchor → error path
snap = p.generate_metabolic_snapshot({60: 400})
check("1-anchor MMP → error", snap.get("status") == "error")

# 3 anchors all in glycolytic window only
snap = p.generate_metabolic_snapshot({30: 700, 45: 550, 60: 470})
check("3-glycolytic-only MMP doesn't crash", isinstance(snap, dict))


# =============================================================================
# REPORT
# =============================================================================


# =============================================================================
# 8. protocol_completeness (new in v3.5.0)
# =============================================================================
print("\n[8] protocol_completeness — onboarding planner")

from engines import protocol_completeness, QualifiedAnchor

# No anchors → "very_low" current, "high" post
r = protocol_completeness(available_durations_s=[])
check("no anchors → very_low current confidence",
      r.expected_current_confidence == "very_low")
check("no anchors → high post-protocol confidence",
      r.expected_post_protocol_confidence == "high")
check("no anchors → 0% completeness", r.completeness_pct == 0)
check("no anchors → 4 missing windows", len(r.missing_windows) == 4)
check("no anchors → at least 1 recommended test",
      len(r.recommended_tests) >= 1)

# Athlete with sprint and threshold (typical first-test combo)
anchors = [
    QualifiedAnchor(5, 900, 1.0, "sprint_test"),
    QualifiedAnchor(1200, 280, 1.0, "ftp_20min"),
]
r = protocol_completeness(qualified_anchors=anchors)
check("sprint + threshold → 50% complete",
      r.completeness_pct == 50,
      f"got {r.completeness_pct}%")
check("missing glycolytic + vo2max",
      set(r.missing_windows) == {"glycolytic", "vo2max"})

# Fully covered athlete
full = [
    QualifiedAnchor(5, 900, 1.0, "sprint_test"),
    QualifiedAnchor(30, 620, 1.0, "sprint_set"),
    QualifiedAnchor(360, 320, 1.0, "cp6"),
    QualifiedAnchor(1200, 280, 1.0, "ftp_20min"),
]
r = protocol_completeness(qualified_anchors=full)
check("fully covered → 100%", r.completeness_pct == 100)
check("fully covered → no recommendations",
      len(r.recommended_tests) == 0)
check("fully covered → high current confidence",
      r.expected_current_confidence == "high")

# Output contract
d = r.to_dict()
check("to_dict has expected keys",
      {"covered_windows", "missing_windows", "completeness_pct",
       "expected_current_confidence", "expected_post_protocol_confidence",
       "recommended_tests", "tier"}.issubset(d.keys()))

# Total duration
r = protocol_completeness(available_durations_s=[])
check("total_duration_min_to_complete > 0 when missing windows",
      r.total_duration_min_to_complete > 0)

print()
print("=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  v3.5.0 EXPRESSIVENESS GATE: {passed}/{total} ({100*passed/total:.0f}%)")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  ✗ {name}: {detail}")
    sys.exit(1)
else:
    print("✓ All v3.5.0 checks passed.")
    sys.exit(0)
