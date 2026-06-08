#!/usr/bin/env python3
"""
Regression checks for profile_anchor_flow: the end-to-end thread
proposal -> anchor -> ride update.

Verifies:
  * build_anchor_from_proposal turns a confirmed proposal into a
    MeasuredProfile, with VLamax from the sprint and aerobic params from the
    CP fit; partial proposals yield a partial anchor with warnings (no
    fabricated values).
  * update_profile_from_ride HOLDS the anchor for non-maximal rides
    (anchor_held) and UPDATES the aerobic params for maximal rides, while
    keeping VLamax sticky at the anchor value.

Deterministic synthetic data; no FIT files required.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from engines.core.athlete_context import AthleteContext
from engines.core.athlete_physiological_prior import MeasuredProfile
from test_effort_extractor import extract_test_proposal
from engines.io.profile_anchor_flow import build_anchor_from_proposal, update_profile_from_ride

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))


def _flat(w, n):
    return [float(w)] * n


def _sprint(peak, n):
    out = []
    for i in range(n):
        out.append(peak * (0.4 + 0.3 * i) if i < 2 else peak * max(0.6, 1.0 - 0.03 * (i - 2)))
    return out + [40.0] * 5


ctx = AthleteContext(gender="MALE", training_years=20, discipline="SPRINT")

# =============================================================================
# 1. Confirmed proposal -> anchor
# =============================================================================
print("\n[1] build_anchor_from_proposal")

# A full-ish test: sprint + CP3 + CP6 + CP12 (maximal, steady)
day = (
    _flat(120, 400)
    + _sprint(1000, 16)
    + _flat(90, 200)
    + _flat(355, 180)        # CP3
    + _flat(90, 150)
    + _flat(320, 360)        # CP6
    + _flat(90, 150)
    + _flat(300, 720)        # CP12
)
prop = extract_test_proposal([{"file_id": "test", "power": day, "laps": None}])
anchor = build_anchor_from_proposal(
    prop, weight_kg=90, measured_on="2026-05-15", context=ctx, active_muscle_mass_kg=23.5
)
d = anchor.to_dict()
check("anchor status is anchored or partial", d["status"] in ("anchored", "partial"), f"status={d['status']}")
check("VLamax anchored from sprint", d["vlamax_source"] == "sprint" and d["profile"]["vlamax"] is not None,
      f"vlamax={d['profile']['vlamax'] if d['profile'] else None}")
check("anchor carries a MeasuredProfile", anchor.profile is not None and isinstance(anchor.profile, MeasuredProfile))

# A proposal with no sprint -> VLamax cannot be anchored, warning present.
no_sprint = _flat(120, 400) + _flat(300, 720) + _flat(320, 360)
prop_ns = extract_test_proposal([{"file_id": "ns", "power": no_sprint, "laps": None}])
anchor_ns = build_anchor_from_proposal(prop_ns, weight_kg=90, measured_on="2026-05-15", context=ctx)
check("no-sprint proposal -> VLamax not from sprint",
      anchor_ns.vlamax_source != "sprint",
      f"vlamax_source={anchor_ns.vlamax_source}")
check("no-sprint proposal warns about missing sprint or anchor",
      len(anchor_ns.warnings) > 0)

# =============================================================================
# 2. Ride update: hold vs update
# =============================================================================
print("\n[2] update_profile_from_ride")

lab_anchor = MeasuredProfile(measured_on="2025-05-05", vo2max=40.4, mlss_watts=228.0, vlamax=0.61, source="lab_test")

# 2a. Non-maximal ride (flat curve) -> anchor held, not corrupted.
non_max_mmp = {1: 444, 5: 413, 15: 358, 60: 284, 300: 239, 1200: 220}
out_hold = update_profile_from_ride(lab_anchor, non_max_mmp, weight_kg=70, as_of="2026-05-09", context=ctx)
check("non-maximal ride -> anchor_held", out_hold.get("status") == "anchor_held", f"status={out_hold.get('status')}")
check("anchor_held keeps VO2max near anchor (not collapsed)",
      out_hold.get("estimated_vo2max") is not None and out_hold["estimated_vo2max"] >= 35.0,
      f"vo2={out_hold.get('estimated_vo2max')}")

# 2b. Maximal ride -> aerobic updates, VLamax stays anchored.
max_mmp = {1: 1050, 5: 1000, 15: 730, 60: 495, 180: 355, 360: 315, 720: 308, 1200: 285}
out_upd = update_profile_from_ride(lab_anchor, max_mmp, weight_kg=90, as_of="2026-05-09", context=ctx)
check("maximal ride -> success", out_upd.get("status") == "success", f"status={out_upd.get('status')}")
check("maximal ride -> VO2max is physiological (35-65)",
      out_upd.get("estimated_vo2max") is not None and 35.0 <= out_upd["estimated_vo2max"] <= 65.0,
      f"vo2={out_upd.get('estimated_vo2max')}")
check("maximal ride -> VLamax held at anchor (sticky)",
      out_upd.get("vlamax_held_from_anchor") is True
      and abs(out_upd.get("estimated_vlamax_mmol_L_s", 0) - 0.61) < 0.01,
      f"vlamax={out_upd.get('estimated_vlamax_mmol_L_s')}")
check("maximal ride update reports method + anchor age",
      out_upd.get("update_method") == "deterministic_fit_with_vlamax_prior"
      and out_upd.get("anchor_age_days") is not None,
      f"age={out_upd.get('anchor_age_days')}")

# 2c. Priors were applied and aged.
pa = out_upd.get("priors_applied", {})
check("priors applied carry aged std (> base)",
      "vlamax" in pa and pa["vlamax"]["std"] > 0.06,
      f"vlamax_std={pa.get('vlamax', {}).get('std')}")


print("\n" + "=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  {passed}/{total} anchor-flow checks passed")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL {name}: {detail}")
    sys.exit(1)

print("PASS Profile anchor-flow regressions passed.")
sys.exit(0)
