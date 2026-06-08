"""
Efforts Analyzer — Breakdown table of peak efforts per duration
Version: 1.0.0

Takes the MMP curve (mean maximal power per duration) and produces a
structured breakdown table showing, for each canonical duration:
  - Absolute power and W/kg
  - % of FTP, CP, MLSS, MAP (when available)
  - Classification (Sprint / Anaerobic / VO2max / Threshold / Endurance)
  - W' consumed (if CP+W' model available)

This is the "efforts table" coaches review to understand an athlete's
current capabilities across the power-duration spectrum.

Reference durations: 5s, 15s, 30s, 1min, 3min, 5min, 10min, 20min, 60min.
"""

from typing import Any, Dict, List, Optional

# Canonical effort durations (seconds)
_EFFORT_DURATIONS = [5, 15, 30, 60, 180, 300, 600, 1200, 3600]

# Classification thresholds (expressed as % of reference anchors)
# These are approximate guides; the actual classification is multi-anchor.
_CLASSIFICATION_RULES = [
    # (label, logic callable)
    ("Sprint",           lambda r: r.get("pct_map", 0) > 150),
    ("Anaerobic",        lambda r: 120 < r.get("pct_map", 0) <= 150),
    ("VO2max",           lambda r: 105 < r.get("pct_mlss", 0) <= 120),
    ("Threshold",        lambda r: 95 <= r.get("pct_mlss", 0) <= 105),
    ("Sub-Threshold",    lambda r: 80 <= r.get("pct_mlss", 0) < 95),
    ("Endurance",        lambda r: r.get("pct_mlss", 0) < 80),
]


def _classify_effort(refs: Dict[str, float]) -> str:
    """Apply classification rules in order. First match wins."""
    for label, rule in _CLASSIFICATION_RULES:
        if rule(refs):
            return label
    return "Unclassified"


def _w_prime_consumed(
    duration_s: int,
    power_w: float,
    cp_w: float,
    wprime_j: float,
) -> Optional[float]:
    """
    Estimate W' consumed for a sustained effort at power_w for duration_s.
    Uses the simple integral: W'_used = (P - CP) * duration.
    """
    if power_w <= cp_w:
        return 0.0
    consumed_j = (power_w - cp_w) * duration_s
    if consumed_j > wprime_j:
        # Effort exceeds available W' — not sustainable
        return None
    return consumed_j


def analyze_efforts(
    mmp_curve: List[Dict[str, Any]],
    weight_kg: float,
    ftp: Optional[float] = None,
    cp_fit: Optional[Dict[str, Any]] = None,
    metabolic_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Produce the efforts breakdown table.

    Parameters
    ----------
    mmp_curve : list of {duration_s, power_w, wkg, ...}
        From power_engine.mean_maximal_power()
    weight_kg : float
    ftp : Optional[float]
        Functional Threshold Power for % reference
    cp_fit : Optional[dict]
        From power_engine.fit_critical_power() with cp_w and wprime_kj
    metabolic_snapshot : Optional[dict]
        From metabolic_profiler.generate_metabolic_snapshot()
        Contains mlss_power_watts, map_aerobic_watts, fatmax_power_watts

    Returns
    -------
    dict with:
      - efforts: list of dicts, one per duration
      - anchors: FTP / CP / MLSS / MAP used for % calculation
      - summary: quick stats (best sprint, best 5min, etc)
    """
    by_duration = {m["duration_s"]: m for m in mmp_curve}

    # Extract anchors. Use explicit `is not None` checks so that legitimate
    # zero or negative-edge values (e.g. wprime_kj = 0 from a degenerate CP fit)
    # are not silently turned into None and lost downstream.
    mlss_w = metabolic_snapshot.get("mlss_power_watts") if metabolic_snapshot else None
    map_w = metabolic_snapshot.get("map_aerobic_watts") if metabolic_snapshot else None
    fatmax_w = metabolic_snapshot.get("fatmax_power_watts") if metabolic_snapshot else None
    cp_w = cp_fit.get("cp_w") if cp_fit else None
    _wprime_kj = cp_fit.get("wprime_kj") if cp_fit else None
    wprime_j = (_wprime_kj * 1000.0) if _wprime_kj is not None else None

    efforts: List[Dict[str, Any]] = []
    for dur in _EFFORT_DURATIONS:
        if dur not in by_duration:
            continue
        m = by_duration[dur]
        power = m["power_w"]
        wkg = m["wkg"]

        refs: Dict[str, float] = {}
        if ftp and ftp > 0:
            refs["pct_ftp"] = round(power / ftp * 100.0, 1)
        if cp_w and cp_w > 0:
            refs["pct_cp"] = round(power / cp_w * 100.0, 1)
        if mlss_w and mlss_w > 0:
            refs["pct_mlss"] = round(power / mlss_w * 100.0, 1)
        if map_w and map_w > 0:
            refs["pct_map"] = round(power / map_w * 100.0, 1)

        classification = _classify_effort(refs)

        # W' consumed
        w_consumed_j = None
        w_consumed_pct = None
        if cp_w and wprime_j and dur >= 120:
            w_consumed_j = _w_prime_consumed(dur, power, cp_w, wprime_j)
            if w_consumed_j is not None:
                w_consumed_pct = round(w_consumed_j / wprime_j * 100.0, 1)

        efforts.append({
            "duration_s": dur,
            "duration_label": _format_duration(dur),
            "power_w": round(power, 1),
            "wkg": round(wkg, 2),
            **refs,
            "classification": classification,
            "w_prime_consumed_j": round(w_consumed_j, 0) if w_consumed_j is not None else None,
            "w_prime_consumed_pct": w_consumed_pct,
        })

    # Summary stats
    summary = {}
    if 5 in by_duration:
        summary["best_sprint_5s"] = {"power": by_duration[5]["power_w"], "wkg": by_duration[5]["wkg"]}
    if 60 in by_duration:
        summary["best_1min"] = {"power": by_duration[60]["power_w"], "wkg": by_duration[60]["wkg"]}
    if 300 in by_duration:
        summary["best_5min"] = {"power": by_duration[300]["power_w"], "wkg": by_duration[300]["wkg"]}
    if 1200 in by_duration:
        summary["best_20min"] = {"power": by_duration[1200]["power_w"], "wkg": by_duration[1200]["wkg"]}
    if 3600 in by_duration:
        summary["best_60min"] = {"power": by_duration[3600]["power_w"], "wkg": by_duration[3600]["wkg"]}

    return {
        "status": "success",
        "schema_version": "1.0.0",
        "efforts": efforts,
        "anchors": {
            "ftp_w": ftp,
            "cp_w": cp_w,
            "mlss_w": mlss_w,
            "map_w": map_w,
            "fatmax_w": fatmax_w,
        },
        "summary": summary,
    }


def _format_duration(s: int) -> str:
    """Convert seconds to human-readable string (e.g. 300 \u2192 '5min')."""
    if s < 60:
        return f"{s}s"
    m = s // 60
    if m < 60:
        return f"{m}min"
    h = m // 60
    rem_m = m % 60
    if rem_m == 0:
        return f"{h}h"
    return f"{h}h{rem_m}m"
