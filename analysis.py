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
