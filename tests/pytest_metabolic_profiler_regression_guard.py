"""Golden regression guard for representative metabolic-profiler inputs.

These cases freeze the public behavior of the current scientific model before
larger refactors. Tolerances allow minor SciPy/platform numerical drift while
still catching meaningful changes to the physiological outputs.
"""

from __future__ import annotations

from typing import Any

import pytest

from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_profiler import MetabolicProfiler


CTX = AthleteContext(gender="MALE", training_years=10, discipline="ROAD")

CASES: list[dict[str, Any]] = [
    {
        "id": "endurance",
        "weight": 72.0,
        "mmp": {5: 850, 30: 520, 60: 430, 300: 330, 600: 310, 1200: 290, 1800: 280, 3600: 265},
        "expected": {
            "fit_method": "joint_auto",
            "vo2": 50.3,
            "vlamax": 0.5332,
            "mlss": 265.0,
            "fatmax": 137.5,
            "map": 332.3,
            "confidence": 0.428,
        },
    },
    {
        "id": "all_rounder",
        "weight": 72.0,
        "mmp": {5: 1100, 15: 900, 30: 700, 60: 520, 180: 380, 300: 340, 600: 310, 1200: 295, 1800: 285, 3600: 270},
        "expected": {
            "fit_method": "joint_auto",
            "vo2": 56.9,
            "vlamax": 0.4949,
            "mlss": 305.0,
            "fatmax": 175.0,
            "map": 379.3,
            "confidence": 0.432,
        },
    },
    {
        "id": "explosive_segmented",
        "weight": 72.0,
        "mmp": {5: 1100, 15: 1000, 60: 520, 300: 340, 1200: 270, 3600: 240},
        "expected": {
            "fit_method": "segmented",
            "vo2": 60.6,
            "vlamax": 0.9480,
            "mlss": 310.0,
            "fatmax": 142.5,
            "map": 405.5,
            "confidence": 0.240,
        },
    },
    {
        "id": "incomplete_endurance_only",
        "weight": 70.0,
        "mmp": {300: 340, 600: 300, 1200: 290, 1800: 285, 3600: 270},
        "expected": {
            "fit_method": "joint_auto",
            "vo2": 55.5,
            "vlamax": None,
            "mlss": 305.0,
            "fatmax": None,
            "map": 359.1,
            "confidence": 0.360,
        },
    },
    {
        "id": "covered_but_submaximal",
        "weight": 72.0,
        "mmp": {5: 500, 30: 460, 60: 420, 300: 350, 1200: 280, 3600: 250},
        "expected": {
            "fit_method": "joint_auto",
            "vo2": 52.5,
            "vlamax": 0.3322,
            "mlss": 290.0,
            "fatmax": 177.5,
            "map": 348.1,
            "confidence": 0.050,
            "submaximal": True,
        },
    },
]


def _assert_optional_numeric(actual: Any, expected: Any, *, abs_tol: float) -> None:
    if expected is None:
        assert actual is None
    else:
        assert actual == pytest.approx(expected, abs=abs_tol)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_metabolic_profiler_golden_profiles(case: dict[str, Any]) -> None:
    snap = MetabolicProfiler(case["weight"], CTX).generate_metabolic_snapshot_auto(case["mmp"])
    expected = case["expected"]

    assert snap["status"] == "success"
    assert snap["fit_method"] == expected["fit_method"]
    _assert_optional_numeric(snap.get("estimated_vo2max"), expected["vo2"], abs_tol=0.2)
    _assert_optional_numeric(
        snap.get("estimated_vlamax_mmol_L_s"), expected["vlamax"], abs_tol=0.005
    )
    _assert_optional_numeric(snap.get("mlss_power_watts"), expected["mlss"], abs_tol=5.0)
    _assert_optional_numeric(snap.get("fatmax_power_watts"), expected["fatmax"], abs_tol=5.0)
    _assert_optional_numeric(snap.get("map_aerobic_watts"), expected["map"], abs_tol=2.0)
    assert snap["confidence_score"] == pytest.approx(expected["confidence"], abs=0.02)

    if expected.get("submaximal"):
        assert (snap.get("curve_maximality") or {}).get("plausible_maximal") is False
        assert snap["confidence_score"] <= 0.15
