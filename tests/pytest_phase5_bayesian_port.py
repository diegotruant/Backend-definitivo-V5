"""Port of tests/integration/test_v400_bayesian.py for coverage."""

from __future__ import annotations

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.metabolic.bayesian_profiler import bayesian_metabolic_snapshot
from engines.metabolic.metabolic_profiler import MetabolicProfiler

CTX = AthleteContext(gender="MALE", training_years=5, discipline="ROAD")
MMP = {5: 950, 30: 620, 60: 470, 300: 340, 600: 305, 1200: 290, 3600: 270}


@pytest.fixture
def profiler() -> MetabolicProfiler:
    return MetabolicProfiler(weight=72, context=CTX)


class TestBayesianPort:
    def test_basic_mcmc_output(self, profiler: MetabolicProfiler) -> None:
        snap = bayesian_metabolic_snapshot(
            profiler,
            profiler._coerce_mmp_dict(MMP),
            n_samples=600,
            n_warmup=150,
        )
        assert snap.status == "success"
        assert snap.vo2max is not None and snap.vlamax is not None
        assert snap.vo2max.std > 0
        assert 0.05 <= snap.acceptance_rate <= 0.80

    def test_flat_mmp_runs(self, profiler: MetabolicProfiler) -> None:
        flat = {300: 300, 600: 300, 1200: 300, 3600: 300}
        flat_snap = bayesian_metabolic_snapshot(
            profiler,
            profiler._coerce_mmp_dict(flat),
            n_samples=400,
            n_warmup=100,
        )
        assert flat_snap.status == "success"
        assert flat_snap.vlamax is not None

    def test_edge_cases(self, profiler: MetabolicProfiler) -> None:
        sparse = bayesian_metabolic_snapshot(
            profiler,
            profiler._coerce_mmp_dict({60: 400}),
            n_samples=200,
            n_warmup=50,
        )
        assert sparse.status in {"success", "error", "insufficient_data"}

        extreme = bayesian_metabolic_snapshot(
            profiler,
            profiler._coerce_mmp_dict({5: 2000, 1200: 200}),
            n_samples=300,
            n_warmup=80,
        )
        assert extreme.status in {"success", "error", "insufficient_data"}

    def test_output_contract(self, profiler: MetabolicProfiler) -> None:
        snap = bayesian_metabolic_snapshot(
            profiler,
            profiler._coerce_mmp_dict(MMP),
            n_samples=400,
            n_warmup=100,
        )
        d = snap.to_dict()
        assert "status" in d
        assert "vo2max" in d or snap.vo2max is None
        if snap.vo2max:
            assert snap.vo2max.ci95_low < snap.vo2max.mean < snap.vo2max.ci95_high

    def test_confidence_from_prior_reduction(self, profiler: MetabolicProfiler) -> None:
        snap = bayesian_metabolic_snapshot(
            profiler,
            profiler._coerce_mmp_dict(MMP),
            n_samples=500,
            n_warmup=120,
            prior_vo2_mean=50.0,
            prior_vla_mean=0.35,
        )
        assert snap.status == "success"
        assert 0.0 <= snap.bayesian_confidence <= 1.0
