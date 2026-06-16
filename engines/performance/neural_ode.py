"""Deprecated alias for :mod:`engines.performance.mader_residual_mlp`.

The historical name ``neural_ode`` suggested a Chen-2018-style Neural ODE. The
implementation is a physics-informed residual MLP that corrects Mader predictions.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "engines.performance.neural_ode is deprecated; "
    "import from engines.performance.mader_residual_mlp",
    DeprecationWarning,
    stacklevel=2,
)

from engines.performance.mader_residual_mlp import (  # noqa: E402
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
