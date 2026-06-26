"""Regression tests for medium-term audit cleanups."""

from __future__ import annotations


def test_mader_residual_mlp_canonical_import() -> None:
    from engines.performance.mader_residual_mlp import NeuralPowerDuration  # noqa: F401


def test_neural_ode_alias_reexports_canonical_symbols() -> None:
    from engines.performance import neural_ode

    assert neural_ode.NeuralPowerDuration is not None
    assert "NeuralPowerDuration" in neural_ode.__all__
