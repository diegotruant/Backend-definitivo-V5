"""Data contracts for the adaptive load engine.

The engine is intentionally stateless: callers pass the current activity stream,
optional daily readiness values, and optional historical daily loads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AthleteLoadProfile:
    """Minimal athlete parameters needed for load/readiness interpretation."""

    weight_kg: float
    ftp: Optional[float] = None
    hr_max: Optional[float] = None
    hr_rest: Optional[float] = None
    lthr: Optional[float] = None


@dataclass(frozen=True)
class DailyStatus:
    """Morning/night status supplied by the caller, usually from wearable + diary."""

    morning_hrv_lnrmssd: Optional[float] = None
    baseline_hrv_lnrmssd: Optional[float] = None
    morning_rhr: Optional[float] = None
    baseline_rhr: Optional[float] = None
    morning_temp_c: Optional[float] = None
    baseline_temp_c: Optional[float] = None
    sleep_score: Optional[float] = None  # 0..100
    soreness: Optional[float] = None     # 1..5, higher = worse
    stress: Optional[float] = None       # 1..5, higher = worse
    mood: Optional[float] = None         # 1..5, higher = better

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> Optional["DailyStatus"]:
        if not raw:
            return None
        return cls(
            morning_hrv_lnrmssd=_as_float(raw.get("morning_hrv_lnrmssd")),
            baseline_hrv_lnrmssd=_as_float(raw.get("baseline_hrv_lnrmssd")),
            morning_rhr=_as_float(raw.get("morning_rhr")),
            baseline_rhr=_as_float(raw.get("baseline_rhr")),
            morning_temp_c=_as_float(raw.get("morning_temp_c") or raw.get("morning_temp")),
            baseline_temp_c=_as_float(raw.get("baseline_temp_c") or raw.get("baseline_temp")),
            sleep_score=_as_float(raw.get("sleep_score")),
            soreness=_as_float(raw.get("soreness")),
            stress=_as_float(raw.get("stress")),
            mood=_as_float(raw.get("mood")),
        )


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
