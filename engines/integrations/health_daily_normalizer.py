"""Normalize daily health sync payloads from athlete app vendors (Oura, Google Health)."""

from __future__ import annotations

from typing import Any, Dict, Optional


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_health_daily(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Map vendor-specific calorie and metadata keys to the daily_energy contract."""
    raw = dict(payload or {})
    nested = raw.get("energy") if isinstance(raw.get("energy"), dict) else {}
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}

    total = _num(
        raw.get("total_calories_kcal")
        or raw.get("total_calories")
        or raw.get("calories_total")
        or raw.get("totalEnergyBurned")
        or nested.get("total_calories_kcal")
        or metrics.get("total_calories_kcal")
    )
    active = _num(
        raw.get("active_calories_kcal")
        or raw.get("active_calories")
        or raw.get("activeEnergyBurned")
        or raw.get("activity_calories_kcal")
        or nested.get("active_calories_kcal")
        or metrics.get("active_calories_kcal")
    )
    basal = _num(
        raw.get("basal_calories_kcal")
        or raw.get("basal_calories")
        or raw.get("basalEnergyBurned")
        or raw.get("bmr_kcal")
        or raw.get("resting_calories_kcal")
        or nested.get("basal_calories_kcal")
        or metrics.get("basal_calories_kcal")
    )

    if total is None and active is not None and basal is not None:
        total = round(active + basal, 1)

    source = (
        raw.get("source")
        or raw.get("provider")
        or raw.get("data_source")
        or "unknown"
    )
    date = raw.get("date") or raw.get("day") or raw.get("local_date")

    steps = _num(raw.get("steps") or metrics.get("steps"))
    distance_m = _num(raw.get("distance_m") or raw.get("distance") or metrics.get("distance_m"))

    return {
        "date": date,
        "source": str(source).lower(),
        "total_calories_kcal": total,
        "active_calories_kcal": active,
        "basal_calories_kcal": basal,
        "steps": int(steps) if steps is not None else None,
        "distance_m": distance_m,
        "raw": raw,
    }
