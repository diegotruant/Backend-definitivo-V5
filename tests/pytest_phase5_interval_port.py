"""Port of tests/integration/test_v340_interval_detector.py into pytest for coverage."""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

import pytest

from engines.performance.interval_detector import (
    SUBTYPES_FREE,
    SUBTYPES_HIIT,
    SUBTYPES_STEADY,
    SUBTYPES_TEST,
    ClassifiedSession,
    classify_session,
)

FTP = 250.0
FLAT = [200.0] * 1200


@pytest.mark.parametrize(
    "fname,exp_cat,exp_sub",
    [
        ("activity_1234_ramp_test_01.fit", "TEST", "ramp_test"),
        ("workout_2x8_test.fit", "TEST", "ftp_2x8"),
        ("cp6_test_morning.fit", "TEST", "cp6"),
        ("3_sprint_test.fit", "TEST", "sprint_set"),
        ("training_30_15_block.fit", "HIIT", "microburst_high_density"),
        ("tabata_indoor.fit", "HIIT", "microburst_balanced"),
        ("vo2max_session.fit", "HIIT", "medium_interval"),
        ("endurance_long_ride.fit", "STEADY", "endurance_z2"),
        ("sweet_spot_intervals.fit", "STEADY", "sweet_spot"),
        ("criterium_race_sunday.fit", "FREE", "race"),
        ("flow_protocol_2026.fit", "TEST", "mixed_test"),
    ],
)
def test_filename_strategy(fname: str, exp_cat: str, exp_sub: str) -> None:
    r = classify_session(FLAT, filename=fname, ftp=FTP)
    assert r.category == exp_cat
    assert r.subtype == exp_sub
    assert r.source == "filename"
    assert r.confidence >= 0.85


def test_unknown_filename_not_strategy_a() -> None:
    r = classify_session(FLAT, filename="random_string.fit", ftp=FTP)
    assert r.source != "filename"


def test_lap_hiit_microburst() -> None:
    hiit_laps: List[Dict[str, Any]] = []
    for i in range(20):
        if i % 2 == 0:
            hiit_laps.append({"duration_s": 30, "avg_power_w": 350, "max_power_w": 380})
        else:
            hiit_laps.append({"duration_s": 30, "avg_power_w": 130, "max_power_w": 150})
    r = classify_session(FLAT, filename="unknown.fit", laps=hiit_laps, ftp=FTP)
    assert r.category == "HIIT"
    assert r.source == "laps"
    assert "microburst" in r.subtype


def test_lap_ramp_and_ftp_2x8() -> None:
    ramp_laps = [
        {"duration_s": 60, "avg_power_w": 100 + i * 25, "max_power_w": 110 + i * 25}
        for i in range(10)
    ]
    r = classify_session(FLAT, filename="unknown.fit", laps=ramp_laps, ftp=FTP)
    assert r.category == "TEST"
    assert r.subtype == "ramp_test"
    assert r.source == "laps"

    ftp_laps = [
        {"duration_s": 600, "avg_power_w": 100, "max_power_w": 110},
        {"duration_s": 480, "avg_power_w": 240, "max_power_w": 260},
        {"duration_s": 300, "avg_power_w": 100, "max_power_w": 110},
        {"duration_s": 480, "avg_power_w": 245, "max_power_w": 265},
        {"duration_s": 300, "avg_power_w": 100, "max_power_w": 110},
    ]
    r2 = classify_session(FLAT, filename="unknown.fit", laps=ftp_laps, ftp=FTP)
    assert r2.category == "TEST"
    assert r2.subtype == "ftp_2x8"


def test_signal_steady_endurance_sprint_race() -> None:
    random.seed(42)
    steady = [200 + random.gauss(0, 10) for _ in range(1800)]
    r = classify_session(steady, filename="ride.fit", ftp=FTP)
    assert r.category == "STEADY"

    endurance = [150 + random.gauss(0, 8) for _ in range(5400)]
    r2 = classify_session(endurance, filename="ride.fit", ftp=FTP)
    assert r2.category == "STEADY"
    assert "endurance" in r2.subtype

    sprint = [120 + random.gauss(0, 10) for _ in range(900)]
    for i in range(700, 710):
        sprint[i] = 900
    r3 = classify_session(sprint, filename="ride.fit", ftp=FTP)
    assert r3.category == "TEST"
    assert r3.subtype == "single_sprint"

    race: List[float] = []
    for i in range(2400):
        if 200 < i < 500 or 800 < i < 1100 or 1500 < i < 1800:
            race.append(300 + random.gauss(0, 40))
        elif i % 200 < 8:
            race.append(450 + random.gauss(0, 80))
        else:
            race.append(180 + random.gauss(0, 30))
    r4 = classify_session(race, filename="ride.fit", ftp=FTP)
    assert r4.category in ("FREE", "HIIT", "TEST") or r4.subtype != "endurance_z2"


def test_hint_override_and_anchors() -> None:
    r = classify_session(FLAT, filename="endurance_ride.fit", ftp=FTP, hint=("TEST", "cp6"))
    assert r.category == "TEST"
    assert r.subtype == "cp6"
    assert r.source == "hint"
    assert r.confidence == 1.0

    cp6 = [150.0] * 300 + [300.0] * 360 + [100.0] * 300
    r2 = classify_session(cp6, filename="cp6_test.fit", ftp=FTP)
    assert any(a.duration_s == 360 for a in r2.qualified_anchors)
    anchor = next(a for a in r2.qualified_anchors if a.duration_s == 360)
    assert abs(anchor.power_w - 300) < 5
    assert anchor.anchor_reliability == 1.0

    sprint_test = [120.0] * 200 + [800.0] * 5 + [100.0] * 200 + [750.0] * 15 + [120.0] * 200
    r3 = classify_session(sprint_test, filename="sprint_test.fit", ftp=FTP)
    assert any(a.duration_s == 5 for a in r3.qualified_anchors)
    assert any(a.duration_s == 15 for a in r3.qualified_anchors)


def test_stimulus_vector_and_edge_cases() -> None:
    z2 = [150.0] * 3600
    r = classify_session(z2, filename="ride.fit", ftp=FTP)
    assert r.stimulus_vector is not None
    assert r.stimulus_vector.aerobic_base_stimulus_s >= 3500
    assert r.stimulus_vector.vo2max_stimulus_s == 0

    r_no_ftp = classify_session(z2, filename="ride.fit", ftp=None)
    assert r_no_ftp.stimulus_vector is None

    empty = classify_session([], filename="empty.fit", ftp=FTP)
    assert empty.category == "UNCLASSIFIED"

    short = classify_session([100.0] * 20, filename="short.fit", ftp=FTP)
    assert short.category in ("UNCLASSIFIED", "STEADY", "HIIT")

    zeros = classify_session([0.0] * 1800, filename="zeros.fit", ftp=FTP)
    assert isinstance(zeros, ClassifiedSession)


def test_to_dict_contract_and_taxonomy() -> None:
    random.seed(42)
    steady = [200 + random.gauss(0, 10) for _ in range(1800)]
    d = classify_session(steady, filename="ride.fit", ftp=FTP).to_dict()
    required = {
        "category",
        "subtype",
        "confidence",
        "source",
        "notes",
        "qualified_anchors",
        "detected_blocks",
        "stimulus_vector",
        "duration_s",
        "duration_min",
        "avg_power_w",
        "normalized_power_w",
        "variability_index",
        "intensity_factor",
        "tier",
    }
    assert required.issubset(d.keys())
    assert d["tier"] == "MODEL"
    assert isinstance(d["confidence"], float) and 0 <= d["confidence"] <= 1
    assert "ramp_test" in SUBTYPES_TEST
    assert "microburst_high_density" in SUBTYPES_HIIT
    assert "endurance_z2" in SUBTYPES_STEADY
    assert "race" in SUBTYPES_FREE
