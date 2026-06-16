"""Power-curve history and best-effort aggregation."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from engines.core.metric_contracts import annotate_payload

_DEFAULT_DURATIONS = [1, 5, 10, 15, 20, 30, 60, 180, 300, 600, 1200, 1800, 3600, 5400]
_PERIOD_DAYS = {"last_6_weeks": 42, "last_90_days": 90, "season": 365, "all_time": None}


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _activity_mmp(activity: Dict[str, Any]) -> Dict[int, float]:
    raw = activity.get("mmp") or activity.get("power_curve") or activity.get("best_efforts") or {}
    if isinstance(raw, list):
        out: Dict[int, float] = {}
        for item in raw:
            if isinstance(item, dict):
                dur = item.get("duration_s") or item.get("duration")
                val = item.get("value") or item.get("power_w") or item.get("avg_power_w")
                if dur is not None and val is not None:
                    out[int(float(dur))] = float(val)
        return out
    if isinstance(raw, dict):
        return {int(float(k)): float(v) for k, v in raw.items() if _is_number(k) and _is_number(v)}
    return {}


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except Exception:
        return False


def _filter_period(activities: List[Dict[str, Any]], days: Optional[int], as_of: date) -> List[Dict[str, Any]]:
    if days is None:
        return activities
    start = as_of - timedelta(days=days)
    return [a for a in activities if (_parse_date(a.get("date") or a.get("start_date") or a.get("activity_date")) or as_of) >= start]


def aggregate_power_curve(activities: Iterable[Dict[str, Any]], durations_s: Optional[List[int]] = None) -> Dict[int, float]:
    curve: Dict[int, float] = {}
    durations = durations_s or _DEFAULT_DURATIONS
    for activity in activities:
        mmp = _activity_mmp(activity)
        for d in durations:
            if d in mmp:
                curve[d] = max(curve.get(d, 0.0), float(mmp[d]))
    return curve


def build_power_curve_history(
    activities: List[Dict[str, Any]],
    *,
    as_of: Optional[str] = None,
    durations_s: Optional[List[int]] = None,
    weight_kg: Optional[float] = None,
) -> Dict[str, Any]:
    ref = _parse_date(as_of) or date.today()
    periods: Dict[str, Any] = {}
    for name, days in _PERIOD_DAYS.items():
        subset = _filter_period(activities, days, ref)
        curve = aggregate_power_curve(subset, durations_s=durations_s)
        periods[name] = {
            "activity_count": len(subset),
            "curve": {str(k): round(v, 1) for k, v in sorted(curve.items())},
            "curve_w_kg": {str(k): round(v / weight_kg, 2) for k, v in sorted(curve.items())} if weight_kg and weight_kg > 0 else {},
        }
    payload = {"status": "success", "schema_version": "1.0.0", "periods": periods, "as_of": ref.isoformat()}
    return annotate_payload(payload, module_name="power_curve_history", method="period_curves", confidence=0.85 if activities else 0.2)
