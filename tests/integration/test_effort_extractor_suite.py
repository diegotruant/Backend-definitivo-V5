#!/usr/bin/env python3
"""
Regression checks for test_effort_extractor.extract_test_proposal.

Verifies the autonomous test detector:
  * recognises a genuine Flow-style test (sprint + steady maximal CP blocks)
    and proposes it with good confidence,
  * does NOT mistake ordinary rides (steady-but-sub-maximal tempo blocks) for
    a test,
  * finds the sprint by its shape (peak then collapse) without fixed windows,
  * uses laps when present and falls back to the power scan when absent,
  * always proposes, never auto-commits.

Uses synthetic power streams so the test is deterministic and needs no FIT
files on disk.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from test_effort_extractor import extract_test_proposal

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))


def _flat(power_w, dur_s, noise=0.0, rng=None):
    arr = np.full(dur_s, float(power_w))
    if noise > 0 and rng is not None:
        arr = arr + rng.normal(0, noise, dur_s)
    return list(np.clip(arr, 0, None))


def _sprint(peak_w, dur_s):
    # rise to peak in ~2s, hold, then collapse — sprint-shaped
    out = []
    for i in range(dur_s):
        if i < 2:
            out.append(peak_w * (0.4 + 0.3 * i))
        else:
            out.append(peak_w * max(0.6, 1.0 - 0.03 * (i - 2)))
    out += [40.0] * 5  # collapse after the sprint
    return out


rng = np.random.default_rng(42)

# =============================================================================
# 1. Genuine Flow-style test: sprint + maximal CP3/CP6/CP12, steady
# =============================================================================
print("\n[1] Genuine test files -> proposed")

# Day 1: warmup + sprint + recovery + CP12
day1 = (
    _flat(120, 600, noise=8, rng=rng)
    + _sprint(1000, 15)
    + _flat(90, 300, noise=8, rng=rng)
    + _flat(300, 720, noise=6, rng=rng)        # CP12 maximal & steady
)
# Day 2: warmup + CP3 + recovery + CP6
day2 = (
    _flat(120, 600, noise=8, rng=rng)
    + _flat(360, 180, noise=8, rng=rng)        # CP3 maximal
    + _flat(90, 300, noise=8, rng=rng)
    + _flat(330, 360, noise=7, rng=rng)        # CP6 maximal
)
files = [
    {"file_id": "day1", "power": day1, "laps": None},
    {"file_id": "day2", "power": day2, "laps": None},
]
prop = extract_test_proposal(files)
d = prop.to_dict()
check("genuine test -> status 'proposed'", d["status"] == "proposed", f"status={d['status']}")
check("genuine test -> confidence >= 0.6", d["confidence"] >= 0.6, f"conf={d['confidence']}")
check("sprint detected", d["sprint"] is not None and d["sprint"]["peak_1s_w"] >= 800,
      f"sprint={d['sprint']}")
check("sprint duration is shape-derived (not fixed 20s)",
      d["sprint"] is not None and 8 <= d["sprint"]["duration_s"] <= 25,
      f"dur={d['sprint']['duration_s'] if d['sprint'] else None}")
labels = {c["target_label"] for c in d["cp_candidates"]}
check("found >= 2 CP targets", len(labels) >= 2, f"labels={labels}")
check("MMP for fit includes sprint + CP anchors",
      len(d["mmp_for_fit"]) >= 3, f"mmp={d['mmp_for_fit']}")

# =============================================================================
# 2. Ordinary rides: steady but sub-maximal tempo -> NOT a confirmed test
# =============================================================================
print("\n[2] Ordinary rides -> not proposed as test")

# A long ride: a brief spike (not a real sprint) + steady tempo blocks that
# are well below the rider's true maximal (here the spike sets a high 'best'
# at short durations, while tempo blocks sit lower).
ride = (
    _flat(150, 1200, noise=25, rng=rng)
    + _sprint(600, 6)                          # short jump, not an all-out 15-20s
    + _flat(210, 720, noise=18, rng=rng)       # tempo, sub-maximal, noisier
    + _flat(150, 600, noise=25, rng=rng)
    + _flat(215, 360, noise=18, rng=rng)
)
prop_ride = extract_test_proposal([{"file_id": "ride", "power": ride, "laps": None}])
dr = prop_ride.to_dict()
check("ordinary ride -> NOT 'proposed'", dr["status"] != "proposed", f"status={dr['status']}")
check("ordinary ride -> confidence < genuine test",
      dr["confidence"] < d["confidence"], f"ride={dr['confidence']} vs test={d['confidence']}")

# =============================================================================
# 3. Lap-marked test is recognised via laps
# =============================================================================
print("\n[3] Lap-marked efforts")

lap_power = (
    _flat(120, 300, noise=6, rng=rng)
    + _sprint(950, 18)
    + _flat(90, 200, noise=6, rng=rng)
    + _flat(310, 360, noise=5, rng=rng)
    + _flat(320, 180, noise=5, rng=rng)
)
# laps mark: warmup, sprint(~23s), rec, cp6, cp3
laps = [
    {"duration_s": 300, "avg_power_w": 120},
    {"duration_s": 23, "avg_power_w": 700},
    {"duration_s": 200, "avg_power_w": 90},
    {"duration_s": 360, "avg_power_w": 310},
    {"duration_s": 180, "avg_power_w": 320},
]
prop_lap = extract_test_proposal([{"file_id": "lapped", "power": lap_power, "laps": laps}])
dl = prop_lap.to_dict()
check("lap-marked sprint detected", dl["sprint"] is not None, f"sprint={dl['sprint']}")
check("lap source used somewhere",
      (dl["sprint"] and dl["sprint"]["source"] == "lap")
      or any(c["source"] == "lap" for c in dl["cp_candidates"]),
      "no lap-sourced candidate")

# =============================================================================
# 4. Empty / no-power input is handled
# =============================================================================
print("\n[4] Degenerate input")

prop_empty = extract_test_proposal([])
check("no files -> status 'empty'", prop_empty.status == "empty")
prop_flat = extract_test_proposal([{"file_id": "z", "power": _flat(100, 600), "laps": None}])
check("flat easy ride -> no sprint, not proposed",
      prop_flat.sprint is None and prop_flat.status != "proposed",
      f"status={prop_flat.status}")

# =============================================================================
# 5. The extractor never auto-commits (returns a proposal object only)
# =============================================================================
print("\n[5] Proposal-only contract")
check("returns a proposal with explicit status (no side effects)",
      hasattr(prop, "status") and hasattr(prop, "confidence") and hasattr(prop, "to_dict"))


print("\n" + "=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  {passed}/{total} test-extractor checks passed")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL {name}: {detail}")
    sys.exit(1)

print("PASS Test-effort extractor regressions passed.")
sys.exit(0)
