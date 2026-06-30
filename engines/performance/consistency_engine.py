"""Training consistency metrics — Eddington numbers and segment history helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from engines.core.metric_contracts import annotate_payload


def calculate_eddington_number(
    values: Sequence[float],
    *,
    threshold: Optional[float] = None,
    unit: str = "duration_h",
) -> Dict[str, Any]:
    """Eddington number: how many activities exceed a given threshold.

    Classic definition: the largest integer N such that at least N activities
    were at least N units long (hours, km, TSS, etc.).
    """
    clean = sorted((float(v) for v in values if v is not None and float(v) > 0), reverse=True)
    if not clean:
        return annotate_payload(
            {"status": "insufficient_data", "n_activities": 0},
            module_name="consistency_engine",
            method="eddington_number",
            confidence=0.0,
            limitations=["Requires at least one positive activity value."],
        )

    eddington = 0
    for i, val in enumerate(clean, start=1):
        if val >= i:
            eddington = i
        else:
            break

    effective_threshold = float(threshold) if threshold is not None else float(eddington)
    above_threshold = sum(1 for v in clean if v >= effective_threshold)

    if eddington >= 20:
        band = "elite_consistency"
    elif eddington >= 10:
        band = "strong_consistency"
    elif eddington >= 5:
        band = "developing_consistency"
    else:
        band = "low_consistency"

    return annotate_payload(
        {
            "status": "success",
            "eddington_number": eddington,
            "threshold": round(effective_threshold, 2),
            "activities_above_threshold": above_threshold,
            "n_activities": len(clean),
            "consistency_band": band,
            "unit": unit,
            "distribution": {
                "max": round(clean[0], 2),
                "median": round(float(np.median(clean)), 2),
                "mean": round(float(np.mean(clean)), 2),
            },
        },
        module_name="consistency_engine",
        method="eddington_number",
        confidence=0.7 if len(clean) >= 8 else 0.45,
        limitations=["Eddington number is sensitive to outlier long sessions."],
    )


def build_segment_history(
    segment_history: List[Dict[str, Any]],
    *,
    metric_key: str = "elapsed_s",
) -> Dict[str, Any]:
    """Aggregate recurring segment attempts for charting."""
    if not segment_history:
        return annotate_payload(
            {"status": "insufficient_data", "segments": []},
            module_name="consistency_engine",
            method="segment_history",
            confidence=0.0,
        )

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in segment_history:
        label = str(row.get("segment_id") or row.get("name") or row.get("distance_m") or "segment")
        grouped.setdefault(label, []).append(row)

    segments: List[Dict[str, Any]] = []
    for label, attempts in grouped.items():
        metrics = [float(a.get(metric_key, 0) or 0) for a in attempts if a.get(metric_key) is not None]
        powers = [float(a.get("avg_power_w", 0) or 0) for a in attempts if a.get("avg_power_w")]
        segments.append({
            "segment_id": label,
            "attempts": len(attempts),
            "best": round(min(metrics), 1) if metrics and metric_key.endswith("_s") else round(max(metrics), 1) if metrics else None,
            "latest": round(metrics[-1], 1) if metrics else None,
            "mean": round(float(np.mean(metrics)), 1) if metrics else None,
            "best_power_w": round(max(powers), 0) if powers else None,
            "history": attempts[-12:],
        })

    return annotate_payload(
        {"status": "success", "segments": segments, "metric_key": metric_key},
        module_name="consistency_engine",
        method="segment_history",
        confidence=0.65,
    )
