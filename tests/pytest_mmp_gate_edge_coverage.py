from __future__ import annotations

from datetime import date, datetime

from api.services import mmp_publication_gate as gate


def test_parse_date_accepts_supported_values_and_rejects_invalid_ones():
    assert gate._parse_date(datetime(2026, 7, 14, 12, 30)) == date(2026, 7, 14)
    assert gate._parse_date(date(2026, 7, 13)) == date(2026, 7, 13)
    assert gate._parse_date("2026-07-12T08:30:00Z") == date(2026, 7, 12)
    assert gate._parse_date("not-a-date") is None
    assert gate._parse_date(12345) is None


def test_coerce_curve_sanitizes_legacy_duplicates_and_reliability_bounds():
    curve = {
        "bad-key": {"duration_s": 5, "power_w": 999},
        "5": {
            "duration_s": 5,
            "power_w": 950,
            "ride_id": "winner",
            "ride_date": "2026-07-10",
            "reliability": 2.0,
        },
        "05": {
            "duration_s": 5,
            "power_w": 900,
            "ride_id": "lower-duplicate",
            "ride_date": "2026-07-09",
            "reliability": 0.8,
        },
        "10": {
            "duration_s": 10,
            "power_w": 850,
            "ride_id": "low-reliability",
            "ride_date": "2026-07-10",
            "reliability": -2.0,
        },
        "20": "700",
        "30": object(),
        "40": {"duration_s": 40, "power_w": None},
        "50": {"duration_s": "bad", "power_w": 600},
        "60": {"duration_s": 60, "power_w": "bad"},
        "0": 500,
    }

    normalized = gate._coerce_curve(curve)

    assert sorted(normalized) == [5, 10, 20]
    assert normalized[5]["power_w"] == 950
    assert normalized[5]["ride_id"] == "winner"
    assert normalized[5]["reliability"] == 1.0
    assert normalized[10]["reliability"] == 0.0
    assert normalized[20]["ride_id"] == "historical"


def test_private_coverage_and_visibility_maps_are_total():
    curve = {
        5: {"power_w": 1000},
        180: {"power_w": 500},
        300: {"power_w": 460},
        1200: {"power_w": 350},
    }

    assert gate._coverage_for(curve) == {
        "sprint": "present",
        "glycolytic": "missing",
        "vo2": "present",
        "threshold": "partial",
    }
    assert gate._visibility_for("collecting") == "progress_only"
    assert gate._visibility_for("provisional") == "coach_preview"
    assert gate._visibility_for("published") == "show"
    assert gate._visibility_for("degraded") == "coach_preview"
    assert gate._visibility_for("invalid") == "hidden"


def test_legacy_curve_without_activity_provenance_stays_collecting_with_warning():
    assessment = gate.evaluate_mmp_gate(
        {
            "5": 1000,
            "30": 700,
            "180": 500,
            "300": 460,
            "1200": 350,
            "1800": 330,
        },
        as_of="2026-07-14",
        window_days=0,
    )

    assert assessment.source_activity_count == 0
    assert assessment.lifecycle_status == "collecting"
    assert assessment.profile_eligible is False
    assert "Winning anchors have no independent activity provenance." in assessment.warnings
    assert assessment.missing_date_durations == [5, 30, 180, 300, 1200, 1800]
