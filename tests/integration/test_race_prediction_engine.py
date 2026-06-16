#!/usr/bin/env python3
"""Regression tests for GPX course ingestion and race prediction."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engines.performance.race_prediction_engine import (
    AthleteRaceProfile,
    analyze_course,
    parse_gpx_course,
    simulate_gpx_race,
)


results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))


GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <name>Race course</name>
    <trkseg>
      <trkpt lat="45.0000" lon="7.0000"><ele>300</ele></trkpt>
      <trkpt lat="45.0000" lon="7.0100"><ele>310</ele></trkpt>
      <trkpt lat="45.0000" lon="7.0200"><ele>340</ele></trkpt>
      <trkpt lat="45.0000" lon="7.0300"><ele>390</ele></trkpt>
      <trkpt lat="45.0000" lon="7.0400"><ele>450</ele></trkpt>
      <trkpt lat="45.0000" lon="7.0500"><ele>455</ele></trkpt>
      <trkpt lat="45.0000" lon="7.0600"><ele>420</ele></trkpt>
      <trkpt lat="45.0000" lon="7.0700"><ele>360</ele></trkpt>
    </trkseg>
  </trk>
</gpx>
"""


print("\n[1] GPX parsing and course analysis")
points = parse_gpx_course(GPX)
course = analyze_course(points)
check("GPX parsed points", len(points) == 8, f"got={len(points)}")
check("course distance computed", course["distance_km"] > 5.0, f"got={course['distance_km']}")
check("elevation gain computed", course["elevation_gain_m"] >= 150, f"got={course['elevation_gain_m']}")
check("climb detected", len(course["climbs"]) >= 1, f"got={course['climbs']}")


print("\n[2] Race simulation")
profile = AthleteRaceProfile(weight_kg=72.0, ftp_w=300.0, mlss_w=295.0, fatmax_w=190.0)
prediction = simulate_gpx_race(GPX, weight_kg=profile.weight_kg, ftp_w=profile.ftp_w, metabolic_snapshot={
    "mlss_power_watts": profile.mlss_w,
    "fatmax_power_watts": profile.fatmax_w,
})

check("prediction status success", prediction.get("status") == "success")
check("prediction has api contract", prediction.get("api_contract", {}).get("module") == "race_prediction_engine")
check("estimated time positive", prediction["prediction"]["estimated_time_s"] > 0)
check("energy demand positive", prediction["prediction"]["mechanical_work_kj"] > 0)
check("pacing plan covers segments", len(prediction["pacing_plan"]) > 0)
check("fueling strategy present", prediction["strategy"]["fueling"]["carbohydrate_target_g"] > 0)


print("\n" + "=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  {passed}/{total} race prediction checks passed")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL {name}: {detail}")
    sys.exit(1)

print("PASS Race prediction regressions passed.")
sys.exit(0)
