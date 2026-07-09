"""Athlete-level training thresholds from published MMP and coach overrides."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from engines.performance.mmp_aggregate import MMP_STATUS_PUBLISHED
from engines.physiology.metabolic_profile_calculator import best_available_power

SOURCE_COACH_OVERRIDE = "coach_override"
SOURCE_MMP_ESTIMATE = "mmp_estimate"

_FTP_FROM_20MIN = 0.95
_FTP_FROM_MAP = 0.75


def estimate_thresholds_from_mmp(
    mmp_curve: List[Dict[str, Any]],
    *,
    metabolic_profile: Optional[Dict[str, Any]] = None,
    coach_ftp_w: Optional[float] = None,
    coach_lthr_bpm: Optional[float] = None,
    mmp_status: str = MMP_STATUS_PUBLISHED,
) -> Dict[str, Any]:
    """Estimate FTP / CP from published aggregate MMP unless coach override supplied."""
    if mmp_status != MMP_STATUS_PUBLISHED:
        return {"status": "skipped", "reason": "MMP_NOT_PUBLISHED", "mmp_status": mmp_status}

    map_w = (metabolic_profile or {}).get("map_power_w")
    mlss = (metabolic_profile or {}).get("mlss_power_w")
    best_20 = best_available_power(mmp_curve, [1200])
    best_5 = best_available_power(mmp_curve, [300, 360, 420], fallback_duration=240, fallback_penalty=0.97)

    ftp_w: Optional[float] = None
    ftp_source = SOURCE_MMP_ESTIMATE
    if coach_ftp_w is not None and coach_ftp_w > 0:
        ftp_w = round(float(coach_ftp_w), 1)
        ftp_source = SOURCE_COACH_OVERRIDE
    elif best_20 is not None:
        ftp_w = round(best_20 * _FTP_FROM_20MIN, 1)
    elif map_w is not None:
        ftp_w = round(float(map_w) * _FTP_FROM_MAP, 1)
    elif best_5 is not None:
        ftp_w = round(best_5 * 0.88, 1)

    cp_w = mlss or best_20
    lthr_bpm = round(float(coach_lthr_bpm), 1) if coach_lthr_bpm else None

    if ftp_w is None and cp_w is None:
        return {"status": "error", "reason": "INSUFFICIENT_MMP_FOR_THRESHOLDS"}

    peak_1s = best_available_power(mmp_curve, [1, 5])
    w_prime_j = None
    if peak_1s is not None and cp_w is not None and peak_1s > cp_w:
        w_prime_j = round((peak_1s - float(cp_w)) * 60.0, 0)

    return {
        "status": "success",
        "ftp_w": ftp_w,
        "ftp_source": ftp_source,
        "cp_w": round(float(cp_w), 1) if cp_w else None,
        "lthr_bpm": lthr_bpm,
        "lthr_source": SOURCE_COACH_OVERRIDE if lthr_bpm else None,
        "w_prime_j": w_prime_j,
        "map_power_w": map_w,
        "mlss_power_w": mlss,
        "source_type": SOURCE_COACH_OVERRIDE if ftp_source == SOURCE_COACH_OVERRIDE else SOURCE_MMP_ESTIMATE,
        "warnings": [] if ftp_source == SOURCE_COACH_OVERRIDE else ["ftp_is_mmp_derived_not_lab_test"],
    }


def should_create_new_threshold_version(
    latest: Optional[Dict[str, Any]],
    new: Dict[str, Any],
) -> Tuple[bool, str]:
    if latest is None:
        return True, "first_thresholds"

    def _pct_delta(new_val: float, old_val: float) -> float:
        if old_val <= 0:
            return 1.0
        return abs(new_val - old_val) / old_val

    checks = [
        ("ftp_changed", "ftp_w", 0.03, True),
        ("cp_changed", "cp_w", 0.03, True),
        ("lthr_changed", "lthr_bpm", 0.02, True),
    ]
    for reason, key, threshold, is_ratio in checks:
        old_val = float(latest.get(key) or 0)
        new_val = float(new.get(key) or 0)
        if old_val <= 0 or new_val <= 0:
            continue
        delta = _pct_delta(new_val, old_val) if is_ratio else abs(new_val - old_val)
        if delta >= threshold:
            return True, reason

    if str(new.get("source_type")) == SOURCE_COACH_OVERRIDE and str(latest.get("source_type")) != SOURCE_COACH_OVERRIDE:
        return True, "coach_override_applied"

    return False, "changes_below_threshold"
