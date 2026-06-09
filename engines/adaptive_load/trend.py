"""Longitudinal load trend helpers for adaptive load."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import numpy as np

from engines.performance.training_variability_engine import calculate_acwr, calculate_monotony_strain


def ewma(values: Iterable[float], span: int) -> Optional[float]:
    vals = [float(v) for v in values if v is not None and np.isfinite(float(v))]
    if not vals:
        return None
    alpha = 2.0 / (span + 1.0)
    out = vals[0]
    for value in vals[1:]:
        out = alpha * value + (1.0 - alpha) * out
    return float(out)


def extract_history_loads(history: Optional[list[Dict[str, Any]]]) -> list[float]:
    """Accept flexible persisted history payloads and return daily/session loads."""
    if not history:
        return []
    loads: list[float] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        value = (
            item.get("session_load_score")
            or item.get("session_load")
            or item.get("adaptive_load")
            or item.get("tss")
            or item.get("load")
        )
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(v) and v >= 0:
            loads.append(v)
    return loads


def calculate_load_trend(
    history: Optional[list[Dict[str, Any]]],
    current_session_load: Optional[float],
) -> Dict[str, Any]:
    loads = extract_history_loads(history)
    if current_session_load is not None:
        loads.append(float(current_session_load))

    if len(loads) < 7:
        return {
            "status": "insufficient_data",
            "days_available": len(loads),
            "atl_7d": None,
            "ctl_42d": None,
            "tsb": None,
            "load_ratio": None,
            "monotony": None,
            "strain": None,
            "message": "Need at least 7 daily/session load values for trend metrics.",
        }

    atl = ewma(loads[-14:], span=7)
    ctl = ewma(loads[-56:], span=42)
    tsb = None if atl is None or ctl is None else ctl - atl

    last_7 = loads[-7:]
    chronic = loads[-42:] if len(loads) >= 42 else loads
    chronic_mean = float(np.mean(chronic)) if chronic else 0.0
    load_ratio = float(np.mean(last_7) / chronic_mean) if chronic_mean > 0 else None

    acwr = calculate_acwr(atl, ctl) if atl is not None and ctl is not None and ctl > 0 else None
    monotony = calculate_monotony_strain(last_7)

    return {
        "status": "success",
        "days_available": len(loads),
        "atl_7d": round(atl, 1) if atl is not None else None,
        "ctl_42d": round(ctl, 1) if ctl is not None else None,
        "tsb": round(tsb, 1) if tsb is not None else None,
        "load_ratio": round(load_ratio, 2) if load_ratio is not None else None,
        "acwr": acwr,
        "monotony": monotony.get("monotony") if isinstance(monotony, dict) else None,
        "strain": monotony.get("strain") if isinstance(monotony, dict) else None,
        "monotony_status": monotony.get("monotony_status") if isinstance(monotony, dict) else None,
    }
