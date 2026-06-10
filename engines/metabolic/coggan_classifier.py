"""
Coggan Power Profile Classifier
Version: 1.0.0

Classifies a rider's W/kg at four canonical durations against the population
percentile tables published by Allen & Coggan ("Training and Racing with a
Power Meter", 3rd ed., Appendix B). The four anchors are:

  - 5-second peak power     (sprinting / neuromuscular system)
  - 1-minute power          (anaerobic capacity / W')
  - 5-minute power          (VO₂max proxy)
  - FTP / 60-min power      (lactate-threshold / aerobic threshold)

The relative shape of the four percentile placements reveals the rider
type: a sprinter sits high on 5s/1min and low on 5min/FTP; a TT
specialist is the mirror image. We classify into four phenotypes:

  - SPRINTER         (peak strength: 5s/1min >> 5min/FTP)
  - PURSUITER / GC   (peak strength: 5min, with FTP solid)  
  - TT / CLIMBER     (peak strength: FTP, sustained)
  - ALL-ROUNDER      (no axis dominates by > 1 tier)

NOTE: these tables are normative. They are NOT used in the metabolic /
cardiac engines for any computation — they exist purely for the coach-
facing classification visualization. The underlying Mader simulation in
metabolic_profiler.py is the physiological model of record.
"""

from typing import Any, Dict, List, Optional, Tuple

# =============================================================================
# COGGAN POWER PROFILING TABLES (Allen & Coggan 2010, Appendix B)
# =============================================================================
# Each entry: (label, w_per_kg_lower_bound)
# Walking from the bottom up; the rider's W/kg is matched against the
# highest tier whose lower bound it meets or exceeds.

_TIERS_ORDER = [
    "WORLD_CLASS",   # 8 — pro tour
    "EXCEPTIONAL",   # 7 — domestic pro / cat 1
    "EXCELLENT",     # 6 — strong cat 1/2
    "VERY_GOOD",     # 5 — cat 2
    "GOOD",          # 4 — cat 3
    "MODERATE",      # 3 — cat 4
    "FAIR",          # 2 — cat 5
    "UNTRAINED",     # 1 — recreational
]

# Male tables (W/kg lower bounds per tier). Source: Allen & Coggan 2010, p.50-52
_MALE_TABLES: Dict[str, Dict[str, float]] = {
    "5s": {
        "WORLD_CLASS": 24.04, "EXCEPTIONAL": 22.50, "EXCELLENT": 20.97,
        "VERY_GOOD":   19.43, "GOOD":         17.89, "MODERATE":  16.36,
        "FAIR":         14.82, "UNTRAINED":     0.00,
    },
    "1min": {
        "WORLD_CLASS": 11.50, "EXCEPTIONAL": 10.78, "EXCELLENT": 10.05,
        "VERY_GOOD":    9.32, "GOOD":          8.60, "MODERATE":   7.87,
        "FAIR":          7.15, "UNTRAINED":     0.00,
    },
    "5min": {
        "WORLD_CLASS": 7.60, "EXCEPTIONAL": 7.06, "EXCELLENT": 6.51,
        "VERY_GOOD":   5.97, "GOOD":         5.42, "MODERATE":   4.87,
        "FAIR":         4.33, "UNTRAINED":   0.00,
    },
    "ftp": {
        "WORLD_CLASS": 6.40, "EXCEPTIONAL": 5.94, "EXCELLENT": 5.49,
        "VERY_GOOD":   5.04, "GOOD":         4.59, "MODERATE":   4.14,
        "FAIR":         3.69, "UNTRAINED":   0.00,
    },
}

# Female tables (W/kg lower bounds per tier). Same source.
_FEMALE_TABLES: Dict[str, Dict[str, float]] = {
    "5s": {
        "WORLD_CLASS": 19.42, "EXCEPTIONAL": 18.16, "EXCELLENT": 16.90,
        "VERY_GOOD":   15.65, "GOOD":         14.39, "MODERATE":  13.13,
        "FAIR":         11.87, "UNTRAINED":     0.00,
    },
    "1min": {
        "WORLD_CLASS": 9.29, "EXCEPTIONAL": 8.71, "EXCELLENT": 8.13,
        "VERY_GOOD":   7.55, "GOOD":         6.97, "MODERATE":   6.39,
        "FAIR":         5.81, "UNTRAINED":   0.00,
    },
    "5min": {
        "WORLD_CLASS": 6.61, "EXCEPTIONAL": 6.13, "EXCELLENT": 5.66,
        "VERY_GOOD":   5.18, "GOOD":         4.71, "MODERATE":   4.23,
        "FAIR":         3.76, "UNTRAINED":   0.00,
    },
    "ftp": {
        "WORLD_CLASS": 5.69, "EXCEPTIONAL": 5.27, "EXCELLENT": 4.86,
        "VERY_GOOD":   4.45, "GOOD":         4.04, "MODERATE":   3.62,
        "FAIR":         3.21, "UNTRAINED":   0.00,
    },
}

# Tier descriptions for the report
_TIER_DESCRIPTIONS = {
    "WORLD_CLASS":  "World-class — top of professional cycling",
    "EXCEPTIONAL":  "Exceptional — domestic pro / cat 1",
    "EXCELLENT":    "Excellent — strong cat 1/2",
    "VERY_GOOD":    "Very good — competitive cat 2",
    "GOOD":         "Good — competitive cat 3",
    "MODERATE":     "Moderate — recreational racer",
    "FAIR":         "Fair — fit recreational",
    "UNTRAINED":    "Untrained — beginner",
}

# Numeric tier scores for shape analysis
_TIER_SCORES = {
    "WORLD_CLASS": 8, "EXCEPTIONAL": 7, "EXCELLENT": 6, "VERY_GOOD": 5,
    "GOOD": 4, "MODERATE": 3, "FAIR": 2, "UNTRAINED": 1,
}


# =============================================================================
# CLASSIFICATION FOR ONE DURATION
# =============================================================================

def classify_duration(wkg: float, duration_key: str, gender: str) -> Dict[str, Any]:
    """
    Classify one W/kg value at a given duration vs population tables.
    duration_key \u2208 {'5s', '1min', '5min', 'ftp'}
    gender \u2208 {'MALE', 'FEMALE'}
    """
    tables = _MALE_TABLES if gender.upper() == "MALE" else _FEMALE_TABLES
    if duration_key not in tables:
        raise ValueError(f"Unknown duration_key: {duration_key}")

    bounds = tables[duration_key]

    # Walk top-down: the highest tier whose lower bound is met
    matched_tier = "UNTRAINED"
    for tier in _TIERS_ORDER:
        if wkg >= bounds[tier]:
            matched_tier = tier
            break

    # Compute headroom to next tier (how close to the next tier above)
    next_tier = None
    headroom_wkg = None
    if matched_tier != "WORLD_CLASS":
        idx = _TIERS_ORDER.index(matched_tier)
        next_tier = _TIERS_ORDER[idx - 1]
        headroom_wkg = round(bounds[next_tier] - wkg, 2)

    return {
        "duration": duration_key,
        "wkg": round(wkg, 2),
        "tier": matched_tier,
        "tier_score": _TIER_SCORES[matched_tier],
        "tier_description": _TIER_DESCRIPTIONS[matched_tier],
        "next_tier": next_tier,
        "headroom_wkg_to_next_tier": headroom_wkg,
    }


# =============================================================================
# RIDER PHENOTYPE FROM PROFILE SHAPE
# =============================================================================

def _classify_phenotype(scores: Dict[str, int]) -> Tuple[str, str]:
    """
    From the 4 tier scores, derive a rider phenotype.
    Returns (phenotype_code, description).
    """
    s5 = scores.get("5s")
    s60 = scores.get("1min")
    s300 = scores.get("5min")
    sftp = scores.get("ftp")
    if any(v is None for v in (s5, s60, s300, sftp)):
        return "INCOMPLETE", "Insufficient data points to classify rider phenotype."

    # mypy can't narrow through any(); assert explicitly after the guard.
    assert s5 is not None and s60 is not None and s300 is not None and sftp is not None
    short = (s5 + s60) / 2.0
    long = (s300 + sftp) / 2.0
    delta = short - long

    # Thresholds for clear phenotype: > 1.5 tier difference
    if delta >= 1.5:
        return "SPRINTER", (
            "Sprinter / fast-twitch dominant. Peak strength in efforts <60s. "
            "Glycolytic + neuromuscular systems well developed."
        )
    if delta <= -1.5:
        return "TT_CLIMBER", (
            "Time-trialist / climber. Peak strength in sustained efforts. "
            "High aerobic ceiling vs anaerobic output."
        )

    # Less extreme: pursuit/GC if 5min is the high point, all-rounder otherwise
    if s300 > sftp and s300 >= s60:
        return "PURSUITER", (
            "Pursuiter / GC type. Strongest at VO₂max-range efforts (3–8 min). "
            "Suited to short climbs, breakaways, prologue TTs."
        )

    return "ALL_ROUNDER", (
        "All-rounder. No single duration dominates — balanced across the "
        "neuromuscular / anaerobic / VO₂max / threshold spectrum."
    )


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def classify_power_profile(
    weight_kg: float,
    gender: str,
    p5s: Optional[float] = None,
    p1min: Optional[float] = None,
    p5min: Optional[float] = None,
    ftp: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Classify a full power profile against Coggan tables.

    Inputs are ABSOLUTE watts. The function divides by weight internally.
    All four are optional but at least 2 are recommended for a meaningful
    phenotype. Missing durations are reported as "not_provided".

    Returns a dict with per-duration tiers and an overall phenotype.
    """
    if weight_kg <= 0:
        raise ValueError("weight_kg must be positive")
    gender_norm = gender.upper() if gender else "MALE"
    if gender_norm not in ("MALE", "FEMALE"):
        gender_norm = "MALE"

    inputs: Dict[str, Optional[float]] = {
        "5s": p5s, "1min": p1min, "5min": p5min, "ftp": ftp,
    }
    per_duration: Dict[str, Any] = {}
    scores: Dict[str, int] = {}

    for key, watts in inputs.items():
        if watts is None or watts <= 0:
            per_duration[key] = {"available": False, "reason": "NOT_PROVIDED"}
            continue
        wkg = watts / weight_kg
        cls = classify_duration(wkg, key, gender_norm)
        per_duration[key] = {"available": True, **cls}
        scores[key] = cls["tier_score"]

    if not scores:
        return {
            "status": "error",
            "message": "No power values provided",
        }

    phenotype_code, phenotype_descr = _classify_phenotype(scores)
    avg_score = round(sum(scores.values()) / len(scores), 1)

    return {
        "status": "success",
        "schema_version": "1.0.0",
        "gender": gender_norm,
        "weight_kg": weight_kg,
        "by_duration": per_duration,
        "overall": {
            "phenotype_code": phenotype_code,
            "phenotype_description": phenotype_descr,
            "average_tier_score": avg_score,
            "n_durations_used": len(scores),
        },
        "reference": "Allen & Coggan 2010, Training and Racing with a Power Meter (3rd ed.)",
    }


def classify_from_mmp(
    mmp_curve: List[Dict[str, Any]],
    weight_kg: float,
    gender: str,
    ftp: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Convenience wrapper: pulls 5s / 60s / 300s peaks from an MMP curve
    (as produced by power_engine.mean_maximal_power) and runs the
    classification.

    If ftp is None, will use 1200s (20-min × 0.95 = FTP estimate) if
    available, falling back to 3600s if no 20-min point exists.
    """
    by_d = {m["duration_s"]: m["power_w"] for m in mmp_curve}

    p5 = by_d.get(5)
    p60 = by_d.get(60)
    p300 = by_d.get(300)

    ftp_used = ftp
    if ftp_used is None:
        if 1200 in by_d:
            ftp_used = by_d[1200] * 0.95
        elif 3600 in by_d:
            ftp_used = by_d[3600]

    return classify_power_profile(
        weight_kg=weight_kg,
        gender=gender,
        p5s=p5, p1min=p60, p5min=p300, ftp=ftp_used,
    )
