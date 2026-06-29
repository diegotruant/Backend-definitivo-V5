"""Morning readiness scoring for adaptive load."""

from __future__ import annotations

from typing import Any, Dict, Optional

from engines.adaptive_load.models import DailyStatus
from engines.adaptive_load.scoring import score_from_high_is_bad, score_from_low_is_bad, weighted_score


def _score_hrv(status: DailyStatus) -> Optional[float]:
    if status.morning_hrv_lnrmssd is None or status.baseline_hrv_lnrmssd is None:
        return None
    delta = status.morning_hrv_lnrmssd - status.baseline_hrv_lnrmssd
    # lnRMSSD within roughly -0.05..+0.05 of baseline is normal; -0.35 is a clear dip.
    if delta >= 0.05:
        return 100.0
    if delta <= -0.35:
        return 20.0
    return round(20.0 + ((delta + 0.35) / 0.40) * 80.0, 1)


def _score_rhr(status: DailyStatus) -> Optional[float]:
    if status.morning_rhr is None or status.baseline_rhr is None:
        return None
    delta = status.morning_rhr - status.baseline_rhr
    return score_from_high_is_bad(delta, good=0.0, bad=10.0)


def _score_temp(status: DailyStatus) -> Optional[float]:
    if status.morning_temp_c is None or status.baseline_temp_c is None:
        return None
    delta = status.morning_temp_c - status.baseline_temp_c
    return score_from_high_is_bad(delta, good=0.0, bad=0.8)


def _score_sleep(status: DailyStatus) -> Optional[float]:
    if status.sleep_score is None:
        return None
    sleep_score = float(status.sleep_score)
    if 0.0 <= sleep_score <= 1.0:
        sleep_score *= 100.0
    return score_from_low_is_bad(sleep_score, bad=35.0, good=90.0)


def _score_inverse_1_to_5(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return score_from_high_is_bad(value, good=1.0, bad=5.0)


def _score_positive_1_to_5(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return score_from_low_is_bad(value, bad=1.0, good=5.0)


def calculate_readiness(daily_status: Optional[DailyStatus]) -> Dict[str, Any]:
    if daily_status is None:
        return {
            "available": False,
            "score": None,
            "status": "unavailable",
            "reason": "NO_DAILY_STATUS_PROVIDED",
        }

    hrv = _score_hrv(daily_status)
    rhr = _score_rhr(daily_status)
    temp = _score_temp(daily_status)
    sleep = _score_sleep(daily_status)
    soreness = _score_inverse_1_to_5(daily_status.soreness)
    stress = _score_inverse_1_to_5(daily_status.stress)
    mood = _score_positive_1_to_5(daily_status.mood)

    subjective = weighted_score(((soreness, 0.35), (stress, 0.35), (mood, 0.30)))
    score = weighted_score(
        (
            (hrv, 0.35),
            (rhr, 0.20),
            (temp, 0.15),
            (sleep, 0.15),
            (subjective, 0.15),
        )
    )

    if score is None:
        status = "insufficient_data"
    elif score >= 80:
        status = "high"
    elif score >= 65:
        status = "normal"
    elif score >= 50:
        status = "reduced"
    else:
        status = "low"

    flags = []
    if hrv is not None and hrv < 50:
        flags.append("hrv_below_baseline")
    if rhr is not None and rhr < 60:
        flags.append("rhr_elevated")
    if temp is not None and temp < 60:
        flags.append("temperature_elevated")
    if sleep is not None and sleep < 55:
        flags.append("sleep_low")
    if subjective is not None and subjective < 55:
        flags.append("subjective_stress_high")

    return {
        "available": score is not None,
        "score": score,
        "status": status,
        "components": {
            "hrv": hrv,
            "rhr": rhr,
            "temperature": temp,
            "sleep": sleep,
            "subjective": subjective,
            "soreness": soreness,
            "stress": stress,
            "mood": mood,
        },
        "flags": flags,
        "weights": {
            "hrv": 0.35,
            "rhr": 0.20,
            "temperature": 0.15,
            "sleep": 0.15,
            "subjective": 0.15,
        },
    }
