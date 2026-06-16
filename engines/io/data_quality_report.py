"""Data quality report for parsed activity streams."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

from engines.core.metric_contracts import annotate_payload


def _series_quality(values: Any, *, valid_min: Optional[float] = None, valid_max: Optional[float] = None) -> Dict[str, Any]:
    if values is None:
        return {"available": False, "coverage_pct": 0.0, "dropout_pct": 100.0, "notes": ["missing_signal"]}
    try:
        arr = np.asarray(values, dtype=float)
    except Exception:
        return {"available": False, "coverage_pct": 0.0, "dropout_pct": 100.0, "notes": ["unreadable_signal"]}
    if arr.size == 0:
        return {"available": False, "coverage_pct": 0.0, "dropout_pct": 100.0, "notes": ["empty_signal"]}
    mask = np.isfinite(arr)
    if valid_min is not None:
        mask &= arr >= valid_min
    if valid_max is not None:
        mask &= arr <= valid_max
    coverage = float(mask.sum() / arr.size * 100.0)
    notes = []
    if coverage < 50:
        notes.append("low_coverage")
    elif coverage < 90:
        notes.append("partial_coverage")
    return {"available": bool(mask.any()), "coverage_pct": round(coverage, 1), "dropout_pct": round(100.0 - coverage, 1), "notes": notes}


def _quality_flags(flags: Any) -> Dict[str, Any]:
    if flags is None:
        return {"available": False}
    try:
        arr = np.asarray(flags)
    except Exception:
        return {"available": False}
    if arr.size == 0:
        return {"available": False}
    counts = {str(int(k)): int(v) for k, v in zip(*np.unique(arr, return_counts=True))}
    unreliable = int(counts.get("3", 0))
    return {"available": True, "counts": counts, "unreliable_pct": round(unreliable / arr.size * 100.0, 1)}


def build_data_quality_report(stream: Any) -> Dict[str, Any]:
    """Return signal coverage, dropout and warning information."""
    signals = {
        "power": _series_quality(getattr(stream, "power", None), valid_min=1),
        "heart_rate": _series_quality(getattr(stream, "heart_rate", None), valid_min=30, valid_max=240),
        "cadence": _series_quality(getattr(stream, "cadence", None), valid_min=1, valid_max=250),
        "speed": _series_quality(getattr(stream, "speed_mps", None), valid_min=0),
        "altitude": _series_quality(getattr(stream, "altitude_m", None)),
        "temperature": _series_quality(getattr(stream, "temperature_c", None), valid_min=-30, valid_max=60),
        "respiration": _series_quality(getattr(stream, "respiration_rate", None), valid_min=1, valid_max=80),
        "left_right_balance": _series_quality(getattr(stream, "left_right_balance", None), valid_min=0, valid_max=100),
    }
    flags = {
        "power": _quality_flags(getattr(stream, "quality_power", None)),
        "heart_rate": _quality_flags(getattr(stream, "quality_hr", None)),
    }
    available = [name for name, info in signals.items() if info.get("available")]
    warnings = []
    for name, info in signals.items():
        if info.get("available") and info.get("coverage_pct", 0) < 90:
            warnings.append(f"{name}_partial_coverage")
    score = 0.0
    weights = {"power": 0.35, "heart_rate": 0.2, "cadence": 0.1, "speed": 0.1, "altitude": 0.1, "temperature": 0.05, "respiration": 0.05, "left_right_balance": 0.05}
    for key, weight in weights.items():
        score += weight * (signals[key].get("coverage_pct", 0.0) / 100.0)
    payload = {
        "status": "success",
        "schema_version": "1.0.0",
        "overall_score": round(max(0.0, min(1.0, score)), 3),
        "available_signals": available,
        "signals": signals,
        "quality_flags": flags,
        "warnings": warnings,
        "gap_summary": getattr(stream, "gap_summary", {}) or {},
    }
    return annotate_payload(payload, module_name="data_quality_report", method="signal_coverage", confidence=1.0)
