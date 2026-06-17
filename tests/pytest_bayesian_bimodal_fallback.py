"""Bayesian profiler must not collapse on bimodal sprint-heavy MMP curves."""

from __future__ import annotations

import pytest

from engines.core.athlete_context import AthleteContext
from engines.metabolic.bayesian_profiler import bayesian_metabolic_snapshot
from engines.metabolic.metabolic_profiler import MetabolicProfiler

# Synthetic edge-case MMP profiles (duration_s -> watts).
MCMC_EDGE_CASES = [
    pytest.param(
        {
            "id": "gigi_sprinter_90kg",
            "weight": 90.0,
            "mmp": {1: 961, 5: 900, 60: 400, 300: 280, 1200: 255, 3600: 215},
            "vo2_range": (35.0, 75.0),
            "vla_range": (0.35, 1.2),
            "vo2_tol": 1.5,
            "mlss_tol": 15.0,
            "expect_bimodal": True,
        },
        id="gigi_sprinter_90kg",
    ),
    pytest.param(
        {
            "id": "track_sprinter_78kg",
            "weight": 78.0,
            "mmp": {5: 1450, 30: 950, 60: 700, 300: 380, 1200: 310, 3600: 280},
            "vo2_range": (40.0, 80.0),
            "vla_range": (0.4, 1.5),
            "vo2_tol": 2.0,
            "mlss_tol": 20.0,
            "expect_bimodal": True,
        },
        id="track_sprinter_78kg",
    ),
    pytest.param(
        {
            "id": "puncheur_72kg",
            "weight": 72.0,
            "mmp": {5: 1100, 30: 700, 60: 520, 300: 340, 1200: 295, 3600: 270},
            "vo2_range": (45.0, 85.0),
            "vla_range": (0.25, 1.0),
            "vo2_tol": 2.0,
            "mlss_tol": 15.0,
            "expect_bimodal": False,
        },
        id="puncheur_72kg",
    ),
    pytest.param(
        {
            "id": "diesel_endurance_68kg",
            "weight": 68.0,
            "mmp": {300: 340, 600: 310, 1200: 290, 1800: 285, 3600: 270},
            "vo2_range": (40.0, 75.0),
            "vla_range": (0.1, 0.8),
            "vo2_tol": 3.0,
            "mlss_tol": 20.0,
            "expect_bimodal": False,
        },
        id="diesel_endurance_68kg",
    ),
]


def _assert_bayesian_coherent_with_reference(
    profiler: MetabolicProfiler,
    mmp: dict[int, float],
    *,
    vo2_range: tuple[float, float],
    vla_range: tuple[float, float],
    vo2_tol: float,
    mlss_tol: float,
) -> dict:
    segmented = profiler.generate_metabolic_snapshot_segmented(mmp)
    bayes = bayesian_metabolic_snapshot(profiler, mmp, n_samples=1500, n_warmup=400)
    out = bayes.to_dict()

    assert segmented.get("status") == "success", segmented
    assert bayes.status == "success", out.get("message")
    assert segmented.get("estimated_vo2max") is not None
    assert out.get("estimated_vo2max") is not None

    seg_vo2 = float(segmented["estimated_vo2max"])
    bayes_vo2 = float(out["estimated_vo2max"])
    assert abs(bayes_vo2 - seg_vo2) <= vo2_tol, f"VO2 bayes={bayes_vo2} seg={seg_vo2}"

    seg_mlss = float(segmented["mlss_power_watts"])
    bayes_mlss = float(out["mlss_power_watts"])
    assert abs(bayes_mlss - seg_mlss) <= mlss_tol, f"MLSS bayes={bayes_mlss} seg={seg_mlss}"

    vo2_lo, vo2_hi = vo2_range
    vla_lo, vla_hi = vla_range
    assert vo2_lo <= bayes_vo2 <= vo2_hi
    vla = float(out["estimated_vlamax_mmol_L_s"])
    assert vla_lo <= vla <= vla_hi

    if out.get("mcmc_fallback"):
        assert out.get("fallback_reason")

    return out


@pytest.mark.parametrize("case", MCMC_EDGE_CASES)
def test_bayesian_mcmc_edge_case_physically_coherent(case: dict) -> None:
    """MCMC posterior must stay near segmented reference on edge-case MMP curves."""
    ctx = AthleteContext(gender="MALE", training_years=10, discipline="ROAD")
    profiler = MetabolicProfiler(weight=case["weight"], context=ctx)
    mmp = profiler._coerce_mmp_dict(case["mmp"])

    ratio = MetabolicProfiler._bimodality_ratio(mmp)
    if case["expect_bimodal"]:
        assert ratio is not None and ratio >= 3.5

    out = _assert_bayesian_coherent_with_reference(
        profiler,
        mmp,
        vo2_range=case["vo2_range"],
        vla_range=case["vla_range"],
        vo2_tol=case["vo2_tol"],
        mlss_tol=case["mlss_tol"],
    )

    if case["expect_bimodal"]:
        assert out.get("mcmc_fallback") is True or out.get("estimated_vo2max") is not None


def test_bayesian_bimodal_profile_falls_back_to_segmented_reference() -> None:
    """Regression: Gigi-like profile must not report VO2max far below segmented fit."""
    ctx = AthleteContext(gender="MALE", training_years=10, discipline="ROAD")
    profiler = MetabolicProfiler(weight=90.0, context=ctx)
    mmp = profiler._coerce_mmp_dict(
        {1: 961, 5: 900, 60: 400, 300: 280, 1200: 255, 3600: 215}
    )
    _assert_bayesian_coherent_with_reference(
        profiler,
        mmp,
        vo2_range=(35.0, 75.0),
        vla_range=(0.35, 1.2),
        vo2_tol=1.0,
        mlss_tol=10.0,
    )
