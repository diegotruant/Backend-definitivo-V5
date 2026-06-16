"""Non-proprietary activity intelligence derived from parsed activity streams.

This module intentionally contains no third-party product vocabulary and no
vendor-specific scoring names. It turns an ActivityStream-like object into a
canonical analysis envelope that the frontend can render without re-implementing
sport calculations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from engines.core.analysis import safe_dt
from engines.core.metric_contracts import annotate_payload
from engines.io.activity_statistics import compute_activity_statistics
from engines.io.data_quality_report import build_data_quality_report
from engines.performance.power_engine import _stream_to_arrays, normalized_power

_DEFAULT_EFFORT_DURATIONS = [1, 5, 10, 15, 20, 30, 60, 180, 300, 600, 1200, 1800, 3600]


@dataclass(frozen=True)
class Zone:
    id: str
    label: str
    min_value: float
    max_value: Optional[float]


def _as_float_array(values: Any) -> np.ndarray:
    if values is None:
        return np.array([], dtype=float)
    try:
        arr = np.asarray(values, dtype=float)
    except Exception:
        return np.array([], dtype=float)
    return arr[np.isfinite(arr)] if arr.ndim == 1 else np.array([], dtype=float)


def _full_array(values: Any) -> np.ndarray:
    if values is None:
        return np.array([], dtype=float)
    try:
        return np.asarray(values, dtype=float)
    except Exception:
        return np.array([], dtype=float)


def _rolling_mean_max(values: np.ndarray, window: int) -> Optional[float]:
    if window <= 0 or values.size < window:
        return None
    clean = np.where(np.isfinite(values), values, 0.0).astype(float)
    kernel = np.ones(window, dtype=float)
    sums = np.convolve(clean, kernel, mode="valid")
    return float(np.max(sums / window)) if sums.size else None


def compute_best_efforts(
    values: Iterable[float],
    *,
    dt_s: float = 1.0,
    durations_s: Optional[List[int]] = None,
    weight_kg: Optional[float] = None,
) -> Dict[str, Any]:
    """Return best rolling averages for common durations."""
    arr = _full_array(list(values))
    if arr.size == 0:
        return {"status": "skipped", "reason": "no_values", "efforts": []}
    durations = durations_s or _DEFAULT_EFFORT_DURATIONS
    efforts = []
    for duration_s in durations:
        window = max(1, int(round(duration_s / max(dt_s, 1e-6))))
        value = _rolling_mean_max(arr, window)
        if value is None:
            continue
        efforts.append(
            {
                "duration_s": duration_s,
                "value": round(value, 1),
                "value_per_kg": round(value / weight_kg, 2) if weight_kg and weight_kg > 0 else None,
            }
        )
    return {"status": "success" if efforts else "skipped", "efforts": efforts}


def _zone_defs_from_threshold(threshold: Optional[float], kind: str) -> List[Zone]:
    if not threshold or threshold <= 0:
        return []
    if kind == "power":
        bands = [
            ("z1", "Recovery", 0.00, 0.55),
            ("z2", "Endurance", 0.55, 0.75),
            ("z3", "Tempo", 0.75, 0.90),
            ("z4", "Threshold", 0.90, 1.05),
            ("z5", "VO2", 1.05, 1.20),
            ("z6", "Anaerobic", 1.20, 1.50),
            ("z7", "Sprint", 1.50, None),
        ]
    else:
        bands = [
            ("z1", "Easy", 0.00, 0.80),
            ("z2", "Endurance", 0.80, 0.88),
            ("z3", "Tempo", 0.88, 0.94),
            ("z4", "Threshold", 0.94, 1.00),
            ("z5", "High", 1.00, None),
        ]
    zones: List[Zone] = []
    for zid, label, lo, hi in bands:
        zones.append(Zone(zid, label, threshold * lo, threshold * hi if hi is not None else None))
    return zones


def compute_zone_distribution(
    values: Iterable[float],
    *,
    threshold: Optional[float],
    kind: str,
    dt_s: float = 1.0,
) -> Dict[str, Any]:
    """Time in zones from a threshold. Returns seconds and percentages."""
    arr = _full_array(list(values))
    zones = _zone_defs_from_threshold(threshold, kind)
    valid = arr[np.isfinite(arr) & (arr > 0)]
    if not zones or valid.size == 0:
        return {"status": "skipped", "reason": "missing_threshold_or_values", "zones": []}
    total_s = float(valid.size * dt_s)
    out = []
    for zone in zones:
        mask = valid >= zone.min_value
        if zone.max_value is not None:
            mask &= valid < zone.max_value
        seconds = float(mask.sum() * dt_s)
        out.append(
            {
                "id": zone.id,
                "label": zone.label,
                "seconds": round(seconds, 1),
                "pct": round((seconds / total_s) * 100.0, 1) if total_s > 0 else 0.0,
                "min": round(zone.min_value, 1),
                "max": round(zone.max_value, 1) if zone.max_value is not None else None,
            }
        )
    return {"status": "success", "zones": out}


def detect_auto_intervals(
    power: Iterable[float],
    *,
    dt_s: float = 1.0,
    threshold_w: Optional[float] = None,
    min_duration_s: int = 30,
) -> Dict[str, Any]:
    """Simple work-interval detector based on sustained power above a threshold."""
    arr = _full_array(list(power))
    clean = np.where(np.isfinite(arr), arr, 0.0)
    if clean.size == 0 or np.max(clean) <= 0:
        return {"status": "skipped", "reason": "no_power", "intervals": []}
    threshold = float(threshold_w) if threshold_w and threshold_w > 0 else max(180.0, float(np.percentile(clean[clean > 0], 75)))
    active = clean >= threshold
    intervals = []
    start_idx: Optional[int] = None
    min_samples = max(1, int(round(min_duration_s / max(dt_s, 1e-6))))
    for i, flag in enumerate(active):
        if flag and start_idx is None:
            start_idx = i
        elif not flag and start_idx is not None:
            if i - start_idx >= min_samples:
                seg = clean[start_idx:i]
                intervals.append(_interval_payload(start_idx, i - 1, seg, dt_s))
            start_idx = None
    if start_idx is not None and clean.size - start_idx >= min_samples:
        seg = clean[start_idx:]
        intervals.append(_interval_payload(start_idx, clean.size - 1, seg, dt_s))
    return {"status": "success" if intervals else "skipped", "threshold_w": round(threshold, 1), "intervals": intervals}


def _interval_payload(start_idx: int, end_idx: int, segment: np.ndarray, dt_s: float) -> Dict[str, Any]:
    np_w = normalized_power(segment) if segment.size >= 30 else float(np.mean(segment))
    return {
        "start_s": round(start_idx * dt_s, 1),
        "end_s": round((end_idx + 1) * dt_s, 1),
        "duration_s": round((end_idx - start_idx + 1) * dt_s, 1),
        "avg_power_w": round(float(np.mean(segment)), 1) if segment.size else None,
        "max_power_w": round(float(np.max(segment)), 1) if segment.size else None,
        "np_w": round(float(np_w), 1) if np_w is not None else None,
    }


def build_chart_series(stream: Any, *, max_points: int = 2000) -> Dict[str, Any]:
    """Downsample common time-series into frontend-ready arrays."""
    arrs = _stream_to_arrays(stream)
    t = arrs.get("t", np.array([], dtype=float))
    n = int(arrs.get("n", 0) or 0)
    if n <= 0:
        return {"status": "skipped", "reason": "empty_stream", "series": {}}
    step = max(1, int(np.ceil(n / max_points)))
    idx = np.arange(0, n, step)
    def pick(name: str, values: Any) -> List[Optional[float]]:
        raw = _full_array(values)
        if raw.size < n:
            return []
        out = []
        for v in raw[idx]:
            out.append(round(float(v), 3) if np.isfinite(v) else None)
        return out
    series: Dict[str, List[Optional[float]]] = {"time_s": [round(float(x), 1) for x in t[idx]] if t.size >= n else [float(i * step) for i in range(len(idx))]}
    for key, attr in [
        ("power_w", "power"),
        ("heart_rate_bpm", "heart_rate"),
        ("cadence_rpm", "cadence"),
        ("speed_mps", "speed_mps"),
        ("altitude_m", "altitude_m"),
        ("temperature_c", "temperature_c"),
        ("respiration_rate", "respiration_rate"),
    ]:
        vals = pick(key, getattr(stream, attr, None))
        if vals:
            series[key] = vals
    return {"status": "success", "sample_step": step, "series": series}


def compute_cardiac_decoupling(stream: Any, *, min_duration_s: int = 1200) -> Dict[str, Any]:
    """Estimate second-half drift in power/heart-rate ratio."""
    arrs = _stream_to_arrays(stream)
    p = arrs.get("power", np.array([], dtype=float))
    hr = arrs.get("hr", np.array([], dtype=float))
    t = arrs.get("t", np.array([], dtype=float))
    n = int(arrs.get("n", 0) or 0)
    duration = float(t[-1] - t[0]) if t.size > 1 else float(n)
    if n < 120 or duration < min_duration_s or p.size != hr.size:
        return {"status": "skipped", "reason": "insufficient_duration_or_signals"}
    mask = np.isfinite(p) & np.isfinite(hr) & (p > 0) & (hr > 30)
    if mask.sum() < 120:
        return {"status": "skipped", "reason": "insufficient_valid_samples"}
    mid = n // 2
    def ratio(sl: slice) -> Optional[float]:
        mp = p[sl][mask[sl]]
        mh = hr[sl][mask[sl]]
        if mp.size < 30 or mh.size < 30 or np.mean(mh) <= 0:
            return None
        return float(np.mean(mp) / np.mean(mh))
    r1 = ratio(slice(0, mid))
    r2 = ratio(slice(mid, n))
    if not r1 or not r2:
        return {"status": "skipped", "reason": "insufficient_halves"}
    drift_pct = ((r2 - r1) / r1) * 100.0
    return {
        "status": "success",
        "first_half_power_hr_ratio": round(r1, 4),
        "second_half_power_hr_ratio": round(r2, 4),
        "decoupling_pct": round(drift_pct, 2),
        "interpretation": "stable" if abs(drift_pct) <= 5 else "drift_detected",
    }


def build_activity_intelligence(
    stream: Any,
    *,
    weight_kg: float,
    ftp: Optional[float] = None,
    cp: Optional[float] = None,
    lthr: Optional[float] = None,
) -> Dict[str, Any]:
    """Build a complete activity intelligence envelope for one ride."""
    arrs = _stream_to_arrays(stream)
    power = arrs.get("power", np.array([], dtype=float))
    hr = arrs.get("hr", np.array([], dtype=float))
    t = arrs.get("t", np.array([], dtype=float))
    dt = safe_dt(t) if t.size else 1.0
    power_threshold = cp or ftp
    statistics = compute_activity_statistics(stream, weight_kg=weight_kg, ftp=ftp, cp=cp, lthr=lthr)
    payload: Dict[str, Any] = {
        "status": "success",
        "schema_version": "1.0.0",
        "statistics": statistics.get("metrics", statistics),
        "best_efforts_power": compute_best_efforts(power, dt_s=dt, weight_kg=weight_kg),
        "power_zones": compute_zone_distribution(power, threshold=power_threshold, kind="power", dt_s=dt),
        "heart_rate_zones": compute_zone_distribution(hr, threshold=lthr, kind="heart_rate", dt_s=dt),
        "auto_intervals": detect_auto_intervals(power, dt_s=dt, threshold_w=power_threshold),
        "cardiac_decoupling": compute_cardiac_decoupling(stream),
        "data_quality": build_data_quality_report(stream),
        "chart_series": build_chart_series(stream),
    }
    confidence = 0.95 if power.size and np.nanmax(power) > 0 else 0.55
    return annotate_payload(payload, module_name="activity_intelligence", method="stream_summary", confidence=confidence)
