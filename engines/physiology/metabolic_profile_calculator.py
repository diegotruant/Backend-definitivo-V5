"""
Athlete-level metabolic profile from published aggregate MMP.

Stable athlete profiles are computed only from ``athlete_mmp_aggregate`` when
``mmp_status == published``. Per-activity metabolic estimates must not be
promoted to athlete profile.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from engines.performance.mmp_aggregate import MMP_DURATION_FAMILIES, MMP_STATUS_PUBLISHED

CONFIDENCE_LOW = "LOW"
CONFIDENCE_MODERATE = "MODERATE"
CONFIDENCE_HIGH = "HIGH"

PROFILE_STATUS_PUBLISHED = "published"
PROFILE_STATUS_PROVISIONAL = "provisional"


def _curve_map(mmp_curve: Sequence[Dict[str, Any]]) -> Dict[int, float]:
    out: Dict[int, float] = {}
    for row in mmp_curve or []:
        if not isinstance(row, dict):
            continue
        try:
            duration_s = int(row["duration_s"])
            power_w = float(row["power_w"])
        except (KeyError, TypeError, ValueError):
            continue
        if duration_s > 0 and power_w > 0:
            out[duration_s] = max(out.get(duration_s, 0.0), power_w)
    return out


def best_available_power(
    mmp_curve: Sequence[Dict[str, Any]],
    durations: Sequence[int],
    *,
    conservative_factor: float = 1.0,
    fallback_duration: Optional[int] = None,
    fallback_penalty: float = 1.0,
) -> Optional[float]:
    """Return best power (W) for preferred durations with optional fallback."""
    by_duration = _curve_map(mmp_curve)
    values = [by_duration[d] for d in durations if d in by_duration]
    if values:
        return round(max(values) * conservative_factor, 1)
    if fallback_duration is not None and fallback_duration in by_duration:
        return round(by_duration[fallback_duration] * fallback_penalty * conservative_factor, 1)
    return None


def _family_covered(mmp_curve: Sequence[Dict[str, Any]], family: str) -> bool:
    durations = MMP_DURATION_FAMILIES.get(family, [])
    by_duration = _curve_map(mmp_curve)
    return any(d in by_duration for d in durations)


def calculate_metabolic_profile_confidence(
    mmp_curve: List[Dict[str, Any]],
    readiness: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Score profile confidence from MMP family coverage and activity count.

    Returns confidence_score, confidence_tier (LOW|MODERATE|HIGH), warnings.
    """
    warnings: List[str] = []
    score = 0.0

    if _family_covered(mmp_curve, "sprint"):
        score += 0.15
    else:
        warnings.append("missing_sprint_family")

    if _family_covered(mmp_curve, "anaerobic"):
        score += 0.15
    else:
        warnings.append("missing_anaerobic_family")

    if _family_covered(mmp_curve, "vo2_map"):
        score += 0.25
    else:
        warnings.append("missing_map_family")

    if _family_covered(mmp_curve, "threshold"):
        score += 0.25
    else:
        warnings.append("missing_threshold_family")

    if _family_covered(mmp_curve, "endurance"):
        score += 0.10
    else:
        warnings.append("missing_endurance_family")

    n_activities = int(readiness.get("n_activities_included") or 0)
    if n_activities >= 8:
        score += 0.10
    elif n_activities < 5:
        warnings.append("low_activity_count")

    score = min(round(score, 4), 1.0)

    if score >= 0.75:
        tier = CONFIDENCE_HIGH
    elif score >= 0.50:
        tier = CONFIDENCE_MODERATE
    else:
        tier = CONFIDENCE_LOW

    if not _family_covered(mmp_curve, "vo2_map") or not _family_covered(mmp_curve, "threshold"):
        warnings.append("profile_cannot_be_published_without_map_and_threshold")

    return {
        "confidence_score": score,
        "confidence_tier": tier,
        "warnings": warnings,
    }


def _estimate_vlamax(apr_w: float, map_power_w: float, mlss_power_w: float) -> float:
    apr_ratio = apr_w / max(map_power_w, 1.0)
    if apr_ratio < 1.4:
        base = 0.25
    elif apr_ratio < 1.8:
        base = 0.35
    elif apr_ratio < 2.2:
        base = 0.475
    else:
        base = 0.65

    mlss_fraction = mlss_power_w / max(map_power_w, 1.0)
    if mlss_fraction > 0.78:
        base -= 0.03
    elif mlss_fraction < 0.70:
        base += 0.03

    return round(max(0.15, min(base, 0.80)), 3)


def _estimate_fatmax(mlss_power_w: float, vlamax: float) -> float:
    if vlamax < 0.30:
        fatmax = mlss_power_w * 0.65
    elif vlamax < 0.45:
        fatmax = mlss_power_w * 0.58
    else:
        fatmax = mlss_power_w * 0.50
    return round(fatmax / 5.0) * 5.0


def _classify_phenotype(
    *,
    vlamax: float,
    mlss_power_w: float,
    map_power_w: float,
) -> Tuple[str, str]:
    mlss_map = mlss_power_w / max(map_power_w, 1.0)
    if vlamax < 0.30 and mlss_map > 0.78:
        return (
            "endurance_leaning",
            "Profilo orientato all'endurance, buona sostenibilità dello sforzo e richiesta glicolitica contenuta.",
        )
    if 0.30 <= vlamax <= 0.50:
        return (
            "balanced",
            "Profilo bilanciato, adatto a granfondo e MTB con buona capacità di cambio ritmo.",
        )
    return (
        "glycolytic_leaning",
        "Profilo con forte riserva anaerobica e buona capacità di picco, ma possibile costo metabolico elevato negli sforzi prolungati.",
    )


def calculate_metabolic_profile_from_mmp(
    mmp_curve: List[Dict[str, Any]],
    athlete_data: Dict[str, Any],
    readiness: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compute stable athlete metabolic profile from aggregate MMP.

    Only meaningful when ``readiness["mmp_status"] == "published"``.
    """
    mmp_status = str(readiness.get("mmp_status") or "")
    if mmp_status != MMP_STATUS_PUBLISHED:
        return {
            "status": "skipped",
            "reason": "MMP_NOT_PUBLISHED",
            "mmp_status": mmp_status,
            "profile_status": None,
        }

    weight_kg = float(athlete_data.get("weight_kg") or 70.0)
    confidence = calculate_metabolic_profile_confidence(mmp_curve, readiness)
    warnings = list(confidence["warnings"])

    map_power_w = best_available_power(mmp_curve, [300, 360, 420], fallback_duration=240, fallback_penalty=0.97)
    if map_power_w is None:
        return {
            "status": "error",
            "reason": "MISSING_MAP_DURATIONS",
            "warnings": warnings + ["cannot_estimate_map"],
        }

    mlss_power_w = best_available_power(mmp_curve, [1800, 2400])
    mlss_conservative = False
    if mlss_power_w is None:
        mlss_1200 = best_available_power(mmp_curve, [1200])
        if mlss_1200 is None:
            return {
                "status": "error",
                "reason": "MISSING_THRESHOLD_DURATIONS",
                "warnings": warnings + ["cannot_estimate_mlss"],
            }
        mlss_power_w = round(mlss_1200 * 0.93, 1)
        mlss_conservative = True
        warnings.append("mlss_estimated_from_1200s_with_penalty")

    peak_1s = best_available_power(mmp_curve, [1, 5])
    if peak_1s is None:
        peak_1s = best_available_power(mmp_curve, [10, 15], conservative_factor=0.98)
    if peak_1s is None:
        return {
            "status": "error",
            "reason": "MISSING_SPRINT_DURATIONS",
            "warnings": warnings + ["cannot_estimate_apr"],
        }

    apr_w = round(peak_1s - map_power_w, 1)
    vlamax_mmol_l_s = _estimate_vlamax(apr_w, map_power_w, mlss_power_w)
    fatmax_power_w = _estimate_fatmax(mlss_power_w, vlamax_mmol_l_s)

    # Documented MAP-based aerobic power proxy (not direct lab VO2max).
    vo2max_ml_kg_min = round((map_power_w / max(weight_kg, 1.0)) * 10.8 + 7.0, 1)

    phenotype_type, phenotype_description = _classify_phenotype(
        vlamax=vlamax_mmol_l_s,
        mlss_power_w=mlss_power_w,
        map_power_w=map_power_w,
    )

    if mlss_conservative:
        confidence["confidence_score"] = round(max(0.0, confidence["confidence_score"] - 0.08), 4)
        if confidence["confidence_score"] < 0.50:
            confidence["confidence_tier"] = CONFIDENCE_LOW
        elif confidence["confidence_score"] < 0.75:
            confidence["confidence_tier"] = CONFIDENCE_MODERATE

    profile_status = PROFILE_STATUS_PUBLISHED
    if confidence["confidence_tier"] == CONFIDENCE_LOW:
        profile_status = PROFILE_STATUS_PROVISIONAL
        warnings.append("low_confidence_profile_marked_provisional")

    if "profile_cannot_be_published_without_map_and_threshold" in warnings:
        profile_status = PROFILE_STATUS_PROVISIONAL

    warnings.append("vlamax_is_model_derived_not_direct_measurement")

    return {
        "status": "success",
        "vo2max_ml_kg_min": vo2max_ml_kg_min,
        "vlamax_mmol_l_s": vlamax_mmol_l_s,
        "mlss_power_w": round(mlss_power_w, 1),
        "fatmax_power_w": fatmax_power_w,
        "map_power_w": round(map_power_w, 1),
        "apr_w": apr_w,
        "phenotype_type": phenotype_type,
        "phenotype_description": phenotype_description,
        "confidence_score": confidence["confidence_score"],
        "confidence_tier": confidence["confidence_tier"],
        "profile_status": profile_status,
        "warnings": warnings,
        "derivation": {
            "vo2max": "map_power_proxy",
            "vlamax": "apr_map_mlss_model",
            "mlss": "threshold_mmp_best_or_1200_penalty",
            "fatmax": "mlss_vlamax_heuristic",
        },
    }


def _tier_rank(tier: str) -> int:
    order = {CONFIDENCE_LOW: 0, CONFIDENCE_MODERATE: 1, CONFIDENCE_HIGH: 2, "low": 0, "medium": 1, "high": 2}
    return order.get(str(tier).upper(), 0)


def should_create_new_profile_version(
    latest_profile: Optional[Dict[str, Any]],
    new_profile: Dict[str, Any],
    changed_mmp_points: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Decide whether to persist a new immutable profile version."""
    if latest_profile is None:
        return True, "first_profile"

    if not changed_mmp_points:
        return False, "mmp_not_changed"

    def _delta_pct(new_val: float, old_val: float) -> float:
        if old_val <= 0:
            return 1.0
        return abs(new_val - old_val) / old_val

    checks = [
        ("map_changed", "map_power_w", 0.03, True),
        ("mlss_changed", "mlss_power_w", 0.03, True),
        ("apr_changed", "apr_w", 0.05, True),
        ("vlamax_changed", "vlamax_mmol_l_s", 0.05, False),
        ("fatmax_changed", "fatmax_power_w", 10.0, False),
    ]
    for reason, key, threshold, is_ratio in checks:
        old_val = float(latest_profile.get(key) or 0)
        new_val = float(new_profile.get(key) or 0)
        if old_val <= 0 or new_val <= 0:
            continue
        delta = _delta_pct(new_val, old_val) if is_ratio else abs(new_val - old_val)
        if delta >= threshold:
            return True, reason

    old_tier = latest_profile.get("confidence_tier")
    new_tier = new_profile.get("confidence_tier")
    if _tier_rank(str(new_tier)) > _tier_rank(str(old_tier)):
        return True, "confidence_improved"

    if str(new_tier) != str(old_tier):
        return True, "confidence_changed"

    return False, "changes_below_threshold"
