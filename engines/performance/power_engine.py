"""
Power Engine — Coggan-style power analytics from a single activity
Version: 1.0.0

Computes the canonical power metrics that coaches use daily:
  - Average Power, Normalized Power (NP)
  - Intensity Factor (IF), Training Stress Score (TSS)
  - Variability Index (VI)
  - Total Work (kJ)
  - Mean Maximal Power curve (MMP) for standard durations
  - Sprint peak power (5s)
  - W/kg metrics
  - Critical Power + W' from MMP, when enough max-effort points are available

References:
  - Coggan & Allen 2010, "Training and Racing with a Power Meter" (3rd ed.)
  - Skiba 2008, "The W' balance model"
  - Monod & Scherrer 1965 (CP concept origin)

The engine is stateless: input is an ActivityStream (or any object with
.elapsed_s / .power / .heart_rate / .total_elapsed_s), output is a dict.
FTP must be supplied — it's a coach decision, not auto-computed here.
A separate utility `estimate_ftp_from_mmp` lets the caller derive FTP from
the MMP if desired.
"""

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from engines.core.metric_contracts import annotate_payload
from engines.core.analysis import safe_dt


# =============================================================================
# CONSTANTS
# =============================================================================

# NP rolling-average window (Coggan's spec is exactly 30s, causal).
_NP_WINDOW_S = 30

# Standard MMP durations (seconds) reported by most platforms.
_DEFAULT_MMP_DURATIONS = (1, 5, 10, 15, 30, 60, 120, 180, 300,
                          600, 900, 1200, 1800, 2700, 3600, 5400, 7200)

# Sprint detection: power > sprint_threshold_pct of FTP for at least 3s.
# Coggan's Z6/Z7 boundary is at 121% FTP; we use 150% to flag "sprints"
# specifically (vs sustained efforts above threshold).
_SPRINT_THRESHOLD_PCT = 1.50
_SPRINT_MIN_DURATION_S = 3.0

# FTP estimation from MMP: Coggan's classic 95% of best 20-minute power
# (Allen & Coggan, 3rd ed., p. 58–60). Validated against MLSS testing.
_FTP_FROM_BEST_20MIN_FACTOR = 0.95

# CP + W' fitting: requires MMP points whose durations are in the
# 2–15 minute window AND that are believed to be max efforts.
# Outside this window the 2-parameter hyperbolic model breaks down
# (anaerobic capacity dominates short, glycogen depletes long).
_CP_FIT_DURATION_MIN_S = 120
_CP_FIT_DURATION_MAX_S = 900
_CP_FIT_MIN_POINTS = 3


# =============================================================================
# STREAM PREPARATION
# =============================================================================

def _stream_to_arrays(stream) -> Dict[str, np.ndarray]:
    """
    Extract aligned numpy arrays from an ActivityStream-like object.
    Power None \u2192 0.0 (treated as coasting/stop, standard convention for
    averaging; for NP these get smoothed by the 30s rolling window).
    """
    n = len(stream.elapsed_s)
    t = np.array(stream.elapsed_s, dtype=float)

    p = np.array([
        float(v) if v is not None and v >= 0 else 0.0
        for v in stream.power
    ], dtype=float)

    h = np.array([
        float(v) if v is not None and 30 <= v <= 230 else np.nan
        for v in stream.heart_rate
    ], dtype=float)

    return {"t": t, "power": p, "hr": h, "n": n}


def _moving_time_seconds(power: np.ndarray, t: np.ndarray) -> int:
    """
    Coggan moving time: sum of seconds where power > 0.
    For attivities with autopause already applied this approximates
    timer_time. For non-paused activities it gives a meaningful denominator
    excluding stops at lights, etc.
    """
    if power.size == 0:
        return 0
    moving = power > 0
    if not moving.any():
        return 0
    # Each sample at 1Hz contributes 1s
    dt = safe_dt(t)
    return int(round(moving.sum() * dt))


# =============================================================================
# PRIMARY METRICS
# =============================================================================

def _causal_rolling_mean(x: np.ndarray, window: int) -> np.ndarray:
    """Causal (backward-looking) rolling mean. Edges padded with the first value."""
    if x.size == 0:
        return x
    if window >= x.size:
        return np.full_like(x, float(np.mean(x)))
    pad = np.full(window - 1, x[0])
    padded = np.concatenate([pad, x])
    kernel = np.ones(window) / window
    return np.convolve(padded, kernel, mode="valid")


def normalized_power(power: np.ndarray) -> float:
    """
    Coggan's Normalized Power algorithm:
      1. 30-second causal rolling average
      2. Raise to the 4th power
      3. Take the mean
      4. Take the 4th root

    NP is undefined for activities shorter than ~5 minutes (the 30s window
    has not enough variance to be meaningful). We compute it anyway and let
    the caller decide; the function returns 0.0 only for empty input.
    """
    if power.size == 0:
        return 0.0
    rolling = _causal_rolling_mean(power, _NP_WINDOW_S)
    fourth = rolling ** 4
    return float(np.power(np.mean(fourth), 0.25))


def training_stress_score(np_value: float, ftp: float, duration_s: float) -> float:
    """
    Coggan TSS: 1 hour at FTP = 100 TSS.
    TSS = (duration_s * NP * IF) / (FTP * 3600) * 100
        = (duration_s / 3600) * IF^2 * 100
    """
    if ftp <= 0 or duration_s <= 0:
        return 0.0
    if_value = np_value / ftp
    return float((duration_s / 3600.0) * (if_value ** 2) * 100.0)


def variability_index(np_value: float, avg_power: float) -> Optional[float]:
    """
    VI = NP / AvgPower. Pacing indicator:
      ~1.00 \u2192 perfectly steady (TT, climbing intervals)
      1.05 \u2192 mixed terrain endurance
      >1.10 \u2192 highly variable (criterium, surges, MTB)
    """
    if avg_power <= 0:
        return None
    return float(np_value / avg_power)


# =============================================================================
# MEAN MAXIMAL POWER (MMP) CURVE
# =============================================================================

def mean_maximal_power(
    power: np.ndarray,
    durations_s: Sequence[int] = _DEFAULT_MMP_DURATIONS,
) -> List[Dict[str, Any]]:
    """
    For each target duration, find the maximum mean power over any window
    of that length within the activity. O(N) per duration via cumulative sum.
    """
    n = power.size
    if n == 0:
        return []

    # Use cumulative sum trick for O(1) window means
    cumsum = np.concatenate([[0.0], np.cumsum(power)])
    out: List[Dict[str, Any]] = []
    for d in durations_s:
        w = int(d)
        if w <= 0 or w > n:
            continue
        # Window means: (cumsum[i+w] - cumsum[i]) / w for i in 0..n-w
        window_sums = cumsum[w:] - cumsum[:-w]
        if window_sums.size == 0:
            continue
        max_avg = float(np.max(window_sums) / w)
        max_idx = int(np.argmax(window_sums))
        out.append({
            "duration_s": w,
            "power_w": round(max_avg, 1),
            "start_t": float(max_idx),
        })
    return out


# =============================================================================
# SPRINT DETECTION
# =============================================================================

def detect_sprints(
    power: np.ndarray,
    t: np.ndarray,
    ftp: float,
) -> List[Dict[str, Any]]:
    """
    Identify sprint efforts: contiguous segments where power > 1.5 × FTP
    sustained for \u2265 3 seconds. Returns peak power and duration of each.
    """
    if ftp <= 0 or power.size == 0:
        return []

    threshold = ftp * _SPRINT_THRESHOLD_PCT
    above = power > threshold
    sprints: List[Dict[str, Any]] = []

    i = 0
    n = power.size
    while i < n:
        if not above[i]:
            i += 1
            continue
        start = i
        while i < n and above[i]:
            i += 1
        end = i  # exclusive
        duration = float(t[end - 1] - t[start])
        if duration >= _SPRINT_MIN_DURATION_S:
            seg_power = power[start:end]
            sprints.append({
                "start_t": float(t[start]),
                "duration_s": round(duration, 1),
                "peak_power": round(float(np.max(seg_power)), 1),
                "avg_power": round(float(np.mean(seg_power)), 1),
            })
    return sprints


# =============================================================================
# CRITICAL POWER + W' (Skiba 2-parameter model)
# =============================================================================

def fit_critical_power(mmp: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Hyperbolic 2-parameter CP model: P(t) = W' / t + CP.
    Equivalent linear form: total_work(t) = CP * t + W'.

    We use the linear form because it's more numerically stable. We fit
    only on MMP points within the 2–15 min window where the model is valid.

    Returns None if insufficient data points.
    """
    fit_points = [
        m for m in mmp
        if _CP_FIT_DURATION_MIN_S <= m["duration_s"] <= _CP_FIT_DURATION_MAX_S
    ]
    if len(fit_points) < _CP_FIT_MIN_POINTS:
        return None

    durs = np.array([m["duration_s"] for m in fit_points], dtype=float)
    powers = np.array([m["power_w"] for m in fit_points], dtype=float)
    works = powers * durs

    # Linear fit: work = CP * duration + W'
    d_mean = float(np.mean(durs))
    w_mean = float(np.mean(works))
    sxx = float(np.sum((durs - d_mean) ** 2))
    sxy = float(np.sum((durs - d_mean) * (works - w_mean)))
    if sxx < 1e-9:
        return None
    cp = sxy / sxx
    wprime = w_mean - cp * d_mean

    # Goodness of fit (R²)
    pred = cp * durs + wprime
    ss_res = float(np.sum((works - pred) ** 2))
    ss_tot = float(np.sum((works - w_mean) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else None

    # Sanity check: CP must be positive and W' must be positive
    if cp <= 0 or wprime <= 0:
        return None

    return {
        "cp_w": round(cp, 1),
        "wprime_kj": round(wprime / 1000.0, 2),
        "r_squared": round(r2, 4) if r2 is not None else None,
        "n_points": len(fit_points),
        "fit_durations_s": [int(d) for d in durs],
        "reference": "Monod & Scherrer 1965; Skiba 2008",
    }


def estimate_ftp_from_mmp(
    mmp: List[Dict[str, Any]],
    cp_estimate: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Estimate FTP from MMP curve using the best available method:
      1. If we have a 20-min max effort \u2192 95% of it (Coggan's standard).
      2. Else, if CP fit is available and the activity covers 2–15 min \u2192 CP.
      3. Else \u2192 return None.

    The caller should treat this as an estimate and prefer an explicit FTP
    from a formal test when available.
    """
    by_duration = {m["duration_s"]: m for m in mmp}

    if 1200 in by_duration:
        p20 = by_duration[1200]["power_w"]
        return {
            "ftp_w": round(p20 * _FTP_FROM_BEST_20MIN_FACTOR, 1),
            "method": "best_20min_x_0.95",
            "source_power": p20,
            "reference": "Allen & Coggan 2010",
        }

    if cp_estimate is not None and cp_estimate > 0:
        return {
            "ftp_w": round(cp_estimate, 1),
            "method": "critical_power",
            "source_power": cp_estimate,
            "reference": "Skiba 2008",
        }

    if 3600 in by_duration:
        # Last resort: 1-hour MMP if it exists (rarely truly maximal)
        p60 = by_duration[3600]["power_w"]
        return {
            "ftp_w": round(p60, 1),
            "method": "best_60min",
            "source_power": p60,
            "reference": "FTP definition",
        }

    return {"ftp_w": None, "method": None}


# =============================================================================
# MAIN ENGINE
# =============================================================================

class PowerEngine:
    """
    Stateless analyzer of one activity's power data.

    Usage:
        engine = PowerEngine(ftp=300, weight_kg=90)
        result = engine.analyze(stream)

    The FTP is the coach's decision (from a recent ramp test, MLSS, or
    longitudinal best). For an estimate from this activity alone, call
    estimate_ftp_from_mmp(result['mmp_curve']) afterwards.
    """

    def __init__(
        self,
        ftp: float,
        weight_kg: float,
        ftp_source: str = "explicit",
    ):
        if ftp <= 0:
            raise ValueError(f"FTP must be positive, got {ftp}")
        if weight_kg < 30:
            raise ValueError(f"weight_kg implausibly low: {weight_kg}")

        self.ftp = float(ftp)
        self.weight_kg = float(weight_kg)
        self.ftp_source = ftp_source

    def analyze(self, stream) -> Dict[str, Any]:
        """Run the full power analysis. Returns a structured dict."""
        arrs = _stream_to_arrays(stream)
        t = arrs["t"]
        p = arrs["power"]
        n = arrs["n"]

        if n == 0:
            return annotate_payload(
                {"status": "error", "message": "Empty stream"},
                module_name="power_engine",
                method="coggan_power_metrics",
                confidence=0.0,
            )

        if not (p > 0).any():
            return annotate_payload({
                "status": "error",
                "message": "No power data in stream — cannot compute power metrics",
            }, module_name="power_engine", method="coggan_power_metrics", confidence=0.0)

        # Headline metrics
        total_s = float(stream.total_elapsed_s) if getattr(stream, "total_elapsed_s", 0) else float(t[-1] - t[0] + 1)
        # Degenerate timestamps (all-NaN / non-monotonic) can make total_s NaN
        # or non-positive; fall back to sample count (assumes ~1 Hz).
        if not np.isfinite(total_s) or total_s <= 0:
            total_s = float(len(p))
        moving_s = _moving_time_seconds(p, t)
        avg_p = float(np.mean(p))
        # Avg power excluding zeros (more meaningful for steady efforts)
        nonzero = p[p > 0]
        avg_p_moving = float(np.mean(nonzero)) if nonzero.size else 0.0
        max_p = float(np.max(p))
        np_val = normalized_power(p)
        if_val = np_val / self.ftp
        tss = training_stress_score(np_val, self.ftp, total_s)
        vi = variability_index(np_val, avg_p)
        work_kj = float(np.sum(p)) / 1000.0  # \u03a3(W\u00b7s) \u2192 kJ since dt=1s

        # MMP curve
        mmp = mean_maximal_power(p)
        # Add W/kg
        for m in mmp:
            m["wkg"] = round(m["power_w"] / self.weight_kg, 2)

        # Sprints
        sprints = detect_sprints(p, t, self.ftp)

        # CP + W' (only if duration covers the 2–15min window)
        cp_fit = fit_critical_power(mmp)

        # Quick W/kg metrics from MMP
        by_d = {m["duration_s"]: m for m in mmp}
        wkg_5s = by_d.get(5, {}).get("wkg")
        wkg_1min = by_d.get(60, {}).get("wkg")
        wkg_5min = by_d.get(300, {}).get("wkg")
        wkg_20min = by_d.get(1200, {}).get("wkg")

        result = {
            "status": "success",
            "schema_version": "1.0.0",
            "ftp_used": self.ftp,
            "ftp_source": self.ftp_source,
            "weight_kg": self.weight_kg,
            "metrics": {
                "duration_s": int(total_s),
                "moving_time_s": moving_s,
                "average_power": round(avg_p, 1),
                "average_power_moving": round(avg_p_moving, 1),
                "max_power": round(max_p, 1),
                "normalized_power": round(np_val, 1),
                "intensity_factor": round(if_val, 3),
                "tss": round(tss, 1),
                "variability_index": round(vi, 3) if vi is not None else None,
                "work_kj": round(work_kj, 1),
                "wkg_average": round(avg_p / self.weight_kg, 2),
                "wkg_5s": wkg_5s,
                "wkg_1min": wkg_1min,
                "wkg_5min": wkg_5min,
                "wkg_20min": wkg_20min,
            },
            "mmp_curve": mmp,
            "sprints": {
                "count": len(sprints),
                "max_peak_w": round(max(s["peak_power"] for s in sprints), 1) if sprints else None,
                "events": sprints,
            },
            "critical_power": cp_fit,
        }
        return annotate_payload(
            result,
            module_name="power_engine",
            method="coggan_power_metrics",
            confidence=1.0 if moving_s > 0 else 0.0,
            limitations=[] if self.ftp_source == "explicit" else ["FTP was estimated."],
        )
