"""Training-load trend summaries from persisted activity metadata."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _load_value(activity: Dict[str, Any]) -> float:
    for key in ("training_load", "tss", "load", "workout_load"):
        value = activity.get(key)
        if value is not None:
            try:
                return max(0.0, float(value))
            except Exception:
                pass
    summary = activity.get("summary") or {}
    if isinstance(summary, dict):
        for key in ("training_stress_score", "tss"):
            value = summary.get(key)
            if value is not None:
                try:
                    return max(0.0, float(value))
                except Exception:
                    pass
    return 0.0


def _daily_loads(activities: List[Dict[str, Any]], as_of: date, window_days: int) -> List[float]:
    start = as_of - timedelta(days=window_days - 1)
    days = {start + timedelta(days=i): 0.0 for i in range(window_days)}
    for act in activities:
        d = _parse_date(act.get("date") or act.get("start_date") or act.get("activity_date"))
        if d in days:
            days[d] += _load_value(act)
    return [days[d] for d in sorted(days)]


def _ewma(values: List[float], tau_days: float) -> float:
    if not values:
        return 0.0
    alpha = 1.0 - pow(2.718281828, -1.0 / max(tau_days, 1.0))
    state = 0.0
    for v in values:
        state = state + alpha * (float(v) - state)
    return state


def compute_load_trends(activities: List[Dict[str, Any]], *, as_of: Optional[str] = None) -> Dict[str, Any]:
    if not activities:
        payload = {
            "status": "insufficient_data",
            "schema_version": "1.0.0",
            "reason": "no_activities",
            "as_of": date.today().isoformat(),
            "acute_load": 0.0,
            "chronic_load": 0.0,
            "load_balance": 0.0,
            "last_7d_load": 0.0,
            "previous_7d_load": 0.0,
            "weekly_ramp_rate": 0.0,
            "risk": "unknown",
            "daily_loads_90d": [],
        }
        return annotate_payload(payload, module_name="load_trends", method="ewma_load_state", confidence=0.1)
    ref = _parse_date(as_of) or date.today()
    loads_90 = _daily_loads(activities, ref, 90)
    acute = _ewma(loads_90[-28:], 7.0)
    chronic = _ewma(loads_90, 42.0)
    balance = chronic - acute
    last_7 = sum(loads_90[-7:])
    prev_7 = sum(loads_90[-14:-7])
    ramp_rate = last_7 - prev_7
    risk = "low"
    if acute > chronic * 1.4 and acute > 30:
        risk = "high"
    elif acute > chronic * 1.2 and acute > 20:
        risk = "moderate"
    payload = {
        "status": "success",
        "schema_version": "1.0.0",
        "as_of": ref.isoformat(),
        "acute_load": round(acute, 1),
        "chronic_load": round(chronic, 1),
        "load_balance": round(balance, 1),
        "last_7d_load": round(last_7, 1),
        "previous_7d_load": round(prev_7, 1),
        "weekly_ramp_rate": round(ramp_rate, 1),
        "risk": risk,
        "daily_loads_90d": [round(v, 1) for v in loads_90],
    }
    return annotate_payload(payload, module_name="load_trends", method="ewma_load_state", confidence=0.8 if activities else 0.2)
