"""Compatibility alias for :mod:`engines.performance.mader_residual_mlp`.

The historical name ``neural_ode`` suggested a Chen-2018-style Neural ODE. The
implementation is a physics-informed residual MLP that corrects Mader predictions.
New code should import from ``engines.performance.mader_residual_mlp``.
"""

from __future__ import annotations

from engines.performance.mader_residual_mlp import (
    DynamicsTrainingResult,
    NeuralDynamics,
    NeuralPDTrainingResult,
    NeuralPowerDuration,
    TinyMLP,
)

__all__ = [
    "DynamicsTrainingResult",
    "NeuralDynamics",
    "NeuralPDTrainingResult",
    "NeuralPowerDuration",
    "TinyMLP",
]
