"""Regression tests for immediate audit fixes (import path, asserts, W' dt)."""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.w_prime_balance_engine import calculate_w_prime_balance


def test_metabolic_profiler_clean_mmp_first_uses_package_import() -> None:
    """clean_mmp_first=True must not rely on flat mmp_quality import."""
    mmp = {"5": 900, "60": 500, "300": 350, "1200": 280, "3600": 240}
    profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
    snap = profiler.generate_metabolic_snapshot(mmp, clean_mmp_first=True)
    assert "mmp_quality" in snap
    assert "analysis" in snap["mmp_quality"]


def test_w_prime_balance_respects_dt_s() -> None:
    w_prime = 1000.0
    tau = 10.0
    cp = 100.0
    power = [100.0, 200.0, 50.0]

    balance_1hz = calculate_w_prime_balance(power, cp=cp, w_prime=w_prime, tau=tau, dt_s=1.0)
    balance_2hz = calculate_w_prime_balance(power, cp=cp, w_prime=w_prime, tau=tau, dt_s=2.0)

    assert balance_1hz[1] == 900.0  # (200-100)*1
    assert balance_2hz[1] == 800.0  # (200-100)*2
    expected_recovery = 800.0 + (w_prime - 800.0) * (1.0 - np.exp(-2.0 / tau))
    assert abs(balance_2hz[-1] - expected_recovery) < 1e-6


def test_w_prime_balance_warns_on_sampling_mismatch() -> None:
    power = [200.0] * 120  # 120 samples
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        calculate_w_prime_balance(
            power,
            cp=100.0,
            w_prime=20_000.0,
            dt_s=1.0,
            duration_s=60.0,  # ~2 Hz implied vs 1 Hz dt_s
        )
    assert any("sampling rate" in str(w.message).lower() for w in caught)


def test_w_prime_balance_rejects_non_positive_dt() -> None:
    with pytest.raises(ValueError, match="dt_s must be positive"):
        calculate_w_prime_balance([100.0, 120.0], cp=100.0, w_prime=1000.0, dt_s=0.0)
