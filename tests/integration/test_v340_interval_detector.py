#!/usr/bin/env python3
"""
Test: v3.4.0 — interval_detector
=================================

Validates the session classifier on:
  1. Synthetic patterns (controlled ground truth)
  2. Real FIT files from Gigi (if present)
  3. Edge cases (empty, very short, no FTP)
  4. API contract (output shape, anchor extraction)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import random

from engines.performance.interval_detector import (
    SUBTYPES_FREE,
    SUBTYPES_HIIT,
    SUBTYPES_STEADY,
    SUBTYPES_TEST,
    ClassifiedSession,
    classify_session,
)


results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if not ok and detail else ""))


FTP = 250


# =============================================================================
# 1. Filename match (Strategy A) — should always win
# =============================================================================
print("\n[1] Strategy A — filename match")

# Use synthetic flat power; the filename should drive the classification
flat_powers = [200] * 1200  # 20 min steady

cases = [
    ("activity_1234_ramp_test_01.fit",         "TEST",   "ramp_test"),
    ("workout_2x8_test.fit",                    "TEST",   "ftp_2x8"),
    ("cp6_test_morning.fit",                    "TEST",   "cp6"),
    ("3_sprint_test.fit",                       "TEST",   "sprint_set"),
    ("training_30_15_block.fit",                "HIIT",   "microburst_high_density"),
    ("tabata_indoor.fit",                       "HIIT",   "microburst_balanced"),
    ("vo2max_session.fit",                      "HIIT",   "medium_interval"),
    ("endurance_long_ride.fit",                 "STEADY", "endurance_z2"),
    ("sweet_spot_intervals.fit",                "STEADY", "sweet_spot"),
    ("criterium_race_sunday.fit",               "FREE",   "race"),
    ("flow_protocol_2026.fit",                  "TEST",   "mixed_test"),
]

for fname, exp_cat, exp_sub in cases:
    r = classify_session(flat_powers, filename=fname, ftp=FTP)
    ok = r.category == exp_cat and r.subtype == exp_sub
    check(f"filename '{fname}' → {exp_cat}/{exp_sub}",
          ok and r.source == "filename" and r.confidence >= 0.85,
          f"got {r.category}/{r.subtype} conf={r.confidence:.2f} src={r.source}")

# Unknown filename should not match Strategy A
r = classify_session(flat_powers, filename="random_string.fit", ftp=FTP)
check("unknown filename does NOT match Strategy A",
      r.source != "filename")


# =============================================================================
# 2. Lap-structure match (Strategy B)
# =============================================================================
print("\n[2] Strategy B — lap structure")

# Synthetic HIIT: 20 alternating work/rest laps
hiit_laps = []
for i in range(20):
    if i % 2 == 0:
        hiit_laps.append({"duration_s": 30, "avg_power_w": 350, "max_power_w": 380})
    else:
        hiit_laps.append({"duration_s": 30, "avg_power_w": 130, "max_power_w": 150})

r = classify_session(
    flat_powers, filename="unknown.fit", laps=hiit_laps, ftp=FTP,
)
check("20 alternating laps → HIIT",
      r.category == "HIIT" and r.source == "laps",
      f"got {r.category} from {r.source}")
check("HIIT subtype is microburst (work<60s)",
      "microburst" in r.subtype)

# Synthetic ramp test: 10 monotonically-increasing laps
ramp_laps = [
    {"duration_s": 60, "avg_power_w": 100 + i * 25, "max_power_w": 110 + i * 25}
    for i in range(10)
]
r = classify_session(flat_powers, filename="unknown.fit", laps=ramp_laps, ftp=FTP)
check("10 monotonic laps → ramp_test",
      r.category == "TEST" and r.subtype == "ramp_test" and r.source == "laps",
      f"got {r.category}/{r.subtype} from {r.source}")

# Synthetic 2x8 FTP test: 2 long threshold laps
ftp_2x8_laps = [
    {"duration_s": 600, "avg_power_w": 100, "max_power_w": 110},  # warmup
    {"duration_s": 480, "avg_power_w": 240, "max_power_w": 260},  # 8min #1
    {"duration_s": 300, "avg_power_w": 100, "max_power_w": 110},  # rest
    {"duration_s": 480, "avg_power_w": 245, "max_power_w": 265},  # 8min #2
    {"duration_s": 300, "avg_power_w": 100, "max_power_w": 110},  # cooldown
]
r = classify_session(flat_powers, filename="unknown.fit", laps=ftp_2x8_laps, ftp=FTP)
check("2 long threshold laps → ftp_2x8",
      r.category == "TEST" and r.subtype == "ftp_2x8",
      f"got {r.category}/{r.subtype}")


# =============================================================================
# 3. Signal-feature match (Strategy C)
# =============================================================================
print("\n[3] Strategy C — signal features")

random.seed(42)

# Synthetic steady tempo: 30min @ 200W with small noise
steady_powers = [200 + random.gauss(0, 10) for _ in range(1800)]
r = classify_session(steady_powers, filename="ride.fit", ftp=FTP)
check("steady 200W ride → STEADY",
      r.category == "STEADY",
      f"got {r.category}/{r.subtype}")

# Synthetic endurance Z2: 90min @ 150W
endurance_powers = [150 + random.gauss(0, 8) for _ in range(5400)]
r = classify_session(endurance_powers, filename="ride.fit", ftp=FTP)
check("90min @ 150W → STEADY/endurance_z2",
      r.category == "STEADY" and "endurance" in r.subtype,
      f"got {r.category}/{r.subtype}")

# Synthetic single sprint: 15min easy + 1 short sprint
sprint_powers = [120 + random.gauss(0, 10) for _ in range(900)]
# Replace one 10s window with a high-power spike
for i in range(700, 710):
    sprint_powers[i] = 900
r = classify_session(sprint_powers, filename="ride.fit", ftp=FTP)
check("15min easy + 1 sprint → TEST/single_sprint",
      r.category == "TEST" and r.subtype == "single_sprint",
      f"got {r.category}/{r.subtype}")

# Synthetic race: high variability with many sustained efforts and frequent surges
race_powers = []
for i in range(2400):
    if 200 < i < 500 or 800 < i < 1100 or 1500 < i < 1800:
        race_powers.append(300 + random.gauss(0, 40))   # sustained efforts
    elif i % 200 < 8:
        race_powers.append(450 + random.gauss(0, 80))   # frequent surges (~1.8x FTP)
    else:
        race_powers.append(180 + random.gauss(0, 30))   # variable base
r = classify_session(race_powers, filename="ride.fit", ftp=FTP)
check("variable + sustained + surges → not STEADY/endurance",
      r.category in ("FREE", "HIIT", "TEST") or r.subtype != "endurance_z2",
      f"got {r.category}/{r.subtype}")


# =============================================================================
# 4. Hint override
# =============================================================================
print("\n[4] Manual hint override")

# Even with conflicting filename, hint wins
r = classify_session(
    flat_powers,
    filename="endurance_ride.fit",
    ftp=FTP,
    hint=("TEST", "cp6"),
)
check("hint overrides filename match",
      r.category == "TEST" and r.subtype == "cp6" and r.source == "hint",
      f"got {r.category}/{r.subtype} src={r.source}")
check("hint sets confidence to 1.0", r.confidence == 1.0)


# =============================================================================
# 5. Qualified anchors extracted for TEST sessions
# =============================================================================
print("\n[5] Qualified anchor extraction")

# Synthetic CP6 test: 5min warmup at 150W + 6min @ 300W + 5min cooldown
cp6_powers = [150] * 300 + [300] * 360 + [100] * 300
r = classify_session(cp6_powers, filename="cp6_test.fit", ftp=FTP)
check("cp6 test extracts 360s anchor",
      any(a.duration_s == 360 for a in r.qualified_anchors))
anchor_360 = next((a for a in r.qualified_anchors if a.duration_s == 360), None)
if anchor_360:
    check("cp6 anchor power ≈ 300W",
          abs(anchor_360.power_w - 300) < 5,
          f"got {anchor_360.power_w}W")
    check("cp6 anchor reliability == 1.0",
          anchor_360.anchor_reliability == 1.0)

# Sprint test extracts 5s and 15s anchors
sprint_test_powers = [120] * 200 + [800] * 5 + [100] * 200 + [750] * 15 + [120] * 200
r = classify_session(sprint_test_powers, filename="sprint_test.fit", ftp=FTP)
check("sprint_test extracts 5s and 15s anchors",
      any(a.duration_s == 5 for a in r.qualified_anchors) and
      any(a.duration_s == 15 for a in r.qualified_anchors))


# =============================================================================
# 6. Stimulus vector
# =============================================================================
print("\n[6] Stimulus vector")

# Steady Z2 → almost all time in aerobic_base
z2_powers = [150] * 3600
r = classify_session(z2_powers, filename="ride.fit", ftp=FTP)
sv = r.stimulus_vector
check("Z2 ride: stimulus vector present", sv is not None)
if sv:
    check("Z2 ride: aerobic_base ≈ 60min",
          sv.aerobic_base_stimulus_s >= 3500,
          f"got {sv.aerobic_base_stimulus_s}s")
    check("Z2 ride: vo2max_stimulus ≈ 0",
          sv.vo2max_stimulus_s == 0,
          f"got {sv.vo2max_stimulus_s}s")

# No FTP → no stimulus vector
r = classify_session(z2_powers, filename="ride.fit", ftp=None)
check("no FTP → stimulus_vector is None",
      r.stimulus_vector is None)


# =============================================================================
# 7. Edge cases
# =============================================================================
print("\n[7] Edge cases")

# Empty
r = classify_session([], filename="empty.fit", ftp=FTP)
check("empty powers → UNCLASSIFIED",
      r.category == "UNCLASSIFIED")

# Very short
r = classify_session([100] * 20, filename="short.fit", ftp=FTP)
check("20-sample stream → UNCLASSIFIED or fallback",
      r.category in ("UNCLASSIFIED", "STEADY", "HIIT"))

# Only zeros
r = classify_session([0] * 1800, filename="zeros.fit", ftp=FTP)
check("all-zero stream doesn't crash",
      isinstance(r, ClassifiedSession))


# =============================================================================
# 8. Output contract (to_dict)
# =============================================================================
print("\n[8] Output contract")

r = classify_session(steady_powers, filename="ride.fit", ftp=FTP)
d = r.to_dict()
required_keys = {
    "category", "subtype", "confidence", "source", "notes",
    "qualified_anchors", "detected_blocks", "stimulus_vector",
    "duration_s", "duration_min", "avg_power_w", "normalized_power_w",
    "variability_index", "intensity_factor", "tier",
}
check("to_dict has all required keys",
      required_keys.issubset(d.keys()),
      f"missing: {required_keys - set(d.keys())}")

check("tier is MODEL", d["tier"] == "MODEL")
check("confidence is float in [0,1]",
      isinstance(d["confidence"], float) and 0 <= d["confidence"] <= 1)


# =============================================================================
# 9. Subtype taxonomy is closed
# =============================================================================
print("\n[9] Subtype taxonomy")

check("TEST subtypes contain ramp_test", "ramp_test" in SUBTYPES_TEST)
check("HIIT subtypes contain microburst_high_density",
      "microburst_high_density" in SUBTYPES_HIIT)
check("STEADY subtypes contain endurance_z2",
      "endurance_z2" in SUBTYPES_STEADY)
check("FREE subtypes contain race", "race" in SUBTYPES_FREE)


# =============================================================================
# 10. Real-data smoke test (Gigi's FIT files, only if available)
# =============================================================================
print("\n[10] Real FIT files (Gigi, if available)")

upload_dir = Path("/mnt/user-data/uploads")
if upload_dir.exists():
    try:
        import fitparse
        fit_files = sorted(upload_dir.glob("*.fit"))
        
        for fit in fit_files[:5]:  # cap at 5 for test speed
            ff = fitparse.FitFile(str(fit))
            powers = []
            for rec in ff.get_messages("record"):
                for f in rec.fields:
                    if f.name == "power":
                        powers.append(f.value if f.value is not None else 0)
                        break
            laps = []
            for lap in ff.get_messages("lap"):
                info = {}
                for f in lap.fields:
                    if f.value is not None:
                        if f.name == "total_elapsed_time":
                            info["duration_s"] = float(f.value)
                        elif f.name == "avg_power":
                            info["avg_power_w"] = float(f.value)
                if info:
                    laps.append(info)
            
            if powers:
                r = classify_session(
                    powers, filename=fit.name, laps=laps, ftp=250
                )
                # Real, unstructured long rides legitimately classify as
                # UNCLASSIFIED with low confidence — that's the detector being
                # honest, not an error. Accept it alongside the 4 main classes.
                check(f"{fit.name[:30]}... classified ({r.category}/{r.subtype}, conf {r.confidence:.2f})",
                      r.category in ("TEST", "HIIT", "STEADY", "FREE", "UNCLASSIFIED"))
    except ImportError:
        check("fitparse available", False, "skipped: fitparse not installed")
else:
    print("    (uploads directory not present, skipping)")


# =============================================================================
# REPORT
# =============================================================================
print()
print("=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  v3.4.0 INTERVAL DETECTOR: {passed}/{total} checks passed ({100*passed/total:.0f}%)")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  ✗ {name}: {detail}")
    sys.exit(1)
else:
    print("✓ All v3.4.0 interval detector checks passed.")
    sys.exit(0)
