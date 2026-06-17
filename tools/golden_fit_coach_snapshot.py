"""Build deterministic coach-pipeline snapshots for golden FIT regression tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from engines.core.analysis import safe_dt
from engines.io.activity_intelligence import compute_best_efforts
from engines.io.data_quality_report import build_data_quality_report
from engines.io.fit_parser import measured_signal_flags
from engines.io.workout_summary import build_workout_summary
from engines.performance.power_engine import _stream_to_arrays

GOLDEN_WEIGHT_KG = 75.0
GOLDEN_FTP_W = 250.0
GOLDEN_LTHR_BPM = 160
MMP_DURATIONS_S = [1, 5, 60, 300, 1200]


def _effort_value(efforts: list[dict[str, Any]], duration_s: int) -> Optional[float]:
    for item in efforts:
        if int(item.get("duration_s", -1)) == duration_s:
            return float(item["value"])
    return None


def _rr_interval_count(stream: Any) -> int:
    total = 0
    for bucket in getattr(stream, "rr_intervals", []) or []:
        total += len(bucket or [])
    return total


def build_coach_golden_snapshot(fit_path: Path, stream: Any) -> Dict[str, Any]:
    """Serialize coach-facing metrics with fixed athlete context for golden tests."""
    file_hash = hashlib.sha256(fit_path.read_bytes()).hexdigest()
    measured = measured_signal_flags(stream)
    quality = build_data_quality_report(stream)
    arrs = _stream_to_arrays(stream)
    power = arrs.get("power", np.array([], dtype=float))
    dt = safe_dt(arrs.get("t", np.array([], dtype=float))) if arrs.get("n", 0) else 1.0
    efforts = compute_best_efforts(power, dt_s=dt, weight_kg=GOLDEN_WEIGHT_KG, durations_s=MMP_DURATIONS_S)

    coach: Dict[str, Any] = {
        "file_hash": file_hash,
        "measured_signals": measured,
        "quality_flags": {
            "power": quality.get("quality_flags", {}).get("power", {}),
            "heart_rate": quality.get("quality_flags", {}).get("heart_rate", {}),
        },
        "rr_interval_count": _rr_interval_count(stream),
        "laps": [
            {
                "lap_index": lap.get("lap_index"),
                "duration_s": lap.get("duration_s"),
                "avg_power_w": lap.get("avg_power_w"),
                "start_time": lap.get("start_time"),
            }
            for lap in (getattr(stream, "laps", None) or [])
        ],
    }

    summary = build_workout_summary(
        stream,
        weight_kg=GOLDEN_WEIGHT_KG,
        ftp=GOLDEN_FTP_W,
        lthr=GOLDEN_LTHR_BPM,
    )

    if measured.get("power"):
        headline = summary.get("headline", {})
        coach["power"] = {
            "normalized_power": headline.get("normalized_power"),
            "intensity_factor": headline.get("intensity_factor"),
            "tss": headline.get("tss"),
            "mmp_w": {
                str(duration): _effort_value(efforts.get("efforts", []), duration)
                for duration in MMP_DURATIONS_S
            },
        }

    hrv_section = summary.get("sections", {}).get("hrv", {}) or {}
    coach["hrv"] = {
        "status": hrv_section.get("status"),
        "window_count": len(hrv_section.get("windows", []) or []),
        "dfa_available": bool(hrv_section.get("status") == "success"),
    }
    return coach
