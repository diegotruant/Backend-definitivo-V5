"""
Basic activity statistics for coach-facing summary pages.

Computes headline ride metrics from an ActivityStream-like object plus athlete
context (weight, optional FTP/CP/LTHR for metadata only — NP does not require FTP).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

from engines.core.analysis import safe_dt
from engines.core.metric_contracts import annotate_payload
from engines.performance.power_engine import _moving_time_seconds, _stream_to_arrays, normalized_power

_MPS_TO_KMH = 3.6
_VALID_HR = (30, 230)
_VALID_CADENCE = (1, 220)


def _finite_mean(values: np.ndarray) -> Optional[float]:
    if values.size == 0:
        return None
    clean = values[np.isfinite(values)]
    if clean.size == 0:
        return None
    return float(np.mean(clean))


def _finite_max(values: np.ndarray) -> Optional[float]:
    clean = values[np.isfinite(values)]
    if clean.size == 0:
        return None
    return float(np.max(clean))


def _total_descent_m(altitude_m: np.ndarray) -> Optional[float]:
    if altitude_m.size < 2 or np.all(np.isnan(altitude_m)):
        return None
    diffs = np.diff(altitude_m.astype(float))
    negatives = diffs[diffs < 0]
    return float(np.nansum(np.abs(negatives))) if negatives.size else 0.0


def _speed_arrays(stream) -> np.ndarray:
    raw = getattr(stream, "speed_mps", None)
    if raw is None:
        raw = getattr(stream, "speed", None)
    if raw is None:
        return np.array([], dtype=float)
    return np.array(
        [float(v) if v is not None and np.isfinite(v) and v >= 0 else np.nan for v in raw],
        dtype=float,
    )


def _cadence_array(stream) -> np.ndarray:
    raw = getattr(stream, "cadence", None)
    if raw is None:
        return np.array([], dtype=float)
    out = []
    for v in raw:
        if v is None or not np.isfinite(v):
            out.append(np.nan)
        else:
            fv = float(v)
            out.append(fv if _VALID_CADENCE[0] <= fv <= _VALID_CADENCE[1] else np.nan)
    return np.array(out, dtype=float)


def _temperature_array(stream) -> np.ndarray:
    for attr in ("temperature_c", "temperature", "ambient_temp"):
        raw = getattr(stream, attr, None)
        if raw is not None and len(raw):
            return np.array(
                [float(v) if v is not None and np.isfinite(v) else np.nan for v in raw],
                dtype=float,
            )
    return np.array([], dtype=float)


def _round_metric(value: Optional[float], digits: int = 1) -> Optional[float]:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


def compute_activity_statistics(
    stream,
    *,
    weight_kg: float,
    ftp: Optional[float] = None,
    cp: Optional[float] = None,
    lthr: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Build the flat metrics dict consumed by the frontend ``statistics_page``.

    Returns
    -------
    dict with ``status``, ``metrics`` (the 15 headline fields), ``context`` and
    ``availability`` flags per signal family.
    """
    if weight_kg < 30:
        raise ValueError(f"weight_kg implausibly low: {weight_kg}")

    arrs = _stream_to_arrays(stream)
    power = arrs["power"]
    hr = arrs["hr"]
    t = arrs["t"]
    n = arrs["n"]

    has_power = bool(getattr(stream, "has_power", False) and n and (power > 0).any())
    has_hr = bool(getattr(stream, "has_heart_rate", False) and np.isfinite(hr).any())
    cadence = _cadence_array(stream)
    has_cadence = bool(cadence.size and np.isfinite(cadence).any())
    speed = _speed_arrays(stream)
    has_speed = bool(speed.size and np.isfinite(speed).any())
    temperature = _temperature_array(stream)
    has_temperature = bool(temperature.size and np.isfinite(temperature).any())

    altitude = getattr(stream, "altitude_m", None)
    if altitude is None:
        altitude = getattr(stream, "altitude", None)
    alt_arr = (
        np.array(altitude, dtype=float)
        if altitude is not None and len(altitude)
        else np.array([], dtype=float)
    )
    has_altitude = bool(alt_arr.size and np.isfinite(alt_arr).any())

    metrics: Dict[str, Optional[float]] = {
        "avg_power_w": None,
        "avg_power_w_kg": None,
        "np_w": None,
        "np_w_kg": None,
        "max_power_w": None,
        "work_kj": None,
        "avg_hr_bpm": None,
        "max_hr_bpm": None,
        "avg_cadence_rpm": None,
        "max_cadence_rpm": None,
        "ascent_m": None,
        "descent_m": None,
        "temperature_avg_c": None,
        "speed_avg_kmh": None,
        "moving_speed_avg_kmh": None,
    }

    if has_power:
        nonzero = power[power > 0]
        avg_p = float(np.mean(power))
        avg_moving = float(np.mean(nonzero)) if nonzero.size else avg_p
        np_val = normalized_power(power)
        metrics["avg_power_w"] = _round_metric(avg_moving, 1)
        metrics["avg_power_w_kg"] = _round_metric(avg_moving / weight_kg, 2)
        metrics["np_w"] = _round_metric(np_val, 1)
        metrics["np_w_kg"] = _round_metric(np_val / weight_kg, 2)
        metrics["max_power_w"] = _round_metric(float(np.max(power)), 1)
        dt = safe_dt(t) if t.size else 1.0
        metrics["work_kj"] = _round_metric(float(np.sum(power) * dt) / 1000.0, 1)

    if has_hr:
        metrics["avg_hr_bpm"] = _round_metric(_finite_mean(hr), 0)
        metrics["max_hr_bpm"] = _round_metric(_finite_max(hr), 0)

    if has_cadence:
        metrics["avg_cadence_rpm"] = _round_metric(_finite_mean(cadence), 0)
        metrics["max_cadence_rpm"] = _round_metric(_finite_max(cadence), 0)

    if has_altitude:
        ascent = getattr(stream, "total_ascent_m", None)
        if ascent is None:
            positives = np.diff(alt_arr.astype(float))
            positives = positives[positives > 0]
            ascent = float(np.nansum(positives)) if positives.size else 0.0
        metrics["ascent_m"] = _round_metric(float(ascent), 0)
        metrics["descent_m"] = _round_metric(_total_descent_m(alt_arr), 0)

    if has_temperature:
        metrics["temperature_avg_c"] = _round_metric(_finite_mean(temperature), 1)

    if has_speed:
        metrics["speed_avg_kmh"] = _round_metric(_finite_mean(speed) * _MPS_TO_KMH, 1)
        moving_mask = np.isfinite(speed) & (speed > 0)
        if has_power and power.size == speed.size:
            moving_mask = moving_mask & (power > 0)
        moving_speed = speed[moving_mask]
        metrics["moving_speed_avg_kmh"] = _round_metric(
            _finite_mean(moving_speed) * _MPS_TO_KMH if moving_speed.size else None,
            1,
        )

    raw_duration = (
        getattr(stream, "total_elapsed_s", 0)
        or (float(t[-1] - t[0] + safe_dt(t)) if t.size else 0)
        or n
    )
    if not np.isfinite(raw_duration) or raw_duration <= 0:
        raw_duration = float(n or 0)
    duration_s = int(raw_duration)

    payload: Dict[str, Any] = {
        "status": "success",
        "schema_version": "1.0.0",
        "metrics": metrics,
        "context": {
            "weight_kg": weight_kg,
            "ftp_w": ftp,
            "cp_w": cp,
            "lthr_bpm": lthr,
            "duration_s": duration_s,
            "moving_time_s": _moving_time_seconds(power, t) if has_power else None,
        },
        "availability": {
            "power": has_power,
            "heart_rate": has_hr,
            "cadence": has_cadence,
            "altitude": has_altitude,
            "temperature": has_temperature,
            "speed": has_speed,
        },
    }
    return annotate_payload(
        payload,
        module_name="activity_statistics",
        method="basic_ride_statistics",
        confidence=1.0 if has_power or has_hr else 0.3,
    )
