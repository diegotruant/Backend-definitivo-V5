"""
Tests for the cross-validation (metabolic self-audit) engine.
Run: python3 test_cross_validation.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engines import cross_validate_metabolic_profile, MetabolicProfiler

_passed = 0
_failed = 0

def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ✓ {name}")
    else:
        _failed += 1
        print(f"  ✗ {name}")


def _fit(weight, mmp):
    prof = MetabolicProfiler(weight=weight)
    snap = prof.generate_metabolic_snapshot(mmp, expected_eta=0.23)
    unmasked = snap["unmasked_estimates"]
    return prof, snap, unmasked["estimated_vo2max"], unmasked["estimated_vlamax_mmol_L_s"]


# Real, well-formed profiles → must be coherent
GOOD = {
    "Omar":     (70, {5:661,15:527,30:438,60:401,120:390,300:352,600:302,1200:288,1800:279,3600:242}),
    "Alessio":  (56, {5:859,15:731,30:584,60:463,120:331,300:270,600:239,1200:227,1800:216,3600:202}),
    "Gabriele": (60, {5:987,15:694,30:498,60:439,120:307,300:260,600:246,1200:237,1800:223,3600:203}),
    "Diego":    (90, {5:1053,15:962,30:602,60:388,120:362,300:328,600:304,1200:280,1800:258,3600:255}),
}

print("Coherent real profiles (must pass):")
for name, (w, mmp) in GOOD.items():
    prof, snap, vo2, vla = _fit(w, mmp)
    cv = snap["cross_validation"]
    check(f"{name} not severely incoherent", cv["severity"] != "severe")
    check(f"{name} acceptable severity", cv["severity"] in ("none", "mild", "moderate"))
    check(f"{name} penalty bounded", cv["coherence_penalty"] <= 0.25)

print("\nAdrian (88kg ultra) — formerly a degenerate fit, now fixed by the")
print("aerobic-floor penalty + multi-start in the profiler:")
adrian_mmp = {5:700,15:639,30:470,60:386,120:369,300:351,600:305,1200:283,1800:272,3600:265}
prof, snap, vo2, vla = _fit(88, adrian_mmp)
cv = snap["cross_validation"]
check("Adrian VO2max now physiological (>40)", vo2 > 40.0)
check("Adrian VLamax now sane (<0.9)", vla < 0.9)
check("Adrian now coherent", cv["coherent"])

print("\nTiered MLSS mismatch (mild vs moderate):")
prof60 = MetabolicProfiler(weight=60)
# Mild: model MLSS only slightly above observed (~10%)
mmp_mild = {5: 500, 15: 450, 60: 380, 120: 340, 300: 300, 600: 280, 1200: 260, 1800: 255, 3600: 250}
_, snap_m, vo2_m, vla_m = _fit(60, mmp_mild)
cv_mild = snap_m["cross_validation"]
check("mild mismatch may stay coherent", cv_mild["severity"] in ("none", "mild"))
check("mild mismatch has recommended_action when warned",
      cv_mild["severity"] == "none" or cv_mild.get("recommended_action"))

print("\nSynthetic non-physical pair (forces the aerobic-floor check):")
# Hand Adrian's curve but a deliberately impossible VO2max/VLamax pair,
# bypassing the fitter, to confirm the cross-check still catches it.
prof = MetabolicProfiler(weight=88)
cv = cross_validate_metabolic_profile(prof, adrian_mmp, vo2max=30.0, vlamax=1.46, eta_base=0.23)
check("non-physical pair flagged incoherent", not cv.coherent)
check("non-physical pair → aerobic_floor or low-MLSS", 
      cv.suspected_outlier in ("nonphysical_fit_vo2max_too_low", "model_mlss_implausibly_low"))
check("non-physical pair penalty >= 0.4", cv.coherence_penalty >= 0.4)
prof = MetabolicProfiler(weight=60)
# Sub-maximal long effort
mmp_sub = {5:987,15:694,30:498,60:439,120:307,300:260,600:246,1200:175,1800:165,3600:150}
_, snap_sub, vo2, vla = _fit(60, mmp_sub)
cv = cross_validate_metabolic_profile(prof, mmp_sub, vo2, vla, eta_base=0.23)
check("sub-maximal long effort flagged", not cv.coherent)

# Curve inversion
mmp_inv = {5:987,15:694,30:498,60:439,120:307,300:260,600:246,1200:237,1800:250,3600:203}
cv = cross_validate_metabolic_profile(prof, mmp_inv, 53, 0.49)
check("curve inversion flagged", not cv.coherent)
check("monotonicity check ran", "monotonicity" in cv.checks_performed)

print("\nEdge cases:")
# No threshold anchor → no crash, reports it couldn't check
mmp_short = {5:900, 15:700, 60:450}
cv = cross_validate_metabolic_profile(prof, mmp_short, 55, 0.5)
check("missing threshold anchor → no crash", isinstance(cv.coherent, bool))
check("missing anchor noted in warnings", any("lacks" in w or "No cross" in w for w in cv.warnings))

# Serialization
cv = cross_validate_metabolic_profile(prof, GOOD["Omar"][1], 60, 0.49)
d = cv.to_dict()
check("to_dict returns tier", d.get("tier") == "MODEL")
check("to_dict has coherent flag", "coherent" in d)

print("\n" + "="*50)
print(f"  {_passed} passed, {_failed} failed")
print("="*50)
sys.exit(1 if _failed else 0)
