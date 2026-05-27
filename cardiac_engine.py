"""
Cardiac Response Engine — descriptive analysis of HR / HRR / cardiac efficiency
Version: 1.0.0

Modulo backend che, dato uno stream di attività con (timestamp, potenza, HR e
opzionalmente RR), produce un Cardiac Response Profile descrittivo.

NESSUNA logica predittiva: questo modulo legge la risposta cardiaca misurata
e la confronta con benchmark scientifici e (se forniti) con le soglie
metaboliche/autonomiche derivate da MetabolicProfiler e HRV engine.

Metriche implementate (con riferimenti):
  - Aerobic Decoupling (Pa:Hr)               Friel 2006, Maunder 2021
  - Cardiac Drift Index                       Coyle 2001, Lambert 2008
  - HR Recovery (HRR60s, HRR120s)             Cole 1999, Imai 1994
  - HR Kinetics first-order tau               Bunc 1988, Linnarsson 1974
  - Chronotropic Linearity (HR/W slope)       Lauer 1996, Brubaker 2011
  - Cardiac Efficiency Index (W/bpm)          Pinet 2010
  - Threshold HR cross-validation             vs DFA-α1, MLSS

API:
  analyzer = CardiacResponseAnalyzer(
      weight=90.0,
      context=ctx,
      metabolic_snapshot=snap,   # optional, abilita cross-val
      hrv_timeline=hrv_points,   # optional, abilita cross-val con DFA
  )
  result = analyzer.analyze(activity_samples)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import math

import numpy as np
from scipy.optimize import least_squares

from engines.athlete_context import AthleteContext


# =============================================================================
# SCIENTIFIC THRESHOLDS (with references)
# =============================================================================

# Aerobic Decoupling Pa:Hr (Friel 2006, "The Cyclist's Training Bible";
# Maunder et al. 2021, Sports Medicine review). Computed as:
#   decoupling_% = (P/HR)_first_half - (P/HR)_second_half) / (P/HR)_first_half * 100
# Interpretation in steady-state aerobic sessions:
_DECOUPLING_EXCELLENT = 3.0   # < 3%: well-adapted aerobic
_DECOUPLING_GOOD = 5.0        # 3–5%: solid aerobic base
_DECOUPLING_FAIR = 8.0        # 5–8%: moderate aerobic stress
# > 8%: significant stress, intensity probably above MLSS for the session

# Cardiac Drift (Coyle 2001 J Appl Physiol; Lambert 2008 Br J Sports Med):
# percent HR rise during the second half of a constant-power session.
# Drivers: glycogen depletion, dehydration, thermoregulation.
_DRIFT_EXCELLENT = 3.0   # well-fueled, well-trained, well-hydrated
_DRIFT_GOOD = 5.0
_DRIFT_FAIR = 10.0
# > 10%: heat stress, dehydration, glycogen depletion, or session too long

# HR Recovery (Cole et al. 1999 NEJM; Imai et al. 1994 J Am Coll Cardiol):
# absolute HR drop in the first 60 / 120 seconds after cessation of effort.
# Cole specifically validated HRR1min on cycle ergometer.
_HRR60_POOR = 12.0       # \u2264 12 bpm: independent mortality predictor (Cole)
_HRR60_AVERAGE = 18.0    # 12–18: untrained but normal
_HRR60_GOOD = 25.0       # 18–25: trained
# > 25: elite endurance

# Trained subjects show HRR120s \u2265 35-40 bpm; untrained 22-30 bpm.
_HRR120_POOR = 22.0
_HRR120_AVERAGE = 30.0
_HRR120_GOOD = 38.0

# HR on-kinetics first-order tau (Bunc 1988 Eur J Appl Physiol;
# Linnarsson 1974). Measured as response to step change in workload below VT1.
_TAU_HR_ON_ELITE = 25.0      # < 25s: highly trained
_TAU_HR_ON_TRAINED = 35.0    # 25–35s: trained
_TAU_HR_ON_AVERAGE = 50.0    # 35–50s: moderately fit
# > 50s: deconditioned, autonomic blunting, or beta-blockade

# Cardiac Efficiency Index W/bpm at MLSS (Pinet 2010; observational):
# higher values = more work per beat, indicator of trained myocardium.
# Values modulated by body weight; we report absolute and weight-normalized.
_CEI_WKG_BPM_LOW = 0.030     # W/(kg\u00b7bpm) at MLSS
_CEI_WKG_BPM_MID = 0.045
_CEI_WKG_BPM_HIGH = 0.055

# Segmentation parameters
_MIN_STEADY_DURATION_S = 300.0   # 5 minutes minimum for drift/decoupling
_STEADY_CV_POWER_MAX = 0.06      # CV(power) <= 6% within a steady segment
_RAMP_DPDT_MIN = 0.3             # W/s minimum slope for ramp detection
_RAMP_MIN_DURATION_S = 180.0     # 3 minutes minimum ramp
_RECOVERY_POWER_MAX = 30.0       # power <= 30W counts as recovery
_RECOVERY_HR_DROP_MIN = 5.0      # need at least 5 bpm drop to count

# Smoothing windows
_HR_SMOOTH_WINDOW_S = 10.0
_POWER_SMOOTH_WINDOW_S = 30.0   # for steady-state detection
_POWER_KINETICS_WINDOW_S = 3.0  # for ramp/kinetics


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ActivitySample:
    """Single sample at 1Hz of an activity stream."""
    t: float           # seconds elapsed
    power: float       # watts
    hr: float          # bpm
    rr: Optional[List[float]] = None  # ms, optional


@dataclass(frozen=True)
class Segment:
    """Detected homogeneous segment of the activity."""
    kind: str          # "steady" | "ramp" | "recovery"
    start_idx: int
    end_idx: int       # exclusive
    start_t: float
    end_t: float
    duration_s: float
    metadata: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# PREPROCESSING UTILITIES
# =============================================================================

def _to_arrays(samples: List[ActivitySample]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract aligned t/power/hr arrays, dropping invalid samples."""
    t = np.array([s.t for s in samples], dtype=float)
    p = np.array([s.power for s in samples], dtype=float)
    h = np.array([s.hr for s in samples], dtype=float)

    # Filter: HR in [30, 230], power >= 0, finite
    valid = (
        np.isfinite(t) & np.isfinite(p) & np.isfinite(h)
        & (h >= 30.0) & (h <= 230.0)
        & (p >= 0.0)
    )
    return t[valid], p[valid], h[valid]


def _moving_average(x: np.ndarray, window_s: float, t: np.ndarray) -> np.ndarray:
    """
    Causal moving average over a time window.
    Assumes (approximately) regular 1Hz sampling — uses index-based window.
    """
    if x.size == 0:
        return x
    dt = float(np.median(np.diff(t))) if t.size > 1 else 1.0
    n = max(1, int(round(window_s / max(dt, 0.1))))
    if n >= x.size:
        return np.full_like(x, float(np.mean(x)))
    kernel = np.ones(n) / n
    pad = np.full(n - 1, x[0])
    padded = np.concatenate([pad, x])
    return np.convolve(padded, kernel, mode="valid")


# =============================================================================
# SEGMENTATION
# =============================================================================

def _detect_steady_segments(t: np.ndarray, p_smooth: np.ndarray) -> List[Segment]:
    """
    Find intervals of >= _MIN_STEADY_DURATION_S where CV(power) <= threshold
    in a sliding window. Greedy expansion approach.
    """
    segments: List[Segment] = []
    n = len(t)
    if n < 60:
        return segments

    dt = float(np.median(np.diff(t))) if n > 1 else 1.0
    min_samples = max(60, int(_MIN_STEADY_DURATION_S / dt))

    i = 0
    while i < n - min_samples:
        # Try to expand a steady segment from i
        end = i + min_samples
        # Check initial window CV
        window = p_smooth[i:end]
        if window.mean() < 50.0:  # exclude rest segments
            i += min_samples // 2
            continue
        cv = float(np.std(window) / max(window.mean(), 1e-6))
        if cv > _STEADY_CV_POWER_MAX:
            i += min_samples // 4
            continue

        # Expand greedily while CV stays within threshold
        while end < n:
            window = p_smooth[i:end + 1]
            cv = float(np.std(window) / max(window.mean(), 1e-6))
            if cv > _STEADY_CV_POWER_MAX:
                break
            end += 1

        duration = float(t[end - 1] - t[i])
        if duration >= _MIN_STEADY_DURATION_S:
            mean_p = float(np.mean(p_smooth[i:end]))
            segments.append(Segment(
                kind="steady",
                start_idx=i,
                end_idx=end,
                start_t=float(t[i]),
                end_t=float(t[end - 1]),
                duration_s=duration,
                metadata={"mean_power": round(mean_p, 1), "cv_power": round(cv, 4)},
            ))
            i = end
        else:
            i += min_samples // 4

    return segments


def _detect_ramp_segments(t: np.ndarray, p_smooth: np.ndarray) -> List[Segment]:
    """
    Find intervals where power increases monotonically with slope >= threshold.
    """
    segments: List[Segment] = []
    n = len(t)
    if n < 60:
        return segments
    dt = float(np.median(np.diff(t))) if n > 1 else 1.0
    min_samples = max(60, int(_RAMP_MIN_DURATION_S / dt))

    # Compute discrete derivative
    dp = np.gradient(p_smooth, t)

    i = 0
    while i < n - min_samples:
        # Look for sustained dp/dt > threshold
        if dp[i] < _RAMP_DPDT_MIN:
            i += 1
            continue
        end = i
        while end < n and dp[end] >= _RAMP_DPDT_MIN * 0.5:
            end += 1
        duration = float(t[end - 1] - t[i]) if end > i else 0.0
        if duration >= _RAMP_MIN_DURATION_S:
            slope_w_per_s = float((p_smooth[end - 1] - p_smooth[i]) / max(duration, 1.0))
            segments.append(Segment(
                kind="ramp",
                start_idx=i,
                end_idx=end,
                start_t=float(t[i]),
                end_t=float(t[end - 1]),
                duration_s=duration,
                metadata={
                    "p_start": round(float(p_smooth[i]), 1),
                    "p_end": round(float(p_smooth[end - 1]), 1),
                    "slope_w_per_s": round(slope_w_per_s, 3),
                },
            ))
            i = end
        else:
            i += 1
    return segments


def _detect_recovery_segments(
    t: np.ndarray, p_smooth: np.ndarray, h: np.ndarray
) -> List[Segment]:
    """
    Find recovery windows: power drops to ~0 from elevated, HR drops by
    at least _RECOVERY_HR_DROP_MIN within the window.
    """
    segments: List[Segment] = []
    n = len(t)
    if n < 30:
        return segments
    dt = float(np.median(np.diff(t))) if n > 1 else 1.0

    # Find transitions: power_prev > 150W, power_curr < _RECOVERY_POWER_MAX
    in_rec = False
    start = 0
    hr_at_start = 0.0
    for i in range(1, n):
        is_rec = p_smooth[i] <= _RECOVERY_POWER_MAX
        if is_rec and not in_rec:
            # Started a recovery
            if i > 0 and p_smooth[i - 1] >= 100.0:  # came down from elevated
                in_rec = True
                start = i
                hr_at_start = float(h[i])
        elif not is_rec and in_rec:
            # Recovery ended
            duration = float(t[i - 1] - t[start])
            if duration >= 60.0 and (hr_at_start - float(np.min(h[start:i]))) >= _RECOVERY_HR_DROP_MIN:
                segments.append(Segment(
                    kind="recovery",
                    start_idx=start,
                    end_idx=i,
                    start_t=float(t[start]),
                    end_t=float(t[i - 1]),
                    duration_s=duration,
                    metadata={"hr_at_start": round(hr_at_start, 1)},
                ))
            in_rec = False

    # Handle recovery at end of stream
    if in_rec:
        i = n
        duration = float(t[i - 1] - t[start])
        if duration >= 60.0 and (hr_at_start - float(np.min(h[start:i]))) >= _RECOVERY_HR_DROP_MIN:
            segments.append(Segment(
                kind="recovery",
                start_idx=start,
                end_idx=i,
                start_t=float(t[start]),
                end_t=float(t[i - 1]),
                duration_s=duration,
                metadata={"hr_at_start": round(hr_at_start, 1)},
            ))

    return segments


# =============================================================================
# METRIC CALCULATORS (one per scientific metric)
# =============================================================================

def _classify(value: float, low: float, mid: float, high: float, lower_is_better: bool) -> str:
    """Map a value to {EXCELLENT, GOOD, FAIR, POOR}."""
    if lower_is_better:
        if value < low: return "EXCELLENT"
        if value < mid: return "GOOD"
        if value < high: return "FAIR"
        return "POOR"
    else:
        if value > high: return "EXCELLENT"
        if value > mid: return "GOOD"
        if value > low: return "FAIR"
        return "POOR"


def compute_aerobic_decoupling(
    t: np.ndarray, power: np.ndarray, hr: np.ndarray, segment: Segment
) -> Dict[str, Any]:
    """
    Friel's Pa:Hr ratio. Splits the segment in half and compares P/HR.
    Returns negative percent for "coupling" (no drift), positive for decoupling.
    """
    s, e = segment.start_idx, segment.end_idx
    mid = s + (e - s) // 2
    p1 = float(np.mean(power[s:mid]))
    p2 = float(np.mean(power[mid:e]))
    h1 = float(np.mean(hr[s:mid]))
    h2 = float(np.mean(hr[mid:e]))

    if h1 < 1.0 or h2 < 1.0:
        return {"available": False, "reason": "INVALID_HR"}

    ratio1 = p1 / h1
    ratio2 = p2 / h2
    decoupling_pct = (ratio1 - ratio2) / max(ratio1, 1e-6) * 100.0

    return {
        "available": True,
        "decoupling_pct": round(decoupling_pct, 2),
        "p_hr_first_half": round(ratio1, 3),
        "p_hr_second_half": round(ratio2, 3),
        "fitness_class": _classify(
            abs(decoupling_pct),
            _DECOUPLING_EXCELLENT, _DECOUPLING_GOOD, _DECOUPLING_FAIR,
            lower_is_better=True
        ),
        "interpretation": (
            "Aerobic adaptation excellent" if abs(decoupling_pct) < _DECOUPLING_EXCELLENT
            else "Significant aerobic stress" if abs(decoupling_pct) > _DECOUPLING_FAIR
            else "Acceptable aerobic response"
        ),
        "reference": "Friel 2006; Maunder 2021",
    }


def compute_cardiac_drift(
    t: np.ndarray, power: np.ndarray, hr: np.ndarray, segment: Segment
) -> Dict[str, Any]:
    """
    Percent HR rise from first half to second half of a constant-power segment.
    Coyle 2001: drivers are dehydration, glycogen depletion, thermoregulation.
    """
    s, e = segment.start_idx, segment.end_idx
    mid = s + (e - s) // 2
    h1 = float(np.mean(hr[s:mid]))
    h2 = float(np.mean(hr[mid:e]))
    if h1 < 1.0:
        return {"available": False, "reason": "INVALID_HR"}

    drift_pct = (h2 - h1) / h1 * 100.0
    return {
        "available": True,
        "drift_pct": round(drift_pct, 2),
        "hr_first_half": round(h1, 1),
        "hr_second_half": round(h2, 1),
        "fitness_class": _classify(
            drift_pct, _DRIFT_EXCELLENT, _DRIFT_GOOD, _DRIFT_FAIR,
            lower_is_better=True
        ),
        "interpretation": (
            "Stable cardiac output" if drift_pct < _DRIFT_EXCELLENT
            else "Significant fatigue/dehydration markers" if drift_pct > _DRIFT_FAIR
            else "Mild physiological stress"
        ),
        "reference": "Coyle 2001; Lambert 2008",
    }


def compute_hr_recovery(
    t: np.ndarray, hr: np.ndarray, segment: Segment
) -> Dict[str, Any]:
    """
    HRR60s and HRR120s: absolute HR drop from peak to t+60s and t+120s.
    Cole 1999 / Imai 1994 protocol.
    """
    s, e = segment.start_idx, segment.end_idx
    if e <= s + 1:
        return {"available": False, "reason": "EMPTY_SEGMENT"}

    hr_peak = float(np.max(hr[max(0, s - 5):s + 5]))  # peak around recovery start
    t_start = t[s]

    hrr60_idx = np.argmin(np.abs(t - (t_start + 60.0)))
    hrr120_idx = np.argmin(np.abs(t - (t_start + 120.0)))

    out: Dict[str, Any] = {
        "available": True,
        "hr_peak": round(hr_peak, 1),
        "hrr60_bpm": None,
        "hrr60_class": None,
        "hrr120_bpm": None,
        "hrr120_class": None,
        "reference": "Cole 1999 NEJM; Imai 1994 JACC",
    }

    if hrr60_idx >= s and (t[hrr60_idx] - t_start) >= 55.0:
        hrr60 = hr_peak - float(hr[hrr60_idx])
        out["hrr60_bpm"] = round(hrr60, 1)
        out["hrr60_class"] = _classify(
            hrr60, _HRR60_POOR, _HRR60_AVERAGE, _HRR60_GOOD,
            lower_is_better=False
        )

    if hrr120_idx >= s and (t[hrr120_idx] - t_start) >= 115.0 and segment.duration_s >= 115.0:
        hrr120 = hr_peak - float(hr[hrr120_idx])
        out["hrr120_bpm"] = round(hrr120, 1)
        out["hrr120_class"] = _classify(
            hrr120, _HRR120_POOR, _HRR120_AVERAGE, _HRR120_GOOD,
            lower_is_better=False
        )

    return out


def compute_hr_kinetics_tau(
    t: np.ndarray, power: np.ndarray, hr: np.ndarray, segment: Segment
) -> Dict[str, Any]:
    """
    Fits a first-order response model to a ramp segment:
        HR(t) = HR_baseline + (HR_steady - HR_baseline) * (1 - exp(-(t-t0)/tau))
    Lower tau = faster cardiac kinetics = better trained autonomic system.
    Uses scipy.optimize.least_squares for robustness.
    """
    s, e = segment.start_idx, segment.end_idx
    if (e - s) < 30:
        return {"available": False, "reason": "TOO_SHORT"}

    tt = t[s:e] - t[s]
    hh = hr[s:e]
    hr0 = float(np.mean(hh[:5]))
    hr_inf = float(np.mean(hh[-5:]))

    if abs(hr_inf - hr0) < 5.0:
        return {"available": False, "reason": "INSUFFICIENT_HR_RISE"}

    # x = [tau]; HR_baseline and HR_steady fixed at observed extremes
    def residuals(x):
        tau = max(1.0, float(x[0]))
        pred = hr0 + (hr_inf - hr0) * (1.0 - np.exp(-tt / tau))
        return pred - hh

    try:
        res = least_squares(residuals, x0=[30.0], bounds=([5.0], [150.0]), loss="soft_l1")
        tau = float(res.x[0])
        residuals_final = residuals(res.x)
        rmse = float(np.sqrt(np.mean(residuals_final ** 2)))
    except Exception:
        return {"available": False, "reason": "FIT_FAILED"}

    return {
        "available": True,
        "tau_s": round(tau, 1),
        "hr_baseline": round(hr0, 1),
        "hr_steady": round(hr_inf, 1),
        "fit_rmse_bpm": round(rmse, 2),
        "fitness_class": _classify(
            tau, _TAU_HR_ON_ELITE, _TAU_HR_ON_TRAINED, _TAU_HR_ON_AVERAGE,
            lower_is_better=True
        ),
        "interpretation": (
            "Highly responsive cardiac autonomic control" if tau < _TAU_HR_ON_ELITE
            else "Sluggish HR kinetics — possible deconditioning" if tau > _TAU_HR_ON_AVERAGE
            else "Normal trained-athlete kinetics"
        ),
        "reference": "Bunc 1988 EJAP; Linnarsson 1974",
    }


def compute_chronotropic_response(
    t: np.ndarray, power: np.ndarray, hr: np.ndarray, segment: Segment
) -> Dict[str, Any]:
    """
    Linear regression of HR vs Power within a ramp segment.
    Slope (bpm/W) and R² describe the chronotropic linearity.
    Lauer 1996: blunted slope = chronotropic incompetence (clinical) or beta-blockade.
    """
    s, e = segment.start_idx, segment.end_idx
    if (e - s) < 30:
        return {"available": False, "reason": "TOO_SHORT"}

    p = power[s:e]
    h = hr[s:e]
    if float(np.std(p)) < 5.0:
        return {"available": False, "reason": "POWER_NOT_VARYING"}

    # Linear fit: hr = a + b * power
    p_mean = float(np.mean(p))
    h_mean = float(np.mean(h))
    sxx = float(np.sum((p - p_mean) ** 2))
    sxy = float(np.sum((p - p_mean) * (h - h_mean)))
    if sxx < 1e-9:
        return {"available": False, "reason": "DEGENERATE_FIT"}
    slope = sxy / sxx
    intercept = h_mean - slope * p_mean
    pred = intercept + slope * p
    ss_res = float(np.sum((h - pred) ** 2))
    ss_tot = float(np.sum((h - h_mean) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else None

    return {
        "available": True,
        "slope_bpm_per_w": round(slope, 4),
        "intercept_bpm": round(intercept, 1),
        "r_squared": round(r2, 4) if r2 is not None else None,
        "interpretation": (
            "Strongly linear chronotropic response" if r2 is not None and r2 > 0.95
            else "Non-linear chronotropic response" if r2 is not None and r2 < 0.85
            else "Normal linear response"
        ),
        "reference": "Lauer 1996; Brubaker 2011",
    }


def compute_cardiac_efficiency(
    power: np.ndarray, hr: np.ndarray, weight: float, segment: Segment
) -> Dict[str, Any]:
    """
    W/bpm averaged within a steady segment. Normalized by body weight gives
    W/(kg*bpm), comparable across athletes (Pinet 2010).
    """
    s, e = segment.start_idx, segment.end_idx
    p = float(np.mean(power[s:e]))
    h = float(np.mean(hr[s:e]))
    if h < 1.0:
        return {"available": False, "reason": "INVALID_HR"}

    cei = p / h
    cei_norm = cei / weight  # W/(kg\u00b7bpm)

    return {
        "available": True,
        "watts_per_bpm": round(cei, 2),
        "wkg_per_bpm": round(cei_norm, 4),
        "mean_power": round(p, 1),
        "mean_hr": round(h, 1),
        "fitness_class": _classify(
            cei_norm, _CEI_WKG_BPM_LOW, _CEI_WKG_BPM_MID, _CEI_WKG_BPM_HIGH,
            lower_is_better=False
        ),
        "interpretation": (
            "Highly efficient cardiac output per beat" if cei_norm > _CEI_WKG_BPM_HIGH
            else "Below-average mechanical efficiency per beat" if cei_norm < _CEI_WKG_BPM_LOW
            else "Normal trained-athlete efficiency"
        ),
        "reference": "Pinet 2010",
    }


# =============================================================================
# CROSS-VALIDATION
# =============================================================================

def _hr_at_time(t: np.ndarray, hr: np.ndarray, target_t: float) -> Optional[float]:
    """Linear interpolation of HR at a given timestamp."""
    if t.size == 0 or target_t < t[0] or target_t > t[-1]:
        return None
    return float(np.interp(target_t, t, hr))


def cross_validate_thresholds(
    t: np.ndarray,
    power: np.ndarray,
    hr: np.ndarray,
    metabolic_snapshot: Optional[Dict[str, Any]],
    hrv_timeline: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """
    Cross-references HR observed at metabolic / autonomic thresholds:
      - HR @ DFA-α₁ VT1 crossing (from hrv_timeline)
      - HR @ DFA-α₁ VT2 crossing
      - HR @ MLSS power (from metabolic_snapshot, requires steady segment near MLSS)

    Reports are descriptive: "at VT1 your HR was X bpm" — no judgement,
    these are observational reference points.
    """
    out: Dict[str, Any] = {"available": False}

    # HR @ VT1 / VT2 from DFA-α1 timeline
    if hrv_timeline:
        last_aerobic_t: Optional[float] = None
        last_mixed_t: Optional[float] = None
        prev = None
        for p in hrv_timeline:
            cur = p["status"]
            if prev == "AEROBIC" and cur != "AEROBIC":
                last_aerobic_t = float(p["timestamp"])
            if prev != "ANAEROBIC" and cur == "ANAEROBIC":
                last_mixed_t = float(p["timestamp"])
            prev = cur

        if last_aerobic_t is not None:
            hr_vt1 = _hr_at_time(t, hr, last_aerobic_t)
            if hr_vt1 is not None:
                out["hr_at_vt1_dfa"] = round(hr_vt1, 1)
                out["t_at_vt1_dfa"] = int(last_aerobic_t)
                out["available"] = True
        if last_mixed_t is not None:
            hr_vt2 = _hr_at_time(t, hr, last_mixed_t)
            if hr_vt2 is not None:
                out["hr_at_vt2_dfa"] = round(hr_vt2, 1)
                out["t_at_vt2_dfa"] = int(last_mixed_t)
                out["available"] = True

    # HR @ MLSS power: average HR during samples whose smoothed power is
    # within ±5% of MLSS, requiring at least 60 such samples
    if metabolic_snapshot and metabolic_snapshot.get("status") == "success":
        mlss_w = float(metabolic_snapshot["mlss_power_watts"])
        band_lo, band_hi = mlss_w * 0.95, mlss_w * 1.05
        mask = (power >= band_lo) & (power <= band_hi)
        if mask.sum() >= 60:
            hr_at_mlss = float(np.mean(hr[mask]))
            out["hr_at_mlss_observed"] = round(hr_at_mlss, 1)
            out["mlss_power"] = round(mlss_w, 1)
            out["samples_in_mlss_band"] = int(mask.sum())
            out["available"] = True

    # If both VT1 (from DFA) and HRmax (estimated from data) are available,
    # report VT1 as % of observed HRmax — useful for prescription
    if out.get("hr_at_vt1_dfa") is not None and hr.size > 0:
        hr_max_observed = float(np.max(hr))
        out["hr_max_observed"] = round(hr_max_observed, 1)
        if hr_max_observed > 0:
            out["vt1_as_pct_hrmax"] = round(out["hr_at_vt1_dfa"] / hr_max_observed * 100.0, 1)

    return out


# =============================================================================
# MAIN ANALYZER
# =============================================================================

class CardiacResponseAnalyzer:
    """
    Descriptive analyzer of cardiac response to exercise.
    Composes segmentation + per-segment metrics + cross-validation.
    """

    def __init__(
        self,
        weight: float,
        context: Optional[AthleteContext] = None,
        metabolic_snapshot: Optional[Dict[str, Any]] = None,
        hrv_timeline: Optional[List[Dict[str, Any]]] = None,
    ):
        self.weight = max(40.0, float(weight))
        self.context = context if context is not None else AthleteContext()
        self.metabolic_snapshot = metabolic_snapshot
        self.hrv_timeline = hrv_timeline

    def analyze(self, samples: List[ActivitySample]) -> Dict[str, Any]:
        """Run the full descriptive cardiac analysis."""
        if not samples:
            return {"status": "error", "message": "Empty activity stream"}

        t, p, h = _to_arrays(samples)
        if t.size < 60:
            return {"status": "error", "message": "Activity too short (<60 samples)"}

        # Smoothing
        p_smooth_steady = _moving_average(p, _POWER_SMOOTH_WINDOW_S, t)
        p_smooth_kin = _moving_average(p, _POWER_KINETICS_WINDOW_S, t)
        h_smooth = _moving_average(h, _HR_SMOOTH_WINDOW_S, t)

        # Segmentation
        steady_segs = _detect_steady_segments(t, p_smooth_steady)
        ramp_segs = _detect_ramp_segments(t, p_smooth_kin)
        recovery_segs = _detect_recovery_segments(t, p_smooth_steady, h_smooth)

        # Per-segment metrics
        decoupling_results = []
        drift_results = []
        cei_results = []
        for seg in steady_segs:
            decoupling_results.append({
                "segment": self._segment_summary(seg),
                **compute_aerobic_decoupling(t, p, h_smooth, seg),
            })
            drift_results.append({
                "segment": self._segment_summary(seg),
                **compute_cardiac_drift(t, p, h_smooth, seg),
            })
            cei_results.append({
                "segment": self._segment_summary(seg),
                **compute_cardiac_efficiency(p, h_smooth, self.weight, seg),
            })

        kinetics_results = []
        chronotropic_results = []
        for seg in ramp_segs:
            kinetics_results.append({
                "segment": self._segment_summary(seg),
                **compute_hr_kinetics_tau(t, p, h_smooth, seg),
            })
            chronotropic_results.append({
                "segment": self._segment_summary(seg),
                **compute_chronotropic_response(t, p, h_smooth, seg),
            })

        recovery_results = []
        for seg in recovery_segs:
            recovery_results.append({
                "segment": self._segment_summary(seg),
                **compute_hr_recovery(t, h_smooth, seg),
            })

        # Cross-validation
        cross_val = cross_validate_thresholds(
            t, p_smooth_steady, h_smooth,
            self.metabolic_snapshot, self.hrv_timeline
        )

        # Aggregate fitness summary
        summary = self._aggregate_summary(
            decoupling_results, drift_results, cei_results,
            kinetics_results, recovery_results
        )

        return {
            "status": "success",
            "schema_version": "1.0.0",
            "summary": summary,
            "segments": {
                "steady": [self._segment_summary(s) for s in steady_segs],
                "ramp": [self._segment_summary(s) for s in ramp_segs],
                "recovery": [self._segment_summary(s) for s in recovery_segs],
            },
            "metrics": {
                "aerobic_decoupling": decoupling_results,
                "cardiac_drift": drift_results,
                "cardiac_efficiency": cei_results,
                "hr_kinetics": kinetics_results,
                "chronotropic_response": chronotropic_results,
                "hr_recovery": recovery_results,
            },
            "cross_validation": cross_val,
            "stream_summary": {
                "duration_s": int(t[-1] - t[0]),
                "samples_valid": int(t.size),
                "mean_power": round(float(np.mean(p)), 1),
                "mean_hr": round(float(np.mean(h)), 1),
                "max_hr": round(float(np.max(h)), 1),
                "max_power": round(float(np.max(p)), 1),
            },
            "context_used": {
                "weight_kg": self.weight,
                "training_years": self.context.effective_training_years(),
                "discipline": self.context.effective_discipline(),
                "has_metabolic_snapshot": self.metabolic_snapshot is not None,
                "has_hrv_timeline": self.hrv_timeline is not None,
            },
        }

    @staticmethod
    def _segment_summary(seg: Segment) -> Dict[str, Any]:
        return {
            "kind": seg.kind,
            "start_t": int(seg.start_t),
            "end_t": int(seg.end_t),
            "duration_s": int(seg.duration_s),
            **seg.metadata,
        }

    @staticmethod
    def _aggregate_summary(
        decoupling: List[Dict[str, Any]],
        drift: List[Dict[str, Any]],
        cei: List[Dict[str, Any]],
        kinetics: List[Dict[str, Any]],
        recovery: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Aggregate per-metric fitness classes into a global cardiac fitness rating.
        Each available metric contributes equally; missing metrics simply
        reduce the confidence.
        """
        class_to_score = {"EXCELLENT": 4, "GOOD": 3, "FAIR": 2, "POOR": 1}

        scores: List[int] = []
        contributions: Dict[str, str] = {}

        if decoupling and any(d.get("available") for d in decoupling):
            classes = [d["fitness_class"] for d in decoupling if d.get("available")]
            avg = round(np.mean([class_to_score[c] for c in classes]))
            scores.append(avg)
            contributions["aerobic_decoupling"] = _score_to_class(avg)

        if drift and any(d.get("available") for d in drift):
            classes = [d["fitness_class"] for d in drift if d.get("available")]
            avg = round(np.mean([class_to_score[c] for c in classes]))
            scores.append(avg)
            contributions["cardiac_drift"] = _score_to_class(avg)

        if cei and any(d.get("available") for d in cei):
            classes = [d["fitness_class"] for d in cei if d.get("available")]
            avg = round(np.mean([class_to_score[c] for c in classes]))
            scores.append(avg)
            contributions["cardiac_efficiency"] = _score_to_class(avg)

        if kinetics and any(d.get("available") for d in kinetics):
            classes = [d["fitness_class"] for d in kinetics if d.get("available")]
            avg = round(np.mean([class_to_score[c] for c in classes]))
            scores.append(avg)
            contributions["hr_kinetics"] = _score_to_class(avg)

        if recovery and any(d.get("available") for d in recovery):
            available_classes = []
            for r in recovery:
                if r.get("hrr60_class"):
                    available_classes.append(r["hrr60_class"])
                elif r.get("hrr120_class"):
                    available_classes.append(r["hrr120_class"])
            if available_classes:
                avg = round(np.mean([class_to_score[c] for c in available_classes]))
                scores.append(avg)
                contributions["hr_recovery"] = _score_to_class(avg)

        if not scores:
            return {
                "fitness_class": "UNKNOWN",
                "confidence": 0.0,
                "n_metrics_available": 0,
                "contributions": contributions,
                "message": "Activity did not contain segments suitable for cardiac analysis",
            }

        global_score = float(np.mean(scores))
        # Confidence: 1.0 with all 5 metrics, 0.2 with 1 metric
        confidence = 0.2 + 0.8 * ((len(scores) - 1) / 4.0)

        return {
            "fitness_class": _score_to_class(round(global_score)),
            "global_score": round(global_score, 2),
            "confidence": round(min(1.0, confidence), 2),
            "n_metrics_available": len(scores),
            "contributions": contributions,
        }


def _score_to_class(score: int) -> str:
    return {4: "EXCELLENT", 3: "GOOD", 2: "FAIR", 1: "POOR"}.get(score, "UNKNOWN")
