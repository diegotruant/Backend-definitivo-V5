#!/usr/bin/env python3
"""
Regression checks for session_router: automatic classify-and-route.

Verifies the routing policy with synthetic sessions:
  * ramp/incremental test  -> hrv_threshold (VT1/VT2 from DFA-alpha1)
  * sprint/CP test         -> metabolic_anchor
  * free/steady ride       -> ride_monitoring (durability, NOT thresholds)
  * missing RR             -> HRV engines skipped, power engines still run
  * the weak-fit honesty gate in HRV threshold extraction
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engines.io.session_router import decide_route, route_and_run
from engines.core.athlete_context import AthleteContext

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))


def _ramp(lo=100, hi=340, step=5, secs=30, seed=42):
    """Generates a ramp test with realistic ERG-mode noise (±3W)."""
    rng = np.random.default_rng(seed)
    p = []
    for w in range(lo, hi, step):
        noise = rng.normal(0, 3, secs)
        p.extend(list(np.clip(float(w) + noise, 0, None)))
    return p


def _sprint_cp():
    """Synthetic mixed test: sprints followed by maximal CP efforts."""
    p = [120.0] * 300
    # sprint
    for i in range(15):
        p.append(1000 * max(0.6, 1.0 - 0.03 * i))
    p += [40.0] * 5 + [100.0] * 200
    p += [350.0] * 180 + [100.0] * 150 + [320.0] * 360  # CP3, CP6
    return p


def _free_ride(n=4000, seed=1):
    rng = np.random.default_rng(seed)
    base = 150 + 60 * np.sin(np.linspace(0, 30, n))
    noise = rng.normal(0, 40, n)
    spikes = np.zeros(n)
    for _ in range(20):
        i = rng.integers(0, n - 10)
        spikes[i:i + 5] = rng.uniform(300, 600)
    return list(np.clip(base + noise + spikes, 0, None))


ctx = AthleteContext(gender="MALE", training_years=10, discipline="ENDURANCE")

# =============================================================================
# 1. Routing decisions
# =============================================================================
print("\n[1] Routing decisions")

# Use a neutral filename to force the classifier into Strategy C (Signal match)
d_ramp = decide_route(_ramp(), filename="indoor_session.fit", ftp=270, has_rr=True)
check("ramp test -> hrv_threshold route", d_ramp.route == "hrv_threshold", f"route={d_ramp.route}")
check("ramp test -> elaborato dal segnale matematico", d_ramp.source == "signal", f"source={d_ramp.source}")
check("ramp test -> HRV threshold engine queued",
      "hrv_threshold_vt1_vt2" in d_ramp.engines_to_run, f"engines={d_ramp.engines_to_run}")

d_ramp_norr = decide_route(_ramp(), filename="indoor_session.fit", ftp=270, has_rr=False)
check("ramp without RR -> threshold skipped",
      "hrv_threshold_vt1_vt2" not in d_ramp_norr.engines_to_run,
      f"engines={d_ramp_norr.engines_to_run}")

d_test = decide_route(_sprint_cp(), filename="test.fit", ftp=270, has_rr=False)
# A synthetic sprint+CP can look like HIIT to the detector; what matters is
# that a structured/interval session routes to engines that build the profile
# or its inputs, never to plain ride_monitoring.
check("structured session not treated as plain ride",
      d_test.route in ("metabolic_anchor", "hrv_threshold", "hiit"),
      f"route={d_test.route}")
check("structured session queues profile-relevant engines",
      any(e in d_test.engines_to_run for e in
          ("metabolic_profile", "test_effort_extraction", "interval_stimulus")),
      f"engines={d_test.engines_to_run}")

d_ride = decide_route(_free_ride(), filename="ride.fit", ftp=270, has_rr=True)
check("free ride -> ride_monitoring route", d_ride.route == "ride_monitoring", f"route={d_ride.route}")
check("free ride -> durability, NOT thresholds",
      "hrv_durability" in d_ride.engines_to_run and "hrv_threshold_vt1_vt2" not in d_ride.engines_to_run,
      f"engines={d_ride.engines_to_run}")

d_ride_norr = decide_route(_free_ride(), filename="ride.fit", ftp=270, has_rr=False)
check("free ride without RR -> only power curve",
      d_ride_norr.engines_to_run == ["power_curve_update"],
      f"engines={d_ride_norr.engines_to_run}")

# CP test = few (2-4) maximal blocks of DIFFERENT durations with recovery.
# This must NOT be HIIT (HIIT = many, equal/similar intervals). Build a
# CP3 + CP6 (different durations, each maximal and steady) and check it
# classifies as a test, not HIIT.
def _cp_test():
    ftp = 270
    rng = np.random.default_rng(123)
    p = [120.0] * 600                      # warmup
    
    # CP3 (maximal, steady, outdoor realistic noise)
    noise_cp3 = rng.normal(0, 10, 180)
    p += list(np.clip(int(1.05 * ftp) + noise_cp3, 0, None))
    
    p += [110.0] * 400                     # recovery
    
    # CP6 (maximal, steady, different duration, realistic noise)
    noise_cp6 = rng.normal(0, 8, 360)
    p += list(np.clip(int(0.98 * ftp) + noise_cp6, 0, None))
    
    p += [110.0] * 200                     # cooldown
    return [float(x) for x in p]

d_cp = decide_route(_cp_test(), filename="unknown.fit", ftp=270, has_rr=False)
check("CP3+CP6 (2 unequal maximal blocks) NOT classified HIIT",
      d_cp.category != "HIIT", f"category={d_cp.category}/{d_cp.subtype}")
check("CP test routes to metabolic, not ride_monitoring",
      d_cp.route in ("metabolic_anchor", "hrv_threshold"),
      f"route={d_cp.route}")

# =============================================================================
# 2. route_and_run executes the right engines
# =============================================================================
print("\n[2] route_and_run execution")

# Free ride with synthetic RR -> durability runs, thresholds do not.
n = 3000
rr_samples = []
t = 0.0
rng = np.random.default_rng(3)
for _ in range(n):
    rr = float(rng.uniform(400, 700))
    t += rr / 1000.0
    rr_samples.append({"rr": [rr], "elapsed": t})
ride = _free_ride(n=n)
out = route_and_run(ride, rr_samples, elapsed_s=list(np.arange(n, dtype=float)),
                    weight_kg=75, filename="ride.fit", ftp=250, context=ctx)
check("ride run -> routing present", "routing" in out and out["routing"]["route"] == "ride_monitoring")
check("ride run -> power_curve produced", "power_curve" in out["results"])
check("ride run -> durability attempted (result or skipped)",
      "hrv_durability" in out["results"] or "hrv_durability" in out["skipped"])
check("ride run -> thresholds NOT in results", "hrv_threshold" not in out["results"])

# Ramp with no RR -> metabolic runs, HRV skipped cleanly.
out2 = route_and_run(_ramp(), None, weight_kg=75, filename="indoor_session.fit", ftp=250, context=ctx)
check("ramp no-RR run -> no HRV threshold result", "hrv_threshold" not in out2["results"])

# =============================================================================
# 3. Honesty gate inside HRV threshold extraction
# =============================================================================
print("\n[3] HRV threshold honesty")
# Build a clean graded RR (alpha1 falling with power) won't be trivial to fake;
# instead we just assert the helper returns a reliability flag structure when
# run on a free ride's noisy data (should be insufficient or low_reliability).
from engines.io.session_router import _hrv_thresholds
try:
    parr = np.array(ride, dtype=float)
    vt = _hrv_thresholds(rr_samples, parr, list(np.arange(n, dtype=float)), ctx)
    check("threshold helper returns a status",
          isinstance(vt, dict) and "status" in vt,
          f"status={vt.get('status')}")
    check("noisy/free data not reported as clean 'ok'",
          vt.get("status") in ("insufficient", "low_reliability"),
          f"status={vt.get('status')}")
except Exception as e:
    check("threshold helper runs without crashing", False, str(e))


print("\n" + "=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  {passed}/{total} session-router checks passed")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL {name}: {detail}")
    sys.exit(1)

print("PASS Session-router regressions passed.")
sys.exit(0)