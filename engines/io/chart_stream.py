"""Rebuild ActivityStreamEnhanced from JSON chart payloads (meta / frontend)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from engines.io.fit_parser import ActivityStreamEnhanced


def _as_float_array(values: Optional[List[Any]], length: int, *, default: float = 0.0) -> np.ndarray:
    if not values:
        return np.full(length, default, dtype=np.float32)
    arr = np.asarray(values, dtype=np.float32)
    if len(arr) < length:
        pad = np.full(length - len(arr), default, dtype=np.float32)
        arr = np.concatenate([arr, pad])
    return arr[:length]


def stream_from_chart_payload(payload: Dict[str, Any]) -> ActivityStreamEnhanced:
    """Coerce a serializable payload into an activity stream for chart builders."""
    nested = payload.get("stream_payload") or payload.get("stream") or {}
    if not isinstance(nested, dict):
        nested = {}

    power = payload.get("power") or nested.get("power")
    if power is None:
        raise ValueError("chart payload requires power[] or stream_payload.power[]")

    n = len(power)
    if n < 1:
        raise ValueError("power stream must contain at least one sample")

    stream = ActivityStreamEnhanced(n)
    stream.power = _as_float_array(power, n)
    elapsed = payload.get("elapsed_s") or nested.get("elapsed_s")
    if elapsed is None:
        stream.elapsed_s = np.arange(n, dtype=np.float32)
    else:
        stream.elapsed_s = _as_float_array(elapsed, n)

    hr = payload.get("heart_rate") or nested.get("heart_rate")
    if hr is not None:
        stream.heart_rate = _as_float_array(hr, n)

    cadence = payload.get("cadence") or nested.get("cadence")
    if cadence is not None:
        stream.cadence = _as_float_array(cadence, n)

    alt = payload.get("altitude_m") or nested.get("altitude_m")
    if alt is not None:
        stream.altitude_m = _as_float_array(alt, n, default=np.nan)

    speed = payload.get("speed_mps") or nested.get("speed_mps")
    if speed is not None:
        stream.speed_mps = _as_float_array(speed, n, default=np.nan)

    temp = payload.get("temperature_c") or nested.get("temperature_c")
    if temp is not None:
        stream.temperature_c = _as_float_array(temp, n, default=np.nan)

    for attr, key in (
        ("respiration_rate", "respiration_rate"),
        ("core_body_temp", "core_temperature"),
        ("skin_temp", "skin_temperature"),
        ("left_right_balance", "left_right_balance"),
    ):
        values = payload.get(key) or nested.get(key)
        if values is not None and hasattr(stream, attr):
            setattr(stream, attr, _as_float_array(values, n, default=np.nan))

    return stream
