"""Bayesian profiler must not collapse on bimodal sprint-heavy MMP curves."""

from __future__ import annotations

from engines.core.athlete_context import AthleteContext
from engines.metabolic.bayesian_profiler import bayesian_metabolic_snapshot
from engines.metabolic.metabolic_profiler import MetabolicProfiler


def test_bayesian_bimodal_profile_falls_back_to_segmented_reference() -> None:
    """Gigi-like profile: MCMC must not report VO2max far below segmented fit."""
    ctx = AthleteContext(gender="MALE", training_years=10, discipline="ROAD")
    profiler = MetabolicProfiler(weight=90.0, context=ctx)
    mmp = profiler._coerce_mmp_dict(
        {1: 961, 5: 900, 60: 400, 300: 280, 1200: 255, 3600: 215}
    )

    segmented = profiler.generate_metabolic_snapshot_segmented(mmp)
    bayes = bayesian_metabolic_snapshot(profiler, mmp, n_samples=1500, n_warmup=400)
    out = bayes.to_dict()

    assert segmented.get("status") == "success"
    assert bayes.status == "success"
    assert segmented.get("estimated_vo2max") is not None
    assert out.get("estimated_vo2max") is not None

    seg_vo2 = float(segmented["estimated_vo2max"])
    bayes_vo2 = float(out["estimated_vo2max"])
    assert abs(bayes_vo2 - seg_vo2) <= 1.0

    seg_mlss = float(segmented["mlss_power_watts"])
    bayes_mlss = float(out["mlss_power_watts"])
    assert abs(bayes_mlss - seg_mlss) <= 10.0

    if out.get("mcmc_fallback"):
        assert out.get("fallback_reason")
