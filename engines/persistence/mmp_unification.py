"""Unify Supabase athlete MMP aggregate with TwinState rolling_power_curve."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.performance.mmp_aggregate import MMP_STATUS_PUBLISHED

CANONICAL_MMP_SOURCE = "athlete_mmp_aggregate"


def aggregate_curve_to_rolling_curve(mmp_curve: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Convert aggregate MMP point list into twin ``rolling_power_curve`` dict format.

    Keys are duration strings; values are CurveEntry-compatible dicts.
    """
    rolling: Dict[str, Any] = {}
    for row in mmp_curve or []:
        if not isinstance(row, dict):
            continue
        try:
            duration_s = int(row["duration_s"])
            power_w = float(row["power_w"])
        except (KeyError, TypeError, ValueError):
            continue
        if duration_s <= 0 or power_w <= 0:
            continue
        rolling[str(duration_s)] = {
            "duration_s": duration_s,
            "power_w": round(power_w, 1),
            "ride_id": str(row.get("source_activity_id") or ""),
            "ride_date": str(row.get("activity_date") or "")[:10],
            "reliability": 1.0,
            "source": CANONICAL_MMP_SOURCE,
        }
    return rolling


def resolve_canonical_rolling_curve(
    *,
    aggregate_record: Optional[Dict[str, Any]],
    legacy_rolling_curve: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Prefer published aggregate MMP for twin curve; fall back to legacy rolling curve.
    """
    aggregate = aggregate_record or {}
    mmp_status = str(aggregate.get("mmp_status") or "")
    curve = aggregate.get("mmp_curve_json") or []
    if mmp_status == MMP_STATUS_PUBLISHED and curve:
        return {
            "curve": aggregate_curve_to_rolling_curve(curve),
            "source": CANONICAL_MMP_SOURCE,
            "mmp_status": mmp_status,
            "n_points": len(curve),
        }
    if legacy_rolling_curve:
        return {
            "curve": dict(legacy_rolling_curve),
            "source": "mmp_aggregator_rolling_window",
            "mmp_status": mmp_status or "unknown",
            "n_points": len(legacy_rolling_curve),
        }
    return {
        "curve": {},
        "source": "none",
        "mmp_status": mmp_status or "collecting",
        "n_points": 0,
    }


def apply_canonical_curve_to_twin_state(
    state: Dict[str, Any],
    *,
    aggregate_record: Optional[Dict[str, Any]],
    legacy_rolling_curve: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach canonical MMP curve metadata to a TwinState dict."""
    resolved = resolve_canonical_rolling_curve(
        aggregate_record=aggregate_record,
        legacy_rolling_curve=legacy_rolling_curve or state.get("rolling_power_curve"),
    )
    state = dict(state)
    state["rolling_power_curve"] = resolved["curve"]
    state["mmp_curve_meta"] = {
        "source": resolved["source"],
        "mmp_status": resolved["mmp_status"],
        "n_points": resolved["n_points"],
    }
    return state
