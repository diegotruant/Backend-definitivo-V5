"""
Pedaling Balance Analysis
=========================

Per-session analysis of left/right power balance, focused on detecting
**unilateral fatigue in endurance** — which gauges whether a single-leg
strength intervention (single-leg squats, leg press unilateral, single-leg
pedaling drills) is warranted.

Strict data policy
------------------
Only **dual-side power meters** (true L/R measurement) produce meaningful
balance data. Single-side meters that *estimate* balance from one crank
arm produce dummy 50/50 numbers or extrapolations that should not be
analyzed:

  - `pedaling_balance_source == "dual"`:        full analysis
  - `pedaling_balance_source == "single_estimated"`: REFUSED
                                                    (return data_quality="refused_single_side")
  - `pedaling_balance_source == "unknown"`:    full analysis but flag as
                                                "source_uncertain"

Per the user's spec: when source is single-side, we either reject the
analysis entirely OR expose only the left-power figure as informational.
We choose **rejection by default**, with a flag so the consumer knows why.

Primary endpoints
-----------------
- **Intra-session drift**: balance shifts from first half to second half
  during long endurance efforts. The clinical question: does one leg
  start taking more of the load as the session progresses?
- **Power-zone breakdown**: balance at Z1-Z2 vs Z3+ to check if asymmetry
  worsens with intensity.
- **Symmetry classification**: stable / mild / moderate / marked.

Trend analysis across sessions is provided separately by
analyze_balance_trend().

Tier: REFERENCE — this is signal processing on a measured channel with
established interpretation thresholds (no physiological model required).
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple
from datetime import date


# =============================================================================
# Thresholds (documented, override-able)
# =============================================================================

# Minimum power (W) for a sample to count: below this, balance reading is noisy
MIN_POWER_FOR_BALANCE_W = 100.0

# Minimum total valid samples to attempt analysis
MIN_VALID_SAMPLES = 60   # ≥1 minute of valid data

# Asymmetry classification thresholds (% deviation from 50/50)
# E.g. 48/52 = 4% deviation
ASYMMETRY_SYMMETRIC_MAX = 4.0    # 48-52
ASYMMETRY_MILD_MAX      = 10.0   # 45-55
ASYMMETRY_MODERATE_MAX  = 20.0   # 40-60
# Above 20% = "marked"

# Intra-session drift thresholds (% absolute change between halves)
DRIFT_STABLE_MAX     = 1.5
DRIFT_DRIFTING_MAX   = 3.0
# Above 3% = "strong_drift"

# Intensity bucket thresholds (relative to FTP)
ZONE_LOW_MAX  = 0.75   # Z1-Z2
ZONE_MID_MAX  = 1.05   # Z3-Z4
# Above 1.05 * FTP = Z5+


# =============================================================================
# Output types
# =============================================================================

@dataclass
class PedalingBalanceReport:
    """Per-session analysis."""
    # Data quality / acceptance
    data_quality: str               # "good" | "limited" | "refused_single_side" | "insufficient_data"
    pedaling_balance_source: str    # echoed from stream
    n_total_samples: int
    n_valid_samples: int            # samples above MIN_POWER_FOR_BALANCE_W with non-NaN balance
    
    # Overall statistics (only when data_quality != refused/insufficient)
    avg_left_pct: Optional[float] = None
    avg_right_pct: Optional[float] = None
    asymmetry_pct: Optional[float] = None             # absolute deviation from 50/50
    dominant_leg: Optional[str] = None                # "left" | "right" | "symmetric"
    asymmetry_classification: Optional[str] = None    # "symmetric" | "mild" | "moderate" | "marked"
    
    # Intra-session drift
    first_half_left_pct: Optional[float] = None
    second_half_left_pct: Optional[float] = None
    intra_session_drift: Optional[float] = None       # signed: positive = left took MORE load over time
    drift_classification: Optional[str] = None        # "stable" | "drifting" | "strong_drift"
    drift_direction: Optional[str] = None             # "leftward" | "rightward" | "stable"
    
    # Balance by power zone
    balance_by_zone: Optional[Dict[str, float]] = None  # {"z1_z2": 49.0, "z3_z4": 48.5, "z5_plus": 47.2}
    zone_shift_flag: Optional[str] = None              # "stable" | "shifts_with_load"
    
    # Clinical hint
    clinical_recommendation: Optional[str] = None
    
    notes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["tier"] = "REFERENCE"
        return d


# =============================================================================
# Public API
# =============================================================================

def analyze_pedaling_balance(
    balance_stream: List[Optional[float]],
    power_stream: List[float],
    ftp: Optional[float] = None,
    pedaling_balance_source: str = "unknown",
    accept_unknown_source: bool = True,
) -> PedalingBalanceReport:
    """
    Analyze L/R balance for one session.
    
    Parameters
    ----------
    balance_stream : list
        Per-sample LEFT-side percentage (0-100). NaN or None for missing.
    power_stream : list of float
        Per-sample power in watts. Used to gate low-power noise and to
        bucket by intensity.
    ftp : float, optional
        Functional Threshold Power. Required for zone-based breakdown.
    pedaling_balance_source : str
        One of: "dual" | "single_estimated" | "unknown".
        - "dual"             → full analysis
        - "single_estimated" → REFUSED (data_quality="refused_single_side")
        - "unknown"          → analyzed if accept_unknown_source=True (default)
    accept_unknown_source : bool
        If False, "unknown" source also gets refused. Useful for strict
        production deployments.
    
    Returns
    -------
    PedalingBalanceReport
    """
    n_total = len(power_stream)
    
    # ---- Source gating ----
    if pedaling_balance_source == "single_estimated":
        return PedalingBalanceReport(
            data_quality="refused_single_side",
            pedaling_balance_source=pedaling_balance_source,
            n_total_samples=n_total,
            n_valid_samples=0,
            notes=[
                "Single-side power meter detected. The L/R balance from "
                "such sensors is estimated, not measured, and is not used "
                "for asymmetry analysis."
            ],
        )
    
    if pedaling_balance_source == "unknown" and not accept_unknown_source:
        return PedalingBalanceReport(
            data_quality="refused_single_side",
            pedaling_balance_source=pedaling_balance_source,
            n_total_samples=n_total,
            n_valid_samples=0,
            notes=[
                "Power meter type could not be confirmed as dual-side. "
                "Set accept_unknown_source=True to analyze anyway."
            ],
        )
    
    # ---- Build valid-sample list ----
    valid: List[Tuple[int, float, float]] = []   # (index, balance_left_pct, power_w)
    for i in range(n_total):
        if i >= len(balance_stream):
            break
        b = balance_stream[i]
        p = power_stream[i]
        if b is None:
            continue
        # NaN check (works for float NaN)
        if isinstance(b, float) and b != b:
            continue
        if p is None or p < MIN_POWER_FOR_BALANCE_W:
            continue
        if not (0 <= b <= 100):
            continue
        valid.append((i, float(b), float(p)))
    
    n_valid = len(valid)
    
    if n_valid < MIN_VALID_SAMPLES:
        return PedalingBalanceReport(
            data_quality="insufficient_data",
            pedaling_balance_source=pedaling_balance_source,
            n_total_samples=n_total,
            n_valid_samples=n_valid,
            notes=[
                f"Only {n_valid} samples with valid balance + power >= "
                f"{MIN_POWER_FOR_BALANCE_W}W. Need at least {MIN_VALID_SAMPLES} "
                "for meaningful analysis."
            ],
        )
    
    # ---- Overall stats: power-weighted average ----
    total_power = sum(p for _, _, p in valid)
    weighted_left = sum(b * p for _, b, p in valid) / total_power
    weighted_right = 100.0 - weighted_left
    asym = abs(weighted_left - 50.0) * 2.0    # double so 48 vs 52 = 4%, not 2%
    
    dominant = ("symmetric" if asym < ASYMMETRY_SYMMETRIC_MAX
                else "left" if weighted_left > 50.0
                else "right")
    
    if asym < ASYMMETRY_SYMMETRIC_MAX:
        classification = "symmetric"
    elif asym < ASYMMETRY_MILD_MAX:
        classification = "mild"
    elif asym < ASYMMETRY_MODERATE_MAX:
        classification = "moderate"
    else:
        classification = "marked"
    
    # ---- Intra-session drift ----
    # Compare first half vs second half (by sample index, not by time)
    midpoint = valid[n_valid // 2][0]   # index in the stream at which to split
    first_half = [(b, p) for i, b, p in valid if i < midpoint]
    second_half = [(b, p) for i, b, p in valid if i >= midpoint]
    
    drift_class = None
    drift_direction = None
    first_left = second_left = drift = None
    
    if first_half and second_half:
        first_total_p = sum(p for _, p in first_half)
        second_total_p = sum(p for _, p in second_half)
        if first_total_p > 0 and second_total_p > 0:
            first_left = sum(b * p for b, p in first_half) / first_total_p
            second_left = sum(b * p for b, p in second_half) / second_total_p
            drift = second_left - first_left   # signed
            
            abs_drift = abs(drift)
            if abs_drift < DRIFT_STABLE_MAX:
                drift_class = "stable"
                drift_direction = "stable"
            elif abs_drift < DRIFT_DRIFTING_MAX:
                drift_class = "drifting"
                drift_direction = "leftward" if drift > 0 else "rightward"
            else:
                drift_class = "strong_drift"
                drift_direction = "leftward" if drift > 0 else "rightward"
    
    # ---- Balance by power zone ----
    balance_by_zone: Optional[Dict[str, float]] = None
    zone_shift = None
    if ftp:
        z1_z2 = [(b, p) for _, b, p in valid if p < ZONE_LOW_MAX * ftp]
        z3_z4 = [(b, p) for _, b, p in valid if ZONE_LOW_MAX * ftp <= p < ZONE_MID_MAX * ftp]
        z5_plus = [(b, p) for _, b, p in valid if p >= ZONE_MID_MAX * ftp]
        
        def _w_avg(samples):
            if not samples:
                return None
            tp = sum(p for _, p in samples)
            if tp <= 0:
                return None
            return sum(b * p for b, p in samples) / tp
        
        z1_z2_avg = _w_avg(z1_z2)
        z3_z4_avg = _w_avg(z3_z4)
        z5_plus_avg = _w_avg(z5_plus)
        
        balance_by_zone = {}
        if z1_z2_avg is not None:
            balance_by_zone["z1_z2"] = round(z1_z2_avg, 1)
        if z3_z4_avg is not None:
            balance_by_zone["z3_z4"] = round(z3_z4_avg, 1)
        if z5_plus_avg is not None:
            balance_by_zone["z5_plus"] = round(z5_plus_avg, 1)
        
        # Check if balance shifts with load — compare lowest and highest available zone
        zones_avail = [(k, v) for k, v in balance_by_zone.items() if v is not None]
        if len(zones_avail) >= 2:
            spread = max(v for _, v in zones_avail) - min(v for _, v in zones_avail)
            zone_shift = "shifts_with_load" if spread >= 2.0 else "stable"
    
    # ---- Clinical recommendation ----
    rec = None
    if classification == "marked" or drift_class == "strong_drift":
        rec = (
            f"Asymmetry is {classification}"
            f"{' with strong intra-session drift' if drift_class == 'strong_drift' else ''}. "
            "Consider screening for hip/glute imbalances and adding unilateral "
            "strength work (single-leg squats, single-leg leg press, single-leg "
            "pedaling drills 4-6 weeks)."
        )
    elif drift_class == "drifting" and drift is not None:
        # Drift alone is clinically meaningful — even from a symmetric baseline
        # if a leg consistently takes more load as the session progresses,
        # that's unilateral fatigue worth flagging.
        leg_taking_load = "left" if drift > 0 else "right"
        weaker_leg = "right" if drift > 0 else "left"
        rec = (
            f"During the session, the {leg_taking_load} leg progressively "
            f"took more of the load (drift {drift:+.1f}%). This is the signature "
            f"of unilateral fatigue: the {weaker_leg} leg appears to tire first. "
            f"If this pattern repeats across endurance sessions, unilateral "
            f"strength work targeting the {weaker_leg} side is worth considering."
        )
    elif classification == "moderate":
        rec = (
            f"Moderate asymmetry detected (~{asym:.0f}%) without significant drift. "
            "Worth flagging but not immediately actionable unless trend confirms."
        )
    
    notes = []
    if pedaling_balance_source == "unknown":
        notes.append(
            "Power meter type unconfirmed; treating as dual-side. Verify the "
            "device is actually a dual-side meter before acting on these results."
        )
    
    return PedalingBalanceReport(
        data_quality="good" if pedaling_balance_source == "dual" else "limited",
        pedaling_balance_source=pedaling_balance_source,
        n_total_samples=n_total,
        n_valid_samples=n_valid,
        avg_left_pct=round(weighted_left, 1),
        avg_right_pct=round(weighted_right, 1),
        asymmetry_pct=round(asym, 1),
        dominant_leg=dominant,
        asymmetry_classification=classification,
        first_half_left_pct=round(first_left, 1) if first_left is not None else None,
        second_half_left_pct=round(second_left, 1) if second_left is not None else None,
        intra_session_drift=round(drift, 2) if drift is not None else None,
        drift_classification=drift_class,
        drift_direction=drift_direction,
        balance_by_zone=balance_by_zone,
        zone_shift_flag=zone_shift,
        clinical_recommendation=rec,
        notes=notes,
    )


# =============================================================================
# Longitudinal trend analysis (across multiple sessions)
# =============================================================================

@dataclass
class BalanceTrend:
    """Multi-session trend in pedaling balance."""
    n_sessions: int
    n_endurance_sessions: int        # only endurance contributes meaningfully
    
    baseline_asymmetry_pct: Optional[float] = None     # avg of first 1/3 of window
    current_asymmetry_pct: Optional[float] = None      # avg of last 1/3
    trend: Optional[str] = None                        # "improving" | "worsening" | "stable"
    trend_delta_pct: Optional[float] = None            # signed change baseline → current
    
    avg_drift_per_session: Optional[float] = None      # avg of intra_session_drift
    consistent_drift_direction: Optional[str] = None   # if drift always favors same leg
    
    sessions_with_drift_above_threshold: int = 0
    
    summary: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["tier"] = "REFERENCE"
        return d


def analyze_balance_trend(
    session_reports: List[PedalingBalanceReport],
    dates: Optional[List[date]] = None,
    endurance_only: bool = True,
) -> BalanceTrend:
    """
    Analyze the trend across multiple session reports.
    
    Parameters
    ----------
    session_reports : list
        Output of analyze_pedaling_balance() for each session, ordered
        chronologically.
    dates : list of date, optional
        Dates for each report. Used only for context; not required.
    endurance_only : bool
        If True, drift analysis is meaningful only on sessions that
        spent most of their time in Z1-Z3. We approximate this by
        accepting sessions where balance_by_zone reports z1_z2 data.
    
    Returns
    -------
    BalanceTrend
    """
    n_total = len(session_reports)
    
    # Filter for usable sessions
    usable = [
        r for r in session_reports
        if r.data_quality in ("good", "limited") and r.asymmetry_pct is not None
    ]
    
    if endurance_only:
        usable = [
            r for r in usable
            if r.balance_by_zone is not None and "z1_z2" in r.balance_by_zone
        ]
    
    n_usable = len(usable)
    
    if n_usable < 3:
        return BalanceTrend(
            n_sessions=n_total,
            n_endurance_sessions=n_usable,
            notes=[
                f"Only {n_usable} usable session(s). Need at least 3 to detect a trend."
            ],
        )
    
    # Split into baseline (first 1/3) and current (last 1/3)
    third = max(1, n_usable // 3)
    baseline_sessions = usable[:third]
    current_sessions = usable[-third:]
    
    baseline_asym = sum(r.asymmetry_pct for r in baseline_sessions if r.asymmetry_pct is not None) / len(baseline_sessions)
    current_asym = sum(r.asymmetry_pct for r in current_sessions if r.asymmetry_pct is not None) / len(current_sessions)
    delta = current_asym - baseline_asym
    
    if abs(delta) < 1.0:
        trend = "stable"
    elif delta > 0:
        trend = "worsening"
    else:
        trend = "improving"
    
    # Drift analysis
    drifts = [r.intra_session_drift for r in usable if r.intra_session_drift is not None]
    avg_drift = sum(drifts) / len(drifts) if drifts else None
    
    above_threshold = sum(
        1 for r in usable
        if r.drift_classification in ("drifting", "strong_drift")
    )
    
    # Consistent drift direction
    consistent_dir = None
    if drifts:
        n_left_drift = sum(1 for d in drifts if d > 1.0)
        n_right_drift = sum(1 for d in drifts if d < -1.0)
        total_directional = n_left_drift + n_right_drift
        if total_directional >= max(3, len(drifts) // 2):
            if n_left_drift > 2 * n_right_drift:
                consistent_dir = "leftward"
            elif n_right_drift > 2 * n_left_drift:
                consistent_dir = "rightward"
    
    # Summary
    parts = []
    if trend == "worsening":
        parts.append(f"Asymmetry has increased by {delta:+.1f}% over the window.")
    elif trend == "improving":
        parts.append(f"Asymmetry has decreased by {abs(delta):.1f}% over the window.")
    else:
        parts.append("Asymmetry has remained stable across the window.")
    
    if consistent_dir:
        weaker = "right" if consistent_dir == "leftward" else "left"
        parts.append(
            f"In {above_threshold}/{n_usable} sessions the {consistent_dir} leg "
            f"took more load as fatigue accumulated, suggesting weakness in the "
            f"{weaker} leg."
        )
    
    if above_threshold >= n_usable // 2 and consistent_dir:
        parts.append("Unilateral strength intervention is worth considering.")
    
    summary = " ".join(parts)
    
    return BalanceTrend(
        n_sessions=n_total,
        n_endurance_sessions=n_usable,
        baseline_asymmetry_pct=round(baseline_asym, 1),
        current_asymmetry_pct=round(current_asym, 1),
        trend=trend,
        trend_delta_pct=round(delta, 1),
        avg_drift_per_session=round(avg_drift, 2) if avg_drift is not None else None,
        consistent_drift_direction=consistent_dir,
        sessions_with_drift_above_threshold=above_threshold,
        summary=summary,
    )
