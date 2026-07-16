"""Data quality report for parsed activity streams."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

from engines.core.metric_contracts import annotate_payload
from engines.io.fit_parser import (
    QUALITY_FORWARD_FILLED,
    QUALITY_INTERPOLATED,
    QUALITY_UNRELIABLE,
    measured_signal_flags,
)

# Quality flag values mirrored from fit_parser for reporting.
_FLAG_LABELS = {
    QUALITY_INTERPOLATED: "interpolated",
    QUALITY_FORWARD_FILLED: "forward_filled",
    QUALITY_UNRELIABLE: "unreliable",
}
_NUMERIC_CONVERSION_ERRORS = (TypeError, ValueError, OverflowError)


def _series_quality(
    values: Any,
    *,
    measured: bool,
    valid_min: Optional[float] = None,
    valid_max: Optional[float] = None,
    quality_flags: Any = None,
) -> Dict[str, Any]:
    if not measured:
        return {
            "available": False,
            "coverage_pct": 0.0,
            "dropout_pct": 100.0,
            "notes": ["missing_signal"],
        }
    if values is None:
        return {
            "available": False,
            "coverage_pct": 0.0,
            "dropout_pct": 100.0,
            "notes": ["missing_signal"],
        }
    try:
        arr = np.asarray(values, dtype=float)
    except _NUMERIC_CONVERSION_ERRORS:
        return {
            "available": False,
            "coverage_pct": 0.0,
            "dropout_pct": 100.0,
            "notes": ["unreadable_signal"],
        }
    if arr.size == 0:
        return {
            "available": False,
            "coverage_pct": 0.0,
            "dropout_pct": 100.0,
            "notes": ["empty_signal"],
        }
    mask = np.isfinite(arr)
    if valid_min is not None:
        mask &= arr >= valid_min
    if valid_max is not None:
        mask &= arr <= valid_max
    if quality_flags is not None:
        try:
            quality_arr = np.asarray(quality_flags)
        except _NUMERIC_CONVERSION_ERRORS:
            quality_arr = np.array([], dtype=np.uint8)
        if quality_arr.size == arr.size:
            # Values explicitly marked unreliable by the parser are true
            # dropouts even when a placeholder/fill value is numeric.
            mask &= quality_arr != QUALITY_UNRELIABLE
    coverage = float(mask.sum() / arr.size * 100.0)
    notes = []
    if coverage < 50:
        notes.append("low_coverage")
    elif coverage < 90:
        notes.append("partial_coverage")
    return {
        "available": bool(mask.any()),
        "coverage_pct": round(coverage, 1),
        "dropout_pct": round(100.0 - coverage, 1),
        "notes": notes,
    }


def _quality_flags(flags: Any) -> Dict[str, Any]:
    if flags is None:
        return {"available": False}
    try:
        arr = np.asarray(flags)
    except _NUMERIC_CONVERSION_ERRORS:
        return {"available": False}
    if arr.size == 0:
        return {"available": False}
    counts = {str(int(k)): int(v) for k, v in zip(*np.unique(arr, return_counts=True))}
    total = max(1, arr.size)
    interpolated = int(counts.get(str(QUALITY_INTERPOLATED), 0))
    forward_filled = int(counts.get(str(QUALITY_FORWARD_FILLED), 0))
    unreliable = int(counts.get(str(QUALITY_UNRELIABLE), 0))
    return {
        "available": True,
        "counts": counts,
        "interpolated_pct": round(interpolated / total * 100.0, 1),
        "forward_filled_pct": round(forward_filled / total * 100.0, 1),
        "unreliable_pct": round(unreliable / total * 100.0, 1),
        "flags": {label: int(counts.get(str(code), 0)) for code, label in _FLAG_LABELS.items()},
    }


def _coerce_quality_stream(stream: Any) -> Any:
    """Accept ActivityStreamEnhanced or a minimal channel dict for quality reports."""
    if not isinstance(stream, dict):
        return stream

    class _ChannelStream:
        pass

    obj = _ChannelStream()
    power = stream.get("power")
    heart_rate = stream.get("heart_rate")
    cadence = stream.get("cadence")
    obj.power = np.asarray(power, dtype=float) if power is not None else np.array([], dtype=float)
    obj.heart_rate = (
        np.asarray(heart_rate, dtype=float) if heart_rate is not None else np.array([], dtype=float)
    )
    obj.cadence = (
        np.asarray(cadence, dtype=float) if cadence is not None else np.array([], dtype=float)
    )
    obj.speed_mps = np.array([], dtype=float)
    obj.distance_m = np.array([], dtype=float)
    obj.altitude_m = np.array([], dtype=float)
    obj.temperature_c = np.array([], dtype=float)
    obj.respiration_rate = np.array([], dtype=float)
    obj.left_right_balance = np.array([], dtype=float)
    obj.lat = np.array([], dtype=float)
    obj.lon = np.array([], dtype=float)
    obj.quality_power = stream.get("quality_power")
    obj.quality_hr = stream.get("quality_hr")
    obj.gap_summary = stream.get("gap_summary", {}) or {}
    obj.has_power = bool(obj.power.size and np.any(np.isfinite(obj.power) & (obj.power > 0)))
    obj.has_heart_rate = bool(
        obj.heart_rate.size and np.any(np.isfinite(obj.heart_rate) & (obj.heart_rate > 0))
    )
    obj.has_speed = False
    obj.has_distance = False
    obj.has_altitude = False
    obj.has_rr = False
    obj.has_cycling_dynamics = False
    obj.has_respiration = False
    return obj


def build_data_quality_report(stream: Any) -> Dict[str, Any]:
    """Return signal coverage, dropout and warning information."""
    stream = _coerce_quality_stream(stream)
    measured = measured_signal_flags(stream)
    signals = {
        # Zero watts are a valid measured state (coasting/stopping), not a
        # sensor dropout. Missing/unreliable samples are represented by NaN or
        # parser quality flags, so coverage must include finite zero values.
        "power": _series_quality(
            getattr(stream, "power", None),
            measured=measured["power"],
            valid_min=0,
            quality_flags=getattr(stream, "quality_power", None),
        ),
        "heart_rate": _series_quality(
            getattr(stream, "heart_rate", None),
            measured=measured["heart_rate"],
            valid_min=30,
            valid_max=240,
            quality_flags=getattr(stream, "quality_hr", None),
        ),
        # Zero cadence is valid while coasting. As for power, actual gaps are
        # represented separately rather than inferred from the numeric value.
        "cadence": _series_quality(
            getattr(stream, "cadence", None),
            measured=measured["cadence"],
            valid_min=0,
            valid_max=250,
        ),
        "speed": _series_quality(
            getattr(stream, "speed_mps", None),
            measured=measured["speed"],
            valid_min=0.0,
        ),
        "distance": _series_quality(
            getattr(stream, "distance_m", None),
            measured=measured["distance"],
            valid_min=0.0,
        ),
        "altitude": _series_quality(
            getattr(stream, "altitude_m", None),
            measured=measured["altitude"],
        ),
        "temperature": _series_quality(
            getattr(stream, "temperature_c", None),
            measured=measured["temperature"],
            valid_min=-30,
            valid_max=60,
        ),
        "respiration": _series_quality(
            getattr(stream, "respiration_rate", None),
            measured=measured["respiration"],
            valid_min=1,
            valid_max=80,
        ),
        "left_right_balance": _series_quality(
            getattr(stream, "left_right_balance", None),
            measured=bool(np.any(np.isfinite(getattr(stream, "left_right_balance", [])))),
            valid_min=0,
            valid_max=100,
        ),
    }
    flag_report = {
        "power": _quality_flags(getattr(stream, "quality_power", None)),
        "heart_rate": _quality_flags(getattr(stream, "quality_hr", None)),
    }
    available = [name for name, is_measured in measured.items() if is_measured and name != "gps"]
    if measured.get("gps"):
        available.extend(["gps", "latitude", "longitude"])
    warnings = []
    for name, info in signals.items():
        if info.get("available") and info.get("coverage_pct", 0) < 90:
            warnings.append(f"{name}_partial_coverage")
    for channel, info in flag_report.items():
        if not info.get("available"):
            continue
        if info.get("unreliable_pct", 0) > 0:
            warnings.append(f"{channel}_unreliable")
        if info.get("forward_filled_pct", 0) > 0:
            warnings.append(f"{channel}_forward_filled")
        if info.get("interpolated_pct", 0) > 0:
            warnings.append(f"{channel}_interpolated")
    score = 0.0
    weights = {
        "power": 0.35,
        "heart_rate": 0.2,
        "cadence": 0.1,
        "speed": 0.1,
        "distance": 0.05,
        "altitude": 0.1,
        "temperature": 0.05,
        "respiration": 0.03,
        "left_right_balance": 0.02,
    }
    for key, weight in weights.items():
        score += weight * (signals[key].get("coverage_pct", 0.0) / 100.0)
    payload = {
        "status": "success",
        "schema_version": "1.0.0",
        "overall_score": round(max(0.0, min(1.0, score)), 3),
        "available_signals": available,
        "measured_signals": measured,
        "signals": signals,
        "quality_flags": flag_report,
        "warnings": warnings,
        "gap_summary": getattr(stream, "gap_summary", {}) or {},
    }
    return annotate_payload(
        payload,
        module_name="data_quality_report",
        method="signal_coverage",
        confidence=1.0,
    )
