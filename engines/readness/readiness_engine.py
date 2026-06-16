"""Deprecated compatibility path. Use engines.readiness instead."""

import warnings

warnings.warn(
    "engines.readness is deprecated; import from engines.readiness",
    DeprecationWarning,
    stacklevel=2,
)

from engines.readiness.readiness_engine import *  # noqa: F403,F401
