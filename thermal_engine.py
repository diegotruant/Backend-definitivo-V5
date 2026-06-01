"""
Thermal Engine — Core Body Temperature Analysis
=================================================

Analyzes core body temperature data from a body-temperature sensor to:
1. Separate cardiac drift into thermal vs fatigue components
2. Calculate heat tolerance threshold (°C at which power drops)
3. Measure thermoregulation efficiency (°C rise per kJ of work)
4. Produce a thermal-adjusted durability metric
5. Track heat acclimation over time (longitudinal)

Requires compatible body-temperature data paired to the activity stream.
When no body-temperature data is available, returns a graceful "no_data" status.

Physiological basis
-------------------
- Critical core temperature ~40°C: all subjects fatigue at the same
  core temp regardless of starting point (González-Alonso et al. 1999)
- Heat acclimation lowers sweat threshold by ~0.1°C per +12-17% VO2max
  improvement (Lorenzo 2010, Periard 2021)
- Cardiac drift has two components: thermal (vasodilatation for cooling)
  and fatigue (stroke volume decline from depletion/dehydration)
- Endurance training increases plasma volume → better thermoregulation
  → lower HR at same core temp

Tier: REFERENCE for signal processing, MODEL for thermal-adjusted metrics.

Dependencies: numpy only.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from datetime import date


# =============================================================================
# Thresholds
# =============================================================================

# Core temp zones (°C)
BODY_TEMP_RESTING = 37.0
BODY_TEMP_WARM = 38.0
BODY_TEMP_HOT = 38.5
BODY_TEMP_CAUTION = 39.0
BODY_TEMP_DANGER = 39.5
BODY_TEMP_CRITICAL = 40.0

# Minimum valid samples for analysis
MIN_VALID_SAMPLES = 300   # ≥5 min of data
MIN_POWER_THRESHOLD = 50  # W — below this, thermal data is noise (coasting)


# =============================================================================
# Output types
# =============================================================================

@dataclass
class ThermalSessionReport:
    """Per-session thermal analysis."""
    
    # Data availability
    data_quality: str           # "good" | "partial" | "no_data"
    n_valid_samples: int
    n_total_samples: int
    
    # Core temperature statistics
    core_temp_start: Optional[float] = None      # °C at minute 5 (after warmup)
    core_temp_end: Optional[float] = None         # °C at last 5 min
    core_temp_peak: Optional[float] = None        # max °C
    core_temp_mean: Optional[float] = None        # mean during active riding
    core_temp_at_peak_power: Optional[float] = None  # °C when max sustained power occurred
    
    # Skin temperature (if available)
    skin_temp_mean: Optional[float] = None
    core_skin_gradient: Optional[float] = None    # core - skin mean
    
    # Ambient temperature
    ambient_temp_mean: Optional[float] = None
    
    # Thermal rise rate
    thermal_rise_rate: Optional[float] = None     # °C/min during active riding
    thermal_rise_per_kj: Optional[float] = None   # °C per kJ of work produced
    
    # Heat tolerance
    heat_tolerance_threshold: Optional[float] = None   # °C where power starts dropping
    heat_tolerance_classification: Optional[str] = None  # "excellent" | "good" | "fair" | "poor"
    
    # Cardiac drift decomposition
    cardiac_drift_total_bpm: Optional[float] = None     # HR change first→second half
    cardiac_drift_thermal_bpm: Optional[float] = None   # component from temperature rise
    cardiac_drift_fatigue_bpm: Optional[float] = None    # residual (true fatigue)
    thermal_drift_pct: Optional[float] = None            # % of total drift explained by temp
    
    # Thermal-adjusted durability
    power_decay_raw_pct: Optional[float] = None          # raw power decline first→second half
    power_decay_thermal_adjusted_pct: Optional[float] = None  # after removing thermal effect
    
    # Efficiency correction
    eta_correction_factor: Optional[float] = None  # multiplier for mechanical efficiency
    
    # Thermal zones time
    time_in_zone_s: Optional[Dict[str, int]] = None  # {resting, warm, hot, caution, danger}
    
    # Clinical/coaching notes
    notes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = {}
        for k, v in self.__dict__.items():
            if k == "notes":
                d[k] = v
            elif v is not None:
                if isinstance(v, float):
                    d[k] = round(v, 2)
                else:
                    d[k] = v
        d["tier"] = "MODEL"
        return d


@dataclass
class HeatAcclimationTrend:
    """Longitudinal heat acclimation tracking."""
    n_sessions: int
    baseline_rise_rate: Optional[float] = None     # °C/min early sessions
    current_rise_rate: Optional[float] = None       # °C/min recent sessions
    trend: Optional[str] = None                     # "acclimating" | "stable" | "deacclimating"
    delta_rise_rate: Optional[float] = None
    baseline_tolerance: Optional[float] = None      # °C threshold early
    current_tolerance: Optional[float] = None       # °C threshold recent
    summary: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = {}
        for k, v in self.__dict__.items():
            if v is not None:
                if isinstance(v, float):
                    d[k] = round(v, 3)
                else:
                    d[k] = v
        d["tier"] = "MODEL"
        return d


# =============================================================================
# Core analysis functions
# =============================================================================

def _steady_state_mean(arr: np.ndarray, skip_pct: float = 0.08) -> float:
    """Mean of array after skipping initial ramp-up."""
    n = len(arr)
    start = int(n * skip_pct)
    end = max(start + 1, int(n * 0.95))
    return float(np.nanmean(arr[start:end]))


def _half_means(arr: np.ndarray) -> Tuple[float, float]:
    """Mean of first and second halves."""
    mid = len(arr) // 2
    return float(np.nanmean(arr[:mid])), float(np.nanmean(arr[mid:]))


def _detect_power_drop_temp(
    core_temp: np.ndarray,
    power: np.ndarray,
    window_s: int = 300,
) -> Optional[float]:
    """
    Find the core temperature at which sustained power starts declining.
    
    Method: sliding window average of power. Find where the slope
    of power vs core_temp turns significantly negative.
    """
    n = len(core_temp)
    if n < window_s * 3:
        return None
    
    # Smooth both signals
    n_windows = n // window_s
    if n_windows < 3:
        return None
    
    temp_buckets = []
    power_buckets = []
    for i in range(n_windows):
        seg_temp = core_temp[i*window_s:(i+1)*window_s]
        seg_power = power[i*window_s:(i+1)*window_s]
        
        valid = ~np.isnan(seg_temp) & (seg_power > MIN_POWER_THRESHOLD)
        if valid.sum() < window_s * 0.5:
            continue
        temp_buckets.append(float(np.nanmean(seg_temp[valid])))
        power_buckets.append(float(np.mean(seg_power[valid])))
    
    if len(temp_buckets) < 3:
        return None
    
    # Find where power starts declining while temp continues rising
    max_power_idx = np.argmax(power_buckets)
    if max_power_idx < len(temp_buckets) - 1:
        return temp_buckets[max_power_idx]
    
    return None


# =============================================================================
# Public API
# =============================================================================

def analyze_thermal_session(
    core_temp_stream: List[Optional[float]],
    power_stream: List[float],
    hr_stream: Optional[List[float]] = None,
    skin_temp_stream: Optional[List[Optional[float]]] = None,
    ambient_temp_stream: Optional[List[Optional[float]]] = None,
    ftp: Optional[float] = None,
) -> ThermalSessionReport:
    """
    Analyze core body temperature data for one session.
    
    Parameters
    ----------
    core_temp_stream : list
        Core body temperature in °C per second. NaN/None for missing.
    power_stream : list
        Power in watts per second.
    hr_stream : list, optional
        Heart rate per second. Required for cardiac drift decomposition.
    skin_temp_stream : list, optional
        Skin temperature in °C per second.
    ambient_temp_stream : list, optional
        Ambient temperature in °C per second.
    ftp : float, optional
        Functional Threshold Power for zone-based analysis.
    
    Returns
    -------
    ThermalSessionReport
    """
    # Align all streams to the shortest common length to avoid shape
    # mismatches when core/power/hr/skin streams differ in length.
    n_total = min(len(power_stream), len(core_temp_stream))
    
    # Convert to numpy and validate
    core = np.array([float(v) if v is not None and v == v else np.nan
                      for v in core_temp_stream[:n_total]], dtype=np.float32)
    power = np.array(power_stream[:n_total], dtype=np.float32)
    
    # Filter: only samples where core temp is valid AND power > threshold
    valid_mask = (~np.isnan(core)) & (power > MIN_POWER_THRESHOLD)
    # Also check physiological range
    valid_mask &= (core >= 30.0) & (core <= 45.0)
    
    n_valid = int(valid_mask.sum())
    
    if n_valid < MIN_VALID_SAMPLES:
        return ThermalSessionReport(
            data_quality="no_data",
            n_valid_samples=n_valid,
            n_total_samples=n_total,
            notes=[
                f"Only {n_valid} valid core temperature samples "
                f"(need {MIN_VALID_SAMPLES}). Is a body-temperature sensor connected?"
            ],
        )
    
    # ---- Core temp statistics ----
    core_valid = core[valid_mask]
    power_valid = power[valid_mask]
    
    # Start: mean of samples 5-10% into the session (past warmup)
    start_idx = max(0, int(len(core_valid) * 0.05))
    end_start = min(len(core_valid), int(len(core_valid) * 0.10))
    core_start = float(np.nanmean(core_valid[start_idx:end_start])) if end_start > start_idx else None
    
    # End: mean of last 5%
    end_idx = max(0, int(len(core_valid) * 0.95))
    core_end = float(np.nanmean(core_valid[end_idx:])) if end_idx < len(core_valid) else None
    
    core_peak = float(np.nanmax(core_valid))
    core_mean = float(np.nanmean(core_valid))
    
    # ---- Thermal rise rate ----
    rise_rate = None
    rise_per_kj = None
    if core_start is not None and core_end is not None:
        duration_min = n_valid / 60.0
        if duration_min > 5:
            rise_rate = (core_end - core_start) / duration_min  # °C/min
        
        # Rise per kJ of work
        total_kj = float(np.sum(power_valid)) / 1000.0  # Joules → kJ
        if total_kj > 10:
            rise_per_kj = (core_end - core_start) / total_kj  # °C/kJ
    
    # ---- Skin temperature ----
    skin_mean = None
    core_skin_grad = None
    if skin_temp_stream is not None and len(skin_temp_stream) >= n_total:
        skin = np.array([float(v) if v is not None and v == v else np.nan
                          for v in skin_temp_stream[:n_total]], dtype=np.float32)
        skin_valid = skin[valid_mask]
        skin_not_nan = skin_valid[~np.isnan(skin_valid)]
        if len(skin_not_nan) > MIN_VALID_SAMPLES:
            skin_mean = float(np.nanmean(skin_not_nan))
            core_skin_grad = core_mean - skin_mean
    
    # ---- Ambient temperature ----
    ambient_mean = None
    if ambient_temp_stream is not None:
        amb = np.array([float(v) if v is not None and v == v else np.nan
                         for v in ambient_temp_stream[:n_total]], dtype=np.float32)
        amb_valid = amb[~np.isnan(amb)]
        if len(amb_valid) > 10:
            ambient_mean = float(np.nanmean(amb_valid))
    
    # ---- Heat tolerance threshold ----
    ht_threshold = _detect_power_drop_temp(core, power)
    ht_class = None
    if ht_threshold is not None:
        if ht_threshold >= 39.5:
            ht_class = "excellent"
        elif ht_threshold >= 39.0:
            ht_class = "good"
        elif ht_threshold >= 38.5:
            ht_class = "fair"
        else:
            ht_class = "poor"
    
    # ---- Cardiac drift decomposition ----
    cardiac_total = cardiac_thermal = cardiac_fatigue = thermal_pct = None
    if hr_stream is not None and len(hr_stream) >= n_total:
        hr = np.array(hr_stream[:n_total], dtype=np.float32)
        hr_valid = hr[valid_mask]
        
        if len(hr_valid) >= MIN_VALID_SAMPLES:
            hr_first, hr_second = _half_means(hr_valid)
            core_first, core_second = _half_means(core_valid)
            
            cardiac_total = hr_second - hr_first
            
            # Thermal component: ~8-10 bpm per °C of core temp rise
            # (Rowell 1974, González-Alonso 2008)
            HR_PER_DEG_C = 9.0  # bpm/°C
            temp_delta = core_second - core_first
            cardiac_thermal = temp_delta * HR_PER_DEG_C
            
            cardiac_fatigue = cardiac_total - cardiac_thermal
            
            if abs(cardiac_total) > 0.5:
                thermal_pct = min(100.0, max(0.0,
                    abs(cardiac_thermal) / abs(cardiac_total) * 100.0))
    
    # ---- Power decay (raw vs thermal-adjusted) ----
    power_decay_raw = power_decay_adj = None
    if len(power_valid) >= MIN_VALID_SAMPLES:
        p_first, p_second = _half_means(power_valid)
        if p_first > 0:
            power_decay_raw = (1 - p_second / p_first) * 100
            
            # Thermal-adjusted: estimate how much power loss is from
            # thermal strain, not fatigue.
            # ~1-2% power loss per °C above 38.5°C (Périard 2021)
            POWER_LOSS_PER_DEG_ABOVE_385 = 1.5  # % per °C
            core_first_m, core_second_m = _half_means(core_valid)
            thermal_power_loss = max(0, core_second_m - 38.5) * POWER_LOSS_PER_DEG_ABOVE_385
            thermal_power_loss -= max(0, core_first_m - 38.5) * POWER_LOSS_PER_DEG_ABOVE_385
            
            power_decay_adj = power_decay_raw - thermal_power_loss
    
    # ---- Efficiency correction factor ----
    eta_correction = None
    if core_mean is not None:
        # Above 38.5°C, efficiency drops ~1% per °C (more energy wasted as heat)
        excess = max(0.0, core_mean - 38.5)
        eta_correction = max(0.85, 1.0 - excess * 0.01)
    
    # ---- Time in thermal zones ----
    zone_time = {
        "resting_below_37.5": int(np.sum(core_valid < 37.5)),
        "warm_37.5_38.5": int(np.sum((core_valid >= 37.5) & (core_valid < 38.5))),
        "hot_38.5_39.0": int(np.sum((core_valid >= 38.5) & (core_valid < 39.0))),
        "caution_39.0_39.5": int(np.sum((core_valid >= 39.0) & (core_valid < 39.5))),
        "danger_above_39.5": int(np.sum(core_valid >= 39.5)),
    }
    
    # ---- Notes ----
    notes = []
    if core_peak >= BODY_TEMP_DANGER:
        notes.append(
            f"Peak core temperature reached {core_peak:.1f}°C — approaching "
            "physiological danger zone. Monitor hydration and consider cooling "
            "strategies."
        )
    if ht_class == "poor":
        notes.append(
            f"Heat tolerance threshold at {ht_threshold:.1f}°C is below average. "
            "Recommend progressive heat acclimation protocol (10 sessions of "
            "60-90 min in controlled heat over 2 weeks)."
        )
    if thermal_pct is not None and thermal_pct > 60:
        notes.append(
            f"~{thermal_pct:.0f}% of cardiac drift is thermal, not fatigue. "
            "The HR rise is largely from thermoregulatory demand, not muscular "
            "deterioration."
        )
    if rise_rate is not None and rise_rate > 0.03:
        notes.append(
            f"Thermal rise rate {rise_rate:.3f}°C/min is above average. "
            "Consider pre-cooling, more frequent hydration, or lighter clothing."
        )
    
    return ThermalSessionReport(
        data_quality="good" if n_valid >= MIN_VALID_SAMPLES * 3 else "partial",
        n_valid_samples=n_valid,
        n_total_samples=n_total,
        core_temp_start=round(core_start, 1) if core_start else None,
        core_temp_end=round(core_end, 1) if core_end else None,
        core_temp_peak=round(core_peak, 1),
        core_temp_mean=round(core_mean, 1),
        skin_temp_mean=round(skin_mean, 1) if skin_mean else None,
        core_skin_gradient=round(core_skin_grad, 1) if core_skin_grad else None,
        ambient_temp_mean=round(ambient_mean, 1) if ambient_mean else None,
        thermal_rise_rate=round(rise_rate, 4) if rise_rate else None,
        thermal_rise_per_kj=round(rise_per_kj, 6) if rise_per_kj else None,
        heat_tolerance_threshold=round(ht_threshold, 1) if ht_threshold else None,
        heat_tolerance_classification=ht_class,
        cardiac_drift_total_bpm=round(cardiac_total, 1) if cardiac_total is not None else None,
        cardiac_drift_thermal_bpm=round(cardiac_thermal, 1) if cardiac_thermal is not None else None,
        cardiac_drift_fatigue_bpm=round(cardiac_fatigue, 1) if cardiac_fatigue is not None else None,
        thermal_drift_pct=round(thermal_pct, 1) if thermal_pct is not None else None,
        power_decay_raw_pct=round(power_decay_raw, 1) if power_decay_raw is not None else None,
        power_decay_thermal_adjusted_pct=round(power_decay_adj, 1) if power_decay_adj is not None else None,
        eta_correction_factor=round(eta_correction, 4) if eta_correction else None,
        time_in_zone_s=zone_time,
        notes=notes,
    )


# =============================================================================
# Longitudinal: heat acclimation tracking
# =============================================================================

def analyze_heat_acclimation(
    session_reports: List[ThermalSessionReport],
) -> HeatAcclimationTrend:
    """
    Track heat acclimation across multiple sessions.
    
    Looks for:
    - Decreasing thermal rise rate (body cools more efficiently)
    - Increasing heat tolerance threshold (can sustain power at higher temps)
    
    Requires ≥3 sessions with valid thermal data.
    """
    # Filter to sessions with usable data
    usable = [
        r for r in session_reports
        if r.data_quality in ("good", "partial")
        and r.thermal_rise_rate is not None
    ]
    
    n = len(usable)
    if n < 3:
        return HeatAcclimationTrend(
            n_sessions=n,
            notes=[f"Only {n} sessions with thermal data. Need ≥3 for trend."],
        )
    
    # Split into baseline (first third) and current (last third)
    third = max(1, n // 3)
    baseline = usable[:third]
    current = usable[-third:]
    
    base_rate = np.mean([r.thermal_rise_rate for r in baseline])
    curr_rate = np.mean([r.thermal_rise_rate for r in current])
    delta = curr_rate - base_rate
    
    # Tolerance threshold (if available)
    base_tol = None
    curr_tol = None
    base_tols = [r.heat_tolerance_threshold for r in baseline if r.heat_tolerance_threshold]
    curr_tols = [r.heat_tolerance_threshold for r in current if r.heat_tolerance_threshold]
    if base_tols:
        base_tol = float(np.mean(base_tols))
    if curr_tols:
        curr_tol = float(np.mean(curr_tols))
    
    # Trend classification
    if delta < -0.003:
        trend = "acclimating"
    elif delta > 0.003:
        trend = "deacclimating"
    else:
        trend = "stable"
    
    # Summary
    parts = []
    if trend == "acclimating":
        parts.append(
            f"Rise rate decreased from {base_rate:.3f} to {curr_rate:.3f} °C/min. "
            "Heat acclimation is progressing."
        )
    elif trend == "deacclimating":
        parts.append(
            f"Rise rate increased from {base_rate:.3f} to {curr_rate:.3f} °C/min. "
            "Heat acclimation may be regressing — ensure regular heat exposure."
        )
    else:
        parts.append("Thermal rise rate is stable across sessions.")
    
    if base_tol and curr_tol:
        tol_delta = curr_tol - base_tol
        if tol_delta > 0.2:
            parts.append(
                f"Heat tolerance threshold improved from {base_tol:.1f}°C "
                f"to {curr_tol:.1f}°C."
            )
    
    return HeatAcclimationTrend(
        n_sessions=n,
        baseline_rise_rate=float(base_rate),
        current_rise_rate=float(curr_rate),
        trend=trend,
        delta_rise_rate=float(delta),
        baseline_tolerance=base_tol,
        current_tolerance=curr_tol,
        summary=" ".join(parts),
    )
