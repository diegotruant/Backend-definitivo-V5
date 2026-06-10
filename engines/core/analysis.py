"""
Compatibility shim for clean_rr_intervals.

This is a minimal in-package implementation that replaces the original
external dependency. Applies:
- Physiological RR range filter (300-2000 ms)
- Beat-to-beat outlier removal (>20% relative jump)
- Returns cleaned array, preserves length where possible
"""

import numpy as np
from typing import Union, Sequence


def clean_rr_intervals(
    rr_ms: Union[np.ndarray, Sequence[float]],
    min_rr_ms: float = 300.0,
    max_rr_ms: float = 2000.0,
    max_rel_jump: float = 0.20,
) -> np.ndarray:
    """
    Clean RR intervals by removing physiologically impossible values
    and beat-to-beat outliers.
    
    Note: this is a basic implementation. The hrv_engine module performs
    additional artifact detection and ectopic correction internally.
    """
    rr = np.asarray(rr_ms, dtype=float)
    if rr.size == 0:
        return rr
    
    # Physiological range
    valid = (rr >= min_rr_ms) & (rr <= max_rr_ms)
    
    # Beat-to-beat outliers (relative jump)
    if rr.size > 1:
        prev = np.concatenate([[rr[0]], rr[:-1]])
        rel_jump = np.abs(rr - prev) / np.maximum(prev, 1.0)
        valid &= rel_jump <= max_rel_jump
    
    return rr[valid]


def safe_dt(t: Union[np.ndarray, Sequence[float]], default: float = 1.0) -> float:
    """Median sampling interval (dt) from a time vector, robust to degenerate input.

    Returns `default` (1.0 s, the FIT default sampling rate) whenever a real dt
    cannot be computed — i.e. when the time vector is too short, or when the
    elapsed timestamps are all-equal / non-monotonic (which happens with real
    devices that fail GPS sync or emit a corrupt time field). This guarantees
    callers can safely divide by the result without a ZeroDivisionError.

    Parameters
    ----------
    t       : time vector (seconds)
    default : fallback dt when none can be derived (default 1.0)

    Returns
    -------
    A strictly positive, finite float.
    """
    arr = np.asarray(t, dtype=float)
    if arr.size < 2:
        return default
    diffs = np.diff(arr)
    # keep only positive, finite steps — discards zeros and time going backwards
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return default
    dt = float(np.median(diffs))
    if not np.isfinite(dt) or dt <= 0:
        return default
    return dt
