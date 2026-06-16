"""Deprecated compatibility package. Use engines.readiness instead."""

import warnings

warnings.warn(
    "engines.readness is deprecated; import from engines.readiness",
    DeprecationWarning,
    stacklevel=2,
)

from engines.readiness import *  # noqa: F403,F401
