"""Simple route/segment analysis from activity streams."""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from engines.core.metric_contracts import annotate_payload


def detect_climb_segments(stream: Any, *, min_gain_m: float = 30.0, min_distance_m: float = 500.0) -> Dict[str, Any]:
    altitude = np.asarray(getattr(stream, "altitude_m", []), dtype=float)
    distance = np.asarray(getattr(stream, "distance_m", []), dtype=float)
    if altitude.size < 2 or distance.size != altitude.size or np.all(~np.isfinite(altitude)):
        return {"status": "skipped", "reason": "missing_altitude_or_distance", "segments": []}
    segments: List[Dict[str, Any]] = []
    start = None
    for i in range(1, altitude.size):
        if np.isfinite(altitude[i]) and np.isfinite(altitude[i - 1]) and altitude[i] > altitude[i - 1]:
            if start is None:
                start = i - 1
        elif start is not None:
            _append_segment(segments, start, i - 1, altitude, distance, min_gain_m, min_distance_m)
            start = None
    if start is not None:
        _append_segment(segments, start, altitude.size - 1, altitude, distance, min_gain_m, min_distance_m)
    payload = {"status": "success" if segments else "skipped", "segments": segments}
    return annotate_payload(payload, module_name="segment_engine", method="climb_detection", confidence=0.65)


def _append_segment(out: List[Dict[str, Any]], start: int, end: int, altitude: np.ndarray, distance: np.ndarray, min_gain: float, min_dist: float) -> None:
    gain = float(altitude[end] - altitude[start])
    dist = float(distance[end] - distance[start])
    if gain >= min_gain and dist >= min_dist:
        out.append({"start_index": start, "end_index": end, "distance_m": round(dist, 1), "elevation_gain_m": round(gain, 1), "avg_grade_pct": round(gain / dist * 100.0, 1) if dist > 0 else None})


def compare_segments(segment_history: List[Dict[str, Any]], new_segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    comparisons = []
    for i, seg in enumerate(new_segments):
        best = None
        for old in segment_history:
            if abs(float(old.get("distance_m", 0)) - float(seg.get("distance_m", 0))) <= max(100.0, float(seg.get("distance_m", 0)) * 0.1):
                best = old
                break
        comparisons.append({"segment_index": i, "matched": best is not None, "previous": best, "current": seg})
    return {"status": "success", "comparisons": comparisons}
