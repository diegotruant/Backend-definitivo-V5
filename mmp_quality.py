"""
MMP Quality Analysis & Cleaning
================================

Tools to assess and clean a Mean Maximal Power curve BEFORE passing it to
MetabolicProfiler. Inspired by WKO5's "Find Power Spikes & Bad Cycling Data"
dashboard, but automated rather than manual.

Categories of issues detected
-----------------------------
- **identical_plateau**  : adjacent durations with identical power (within ±0.5W).
    Physiologically impossible — almost always indicates that both anchors
    come from rolling-window extraction on the same source activity, not
    from independent maximal efforts.

- **rolling_window_redundant** : multiple anchors all sourced from a single
    activity, particularly in the long-duration range (>10min). When 5+
    consecutive anchors come from the same FIT, those anchors aren't
    independent observations — they're rolling averages of the same physiological
    event at different window widths. Keep one, downweight or drop the rest.

- **sprint_outlier** : a 5-15s anchor that produces a sprint/MLSS ratio above
    3.5. Usually indicates either a power meter calibration spike, a
    standing-start artifact, or a power meter that's actually on a different
    bike (e.g. e-bike, dirt bike) than the rest of the data.

- **flat_long_region** : 4+ consecutive long-duration anchors (>600s) with
    less than 1% decay between adjacent samples. Usually means the athlete
    has never done an all-out long effort and the modeled long-duration
    region is dominated by Z2/Z3 endurance riding.

- **non_monotonic** : a longer-duration anchor with power > a shorter-duration
    anchor. Physically impossible. Either a sub-max effort polluted a shorter
    anchor or there's an outlier spike. Detection only — not used as cleaning
    rule since usually upstream extraction already enforces monotonicity.

API
---
    analyze_mmp_quality(mmp, mmp_samples=None) -> MMPQualityReport
    clean_mmp(mmp, mmp_samples=None, drop_rules=None) -> tuple[cleaned_mmp, audit]

The default cleaning rules are conservative: drop plateau duplicates and
rolling-window redundants beyond the first anchor in a cluster. Sprint
outliers and flat regions are flagged but NOT dropped automatically.

Tier: HEURISTIC (the thresholds are evidence-informed but not validated
against a gold-standard MMP curve).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict


# Tunable thresholds. Documented so that consumers can override per-athlete
# or per-discipline if needed (e.g. trackies might legitimately have sprint
# ratios > 3.5).
PLATEAU_TOLERANCE_W = 0.5            # Δpower below this between adjacent → plateau
PLATEAU_MIN_DURATION_S = 60          # only flag plateaus for durations ≥ this
ROLLING_REDUNDANT_MIN_CLUSTER = 4    # this many+ consecutive anchors from same file = cluster
ROLLING_REDUNDANT_MIN_DURATION_S = 600  # only flag in long-duration region
SPRINT_RATIO_THRESHOLD = 3.5         # sprint5s / MLSS_proxy
FLAT_REGION_MIN_ANCHORS = 4
FLAT_REGION_MIN_DURATION_S = 600
FLAT_REGION_MAX_DECAY_PCT = 1.0      # decay below this between samples = flat


@dataclass
class MMPQualityIssue:
    """One detected issue in the MMP curve."""
    category: str                    # one of the categories listed above
    severity: str                    # "info" | "warn" | "error"
    durations: List[int]             # affected durations in seconds
    message: str                     # human-readable explanation
    suggested_action: str = ""       # what to do about it
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "durations": self.durations,
            "message": self.message,
            "suggested_action": self.suggested_action,
        }


@dataclass
class MMPQualityReport:
    """Output of analyze_mmp_quality()."""
    total_anchors: int = 0
    total_source_files: Optional[int] = None
    issues: List[MMPQualityIssue] = field(default_factory=list)
    quality_score: float = 1.0       # 0..1, 1 = pristine
    classification: str = "good"     # "good" | "fair" | "poor"
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_anchors": self.total_anchors,
            "total_source_files": self.total_source_files,
            "issues": [i.to_dict() for i in self.issues],
            "issue_counts_by_category": self._counts(),
            "quality_score": round(self.quality_score, 3),
            "classification": self.classification,
            "recommendations": self.recommendations,
            "tier": "HEURISTIC",
        }
    
    def _counts(self) -> Dict[str, int]:
        out: Dict[str, int] = defaultdict(int)
        for i in self.issues:
            out[i.category] += 1
        return dict(out)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _coerce_mmp(mmp: Dict[Any, float]) -> Dict[int, float]:
    """Normalize key types to int seconds, drop None/non-numeric."""
    out: Dict[int, float] = {}
    for k, v in mmp.items():
        if v is None:
            continue
        try:
            p = float(v)
            if p <= 0:
                continue
            ks = str(k).strip().lower()
            if ks.endswith("s"):
                sec = int(float(ks[:-1]))
            elif ks.endswith("m"):
                sec = int(float(ks[:-1]) * 60)
            else:
                sec = int(float(ks))
            out[sec] = p
        except (TypeError, ValueError):
            continue
    return dict(sorted(out.items()))


def _source_map(mmp_samples: Optional[List[Dict[str, Any]]]) -> Dict[int, str]:
    """
    For each duration, pick the source file of the winning (max-power) sample.
    Returns: {duration_s: filename}.
    Returns {} if mmp_samples is None or empty.
    """
    if not mmp_samples:
        return {}
    by_dur: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for s in mmp_samples:
        try:
            d = int(s.get("duration_s") or s.get("duration"))
            p = float(s.get("power_w") or s.get("power") or 0)
            fn = s.get("filename") or s.get("source_file") or s.get("file")
        except (TypeError, ValueError):
            continue
        if p <= 0 or not fn:
            continue
        by_dur[d].append({"power": p, "filename": fn})
    
    out = {}
    for d, candidates in by_dur.items():
        winner = max(candidates, key=lambda c: c["power"])
        out[d] = winner["filename"]
    return out


# -----------------------------------------------------------------------------
# Detection passes
# -----------------------------------------------------------------------------

def _detect_plateaus(mmp: Dict[int, float]) -> List[MMPQualityIssue]:
    """Adjacent durations with near-identical power."""
    out = []
    durations = sorted(mmp.keys())
    for i in range(1, len(durations)):
        d_prev, d_curr = durations[i-1], durations[i]
        if d_curr < PLATEAU_MIN_DURATION_S:
            continue
        if abs(mmp[d_curr] - mmp[d_prev]) <= PLATEAU_TOLERANCE_W:
            out.append(MMPQualityIssue(
                category="identical_plateau",
                severity="warn",
                durations=[d_prev, d_curr],
                message=(
                    f"Anchors at {d_prev}s and {d_curr}s have near-identical power "
                    f"({mmp[d_prev]:.1f}W vs {mmp[d_curr]:.1f}W). Physiologically "
                    f"power should decrease with duration. Usually means both come "
                    f"from rolling-window extraction on the same source activity."
                ),
                suggested_action=f"Keep {d_prev}s, drop {d_curr}s (or vice versa)",
            ))
    return out


def _detect_rolling_redundant(
    mmp: Dict[int, float], src_map: Dict[int, str]
) -> List[MMPQualityIssue]:
    """Clusters of consecutive long-duration anchors all from the same file."""
    if not src_map:
        return []
    durations = sorted([d for d in mmp.keys() if d >= ROLLING_REDUNDANT_MIN_DURATION_S])
    out = []
    
    i = 0
    while i < len(durations):
        # Walk forward while same source file
        same_src = [durations[i]]
        src_i = src_map.get(durations[i])
        if src_i is None:
            i += 1
            continue
        j = i + 1
        while j < len(durations) and src_map.get(durations[j]) == src_i:
            same_src.append(durations[j])
            j += 1
        
        if len(same_src) >= ROLLING_REDUNDANT_MIN_CLUSTER:
            out.append(MMPQualityIssue(
                category="rolling_window_redundant",
                severity="warn",
                durations=same_src,
                message=(
                    f"{len(same_src)} consecutive long-duration anchors "
                    f"({same_src[0]}s–{same_src[-1]}s) all come from the same "
                    f"source activity ({src_i}). These are rolling averages of "
                    f"the same physiological event, not independent maximal efforts."
                ),
                suggested_action=(
                    f"Keep only one representative anchor (e.g. the longest, "
                    f"{same_src[-1]}s) and drop the others to avoid biasing the fit."
                ),
            ))
        i = j
    return out


def _detect_sprint_outlier(mmp: Dict[int, float]) -> List[MMPQualityIssue]:
    """Sprint power dramatically higher than threshold power."""
    sprint_5 = mmp.get(5)
    # Use 1200s (20min) as MLSS proxy if available, else longest duration
    durations = sorted(mmp.keys())
    long_anchors = [d for d in durations if 1000 <= d <= 1800]
    proxy_dur = long_anchors[0] if long_anchors else (durations[-1] if durations else None)
    if proxy_dur is None or sprint_5 is None:
        return []
    proxy = mmp[proxy_dur]
    ratio = sprint_5 / proxy if proxy > 0 else 0
    if ratio > SPRINT_RATIO_THRESHOLD:
        return [MMPQualityIssue(
            category="sprint_outlier",
            severity="warn",
            durations=[5],
            message=(
                f"5s sprint power ({sprint_5:.0f}W) is {ratio:.1f}x the "
                f"{proxy_dur}s power ({proxy:.0f}W). Typical road/MTB ratios are "
                f"2.0-3.0; values above {SPRINT_RATIO_THRESHOLD} suggest either "
                f"a power meter calibration spike, a standing-start artifact, "
                f"or a sprint recorded on different equipment."
            ),
            suggested_action=(
                "Inspect the source FIT for the 5s anchor. Verify power meter "
                "calibration on that activity. Consider excluding if it looks "
                "anomalous."
            ),
        )]
    return []


def _detect_flat_long_region(mmp: Dict[int, float]) -> List[MMPQualityIssue]:
    """Sequences of long-duration anchors with negligible decay between them."""
    durations = sorted([d for d in mmp.keys() if d >= FLAT_REGION_MIN_DURATION_S])
    if len(durations) < FLAT_REGION_MIN_ANCHORS:
        return []
    
    flat_runs: List[List[int]] = []
    current_run: List[int] = []
    
    for i in range(1, len(durations)):
        d_prev, d_curr = durations[i-1], durations[i]
        p_prev, p_curr = mmp[d_prev], mmp[d_curr]
        if p_prev <= 0:
            continue
        decay_pct = (1 - p_curr / p_prev) * 100
        if decay_pct < FLAT_REGION_MAX_DECAY_PCT:
            if not current_run:
                current_run = [d_prev]
            current_run.append(d_curr)
        else:
            if len(current_run) >= FLAT_REGION_MIN_ANCHORS:
                flat_runs.append(current_run)
            current_run = []
    if len(current_run) >= FLAT_REGION_MIN_ANCHORS:
        flat_runs.append(current_run)
    
    out = []
    for run in flat_runs:
        out.append(MMPQualityIssue(
            category="flat_long_region",
            severity="info",
            durations=run,
            message=(
                f"{len(run)} consecutive long-duration anchors "
                f"({run[0]}s–{run[-1]}s) decay less than "
                f"{FLAT_REGION_MAX_DECAY_PCT}% between samples. This usually "
                f"means the athlete has never done an all-out long effort and "
                f"the modeled endurance region is dominated by sub-maximal rides."
            ),
            suggested_action=(
                "Schedule a 20-min and a 60-min all-out test (see onboarding "
                "protocol Session 3). The MLSS estimate is likely sub-stated "
                "until then."
            ),
        ))
    return out


def _detect_non_monotonic(mmp: Dict[int, float]) -> List[MMPQualityIssue]:
    """Power increases with duration — physically impossible."""
    durations = sorted(mmp.keys())
    out = []
    for i in range(1, len(durations)):
        d_prev, d_curr = durations[i-1], durations[i]
        if mmp[d_curr] > mmp[d_prev] + 0.5:
            out.append(MMPQualityIssue(
                category="non_monotonic",
                severity="error",
                durations=[d_prev, d_curr],
                message=(
                    f"Power at {d_curr}s ({mmp[d_curr]:.1f}W) is higher than at "
                    f"{d_prev}s ({mmp[d_prev]:.1f}W). MMP must be monotonically "
                    f"non-increasing. Likely an outlier spike or sub-max anchor."
                ),
                suggested_action=f"Inspect both anchors; one of them is wrong.",
            ))
    return out


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def analyze_mmp_quality(
    mmp: Dict[Any, float],
    mmp_samples: Optional[List[Dict[str, Any]]] = None,
) -> MMPQualityReport:
    """
    Analyze the quality of an MMP curve and produce a report.
    
    Parameters
    ----------
    mmp : dict
        {duration_s_or_str: power_w}. Same input format the profiler accepts.
    mmp_samples : list of dicts, optional
        Per-sample provenance: [{duration_s, power_w, filename, date}, ...].
        Enables detection of rolling-window redundancy across source files.
    
    Returns
    -------
    MMPQualityReport
    """
    clean_mmp_dict = _coerce_mmp(mmp)
    src_map = _source_map(mmp_samples)
    
    issues = []
    issues += _detect_non_monotonic(clean_mmp_dict)
    issues += _detect_plateaus(clean_mmp_dict)
    issues += _detect_rolling_redundant(clean_mmp_dict, src_map)
    issues += _detect_sprint_outlier(clean_mmp_dict)
    issues += _detect_flat_long_region(clean_mmp_dict)
    
    # Quality score: 1.0 - penalty per issue, capped at 0
    penalty = 0.0
    for issue in issues:
        penalty += {"error": 0.20, "warn": 0.10, "info": 0.03}.get(issue.severity, 0.05)
    quality_score = max(0.0, 1.0 - penalty)
    
    classification = (
        "good" if quality_score >= 0.75 else
        "fair" if quality_score >= 0.45 else
        "poor"
    )
    
    # Recommendations are derived from the issues
    recommendations: List[str] = []
    cats = {i.category for i in issues}
    if "rolling_window_redundant" in cats:
        recommendations.append(
            "Multiple anchors come from the same source activity. Consider "
            "limiting the MMP window to 60-90 days, or excluding redundant "
            "rolling-window anchors before fitting."
        )
    if "identical_plateau" in cats:
        recommendations.append(
            "Plateau artifacts detected. Run clean_mmp() before passing to "
            "MetabolicProfiler to drop duplicates."
        )
    if "sprint_outlier" in cats:
        recommendations.append(
            "Sprint anchor is anomalous. Inspect the source FIT for power meter "
            "calibration or equipment mismatch."
        )
    if "flat_long_region" in cats:
        recommendations.append(
            "Long-duration anchors look sub-maximal. Schedule a 20-min and a "
            "60-min all-out test to qualify the MLSS region."
        )
    if "non_monotonic" in cats:
        recommendations.append(
            "Non-monotonic anchors detected. This is a data integrity issue: "
            "MMP must always decrease with duration."
        )
    if not issues:
        recommendations.append(
            "MMP curve looks clean. Confidence will be driven mostly by coverage "
            "and number of anchors."
        )
    
    src_count = len(set(src_map.values())) if src_map else None
    
    return MMPQualityReport(
        total_anchors=len(clean_mmp_dict),
        total_source_files=src_count,
        issues=issues,
        quality_score=quality_score,
        classification=classification,
        recommendations=recommendations,
    )


def clean_mmp(
    mmp: Dict[Any, float],
    mmp_samples: Optional[List[Dict[str, Any]]] = None,
    drop_rules: Optional[List[str]] = None,
) -> Tuple[Dict[int, float], Dict[str, Any]]:
    """
    Return a cleaned MMP suitable for passing to MetabolicProfiler.
    
    Parameters
    ----------
    mmp : dict
        Input MMP. Keys can be int seconds or "5s"/"30m" strings.
    mmp_samples : list, optional
        Provenance info, enables rolling-window detection.
    drop_rules : list of str, optional
        Which categories of issue to drop. Default:
            ["identical_plateau", "rolling_window_redundant"]
        Sprint outliers and flat regions are FLAGGED in the audit but NOT
        dropped automatically — they require human judgment.
    
    Returns
    -------
    cleaned_mmp : dict[int, float]
        MMP with offending anchors removed.
    audit : dict
        {
            "original_anchors": int,
            "cleaned_anchors": int,
            "dropped": [{"duration_s": int, "reason": str, "category": str}, ...],
            "kept_warnings": [issue.to_dict() for non-dropped issues],
        }
    """
    if drop_rules is None:
        drop_rules = ["identical_plateau", "rolling_window_redundant"]
    
    clean = _coerce_mmp(mmp)
    src_map = _source_map(mmp_samples)
    report = analyze_mmp_quality(mmp, mmp_samples)
    
    dropped: List[Dict[str, Any]] = []
    kept_warnings: List[Dict[str, Any]] = []
    
    for issue in report.issues:
        if issue.category not in drop_rules:
            kept_warnings.append(issue.to_dict())
            continue
        
        if issue.category == "identical_plateau":
            # Drop the LONGER duration (keep the shorter, more informative one)
            # because in a plateau, the shorter is closer to the "true" peak
            # and the longer is the rolling-window extension.
            to_drop = max(issue.durations)
            if to_drop in clean:
                del clean[to_drop]
                dropped.append({
                    "duration_s": to_drop,
                    "reason": "Plateau with shorter-duration anchor",
                    "category": issue.category,
                })
        
        elif issue.category == "rolling_window_redundant":
            # Keep first and last of the cluster, drop the middle
            durs = sorted(issue.durations)
            if len(durs) <= 2:
                continue
            for d in durs[1:-1]:
                if d in clean:
                    del clean[d]
                    dropped.append({
                        "duration_s": d,
                        "reason": "Rolling-window redundant within source-activity cluster",
                        "category": issue.category,
                    })
    
    audit = {
        "original_anchors": report.total_anchors,
        "cleaned_anchors": len(clean),
        "dropped": dropped,
        "kept_warnings": kept_warnings,
        "quality_score_before": report.quality_score,
        "tier": "HEURISTIC",
    }
    
    return clean, audit


# =============================================================================
# Time-window filtering (WKO5-style "last 90 days")
# =============================================================================

def filter_mmp_by_window(
    mmp_samples: List[Dict[str, Any]],
    today: Optional[Any] = None,
    window_days: int = 90,
) -> Tuple[Dict[int, float], List[Dict[str, Any]]]:
    """
    Rebuild an MMP dict from samples, keeping only those within `window_days`
    of `today`.
    
    Replicates WKO5's "last 90 days" window for power-duration modeling.
    The motivation: an athlete's physiology changes over time. Anchors from
    6 months ago bias the fit toward an outdated state. Limiting to recent
    data gives a more representative snapshot of current fitness, at the
    cost of fewer anchors (and potentially lower confidence for athletes
    with sparse recent activity).
    
    Parameters
    ----------
    mmp_samples : list of dicts
        Each dict must have at least: duration_s, power_w, date.
        Date can be a date/datetime object or ISO string.
    today : date | datetime | str, optional
        Reference date for the window. Default: today.
    window_days : int
        Window size in days. Default 90 (matches WKO5). Use a larger
        value (180-365) for athletes with infrequent training.
    
    Returns
    -------
    mmp : dict[int, float]
        Rebuilt MMP from filtered samples (max power per duration).
    kept_samples : list
        The samples that survived the filter (useful for further analysis).
    
    Notes
    -----
    If no samples match the window (e.g. athlete inactive), returns an empty
    MMP. The caller should handle this case (e.g. fall back to all-time MMP
    with a warning).
    """
    from datetime import date, datetime, timedelta
    
    if today is None:
        today_d = date.today()
    elif isinstance(today, str):
        today_d = datetime.fromisoformat(today.split("T")[0]).date()
    elif isinstance(today, datetime):
        today_d = today.date()
    elif isinstance(today, date):
        today_d = today
    else:
        today_d = date.today()
    
    cutoff = today_d - timedelta(days=window_days)
    
    kept = []
    for s in mmp_samples or []:
        d_raw = s.get("date")
        if d_raw is None:
            continue
        try:
            if isinstance(d_raw, str):
                d = datetime.fromisoformat(d_raw.split("T")[0]).date()
            elif isinstance(d_raw, datetime):
                d = d_raw.date()
            elif isinstance(d_raw, date):
                d = d_raw
            else:
                continue
        except (ValueError, TypeError):
            continue
        
        if d >= cutoff:
            kept.append(s)
    
    # Rebuild MMP: max power per duration from kept samples
    mmp: Dict[int, float] = {}
    for s in kept:
        try:
            dur = int(s.get("duration_s") or s.get("duration"))
            pw = float(s.get("power_w") or s.get("power") or 0)
        except (TypeError, ValueError):
            continue
        if pw <= 0:
            continue
        if dur not in mmp or pw > mmp[dur]:
            mmp[dur] = pw
    
    return dict(sorted(mmp.items())), kept
