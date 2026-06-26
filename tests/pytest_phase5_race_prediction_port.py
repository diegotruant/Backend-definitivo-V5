"""Port of tests/integration/test_race_prediction_engine.py for coverage."""

from __future__ import annotations

from engines.performance.race_prediction_engine import (
    AthleteRaceProfile,
    analyze_course,
    parse_gpx_course,
    simulate_gpx_race,
)

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


class TestRacePredictionPort:
    def test_gpx_parse_and_course_analysis(self) -> None:
        points = parse_gpx_course(GPX)
        assert len(points) == 8
        course = analyze_course(points)
        assert course["distance_km"] > 5.0
        assert course["elevation_gain_m"] >= 150
        assert len(course["climbs"]) >= 1

    def test_race_simulation(self) -> None:
        profile = AthleteRaceProfile(weight_kg=72.0, ftp_w=300.0, mlss_w=295.0, fatmax_w=190.0)
        prediction = simulate_gpx_race(
            GPX,
            weight_kg=profile.weight_kg,
            ftp_w=profile.ftp_w,
            metabolic_snapshot={
                "mlss_power_watts": profile.mlss_w,
                "fatmax_power_watts": profile.fatmax_w,
            },
        )
        assert prediction.get("status") == "success"
        assert prediction.get("api_contract", {}).get("module") == "race_prediction_engine"
        assert prediction["prediction"]["estimated_time_s"] > 0
        assert prediction["prediction"]["mechanical_work_kj"] > 0
        assert len(prediction["pacing_plan"]) > 0
        assert prediction["strategy"]["fueling"]["carbohydrate_target_g"] > 0
