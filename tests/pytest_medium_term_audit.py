"""Regression tests for medium-term audit cleanups."""

from __future__ import annotations

import warnings

import pytest


def test_mader_residual_mlp_canonical_import() -> None:
    from engines.performance.mader_residual_mlp import NeuralPowerDuration  # noqa: F401


def test_neural_ode_alias_emits_deprecation_warning() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import importlib

        importlib.reload(importlib.import_module("engines.performance.neural_ode"))
    assert any(
        issubclass(w.category, DeprecationWarning) and "mader_residual_mlp" in str(w.message)
        for w in caught
    )
