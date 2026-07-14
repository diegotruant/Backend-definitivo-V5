"""Canonical FIT parse report for API consumers and persistence layers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from engines.core.metric_contracts import annotate_payload
from engines.io.data_quality_report import build_data_quality_report
from engines.io.fit_parser import FIT_PARSER_VERSION


_NUMERIC_CONVERSION_ERRORS = (TypeError, ValueError, OverflowError)


def _series_or_none(values: Any, *, n_samples: int) -> Optional[List[float]]:
    if values is None:
        return None
    try:
        arr = np.asarray(values, dtype=float)[:n_samples]
    except _NUMERIC_CONVERSION_ERRORS:
        return None
    if arr.size == 0:
        return None
    return [float(v) for v in arr]


def build_fit_parse_report(
    *,
    stream: Any,
    file_id: str,
    file_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the full parse contract for a parsed activity stream."""
    n_samples = int(getattr(stream, "n_samples", 0) or 0)
    quality = build_data_quality_report(stream)
    provenance = getattr(stream, "data_provenance", None) or {
        "source": "unknown",
        "synthetic_signals": [],
        "measured_signals": quality.get("available_signals", []),
    }
    warnings: list[str] = list(quality.get("warnings", []))
    if provenance.get("synthetic_signals"):
        warnings.append("contains_synthetic_signals")

    payload: Dict[str, Any] = {
        "status": "success",
        "activity_id": file_id,
        "file_hash": file_hash,
        "parser_version": FIT_PARSER_VERSION,
        "device": getattr(stream, "device_name", None),
        "start_time": stream.start_time.isoformat() if getattr(stream, "start_time", None) else None,
        "duration_s": int(getattr(stream, "total_elapsed_s", 0) or n_samples),
        "available_signals": quality.get("available_signals", []),
        "data_provenance": provenance,
        "streams": {
            "time_s": _series_or_none(getattr(stream, "elapsed_s", None), n_samples=n_samples),
            "power_w": _series_or_none(getattr(stream, "power", None), n_samples=n_samples),
            "heart_rate_bpm": _series_or_none(getattr(stream, "heart_rate", None), n_samples=n_samples),
            "cadence_rpm": _series_or_none(getattr(stream, "cadence", None), n_samples=n_samples),
            "speed_mps": _series_or_none(getattr(stream, "speed_mps", None), n_samples=n_samples),
            "altitude_m": _series_or_none(getattr(stream, "altitude_m", None), n_samples=n_samples),
            "lat": _series_or_none(getattr(stream, "lat", None), n_samples=n_samples),
            "lon": _series_or_none(getattr(stream, "lon", None), n_samples=n_samples),
        },
        "quality": {
            "coverage": quality.get("signals", {}),
            "gap_summary": getattr(stream, "gap_summary", {}),
            "quality_flags": quality.get("quality_flags", {}),
            "overall_score": quality.get("overall_score"),
        },
        "laps": list(getattr(stream, "laps", []) or []),
        "warnings": warnings,
    }
    return annotate_payload(payload, module_name="fit_parser", method="parse_fit_file_enhanced")
