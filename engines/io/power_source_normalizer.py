"""Power-source drift/offset detection and normalization recommendations.

This layer protects downstream CP/W′/MMP/twin metrics when the athlete mixes
indoor trainers and outdoor power meters.  It does not rewrite history; it
produces auditable offset estimates and confidence so callers can decide whether
to normalize curves before profiling.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

_DURATIONS = (5, 10, 30, 60, 120, 300, 600, 1200, 1800, 3600)


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(out) or np.isinf(out):
        return None
    return out


def _mmp(activity: Dict[str, Any]) -> Dict[int, float]:
    raw = activity.get("mmp") or activity.get("mmp_curve") or activity.get("curve") or activity.get("power_curve") or {}
    out: Dict[int, float] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                dur = int(float(k))
            except (TypeError, ValueError):
                continue
            val = _num(v.get("power_w") if isinstance(v, dict) else v)
            if val is not None and val > 0:
                out[dur] = val
    return out


def _source_id(activity: Dict[str, Any]) -> str:
    for key in ("power_source_id", "source_id", "device_id", "trainer_id"):
        if activity.get(key):
            return str(activity[key])
    modality = str(activity.get("modality") or activity.get("discipline") or "unknown")
    device = str(activity.get("device_name") or activity.get("source") or "unknown")
    return f"{modality}:{device}".lower()


def _source_kind(activity: Dict[str, Any]) -> str:
    text = " ".join(str(activity.get(k) or "") for k in ("source", "device_name", "modality", "power_source_id")).lower()
    if any(x in text for x in ("trainer", "trainer_device", "indoor_trainer_a", "neo", "indoor", "virtual platform", "rullo")):
        return "indoor_trainer"
    if any(x in text for x in ("pedal", "crank", "spider", "outdoor_meter_a", "crank_meter", "head_unit", "power meter", "outdoor")):
        return "outdoor_power_meter"
    return "unknown"


def _source_signature(activities: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_source: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for activity in activities:
        if isinstance(activity, dict):
            by_source[_source_id(activity)].append(activity)
    summaries: Dict[str, Any] = {}
    for sid, acts in by_source.items():
        duration_values: Dict[int, List[float]] = defaultdict(list)
        kinds = defaultdict(int)
        for act in acts:
            kinds[_source_kind(act)] += 1
            mmp = _mmp(act)
            for dur in _DURATIONS:
                if dur in mmp:
                    duration_values[dur].append(mmp[dur])
        med_curve = {dur: round(float(median(vals)), 1) for dur, vals in duration_values.items() if vals}
        summaries[sid] = {
            "source_id": sid,
            "source_kind": max(kinds.items(), key=lambda x: x[1])[0] if kinds else "unknown",
            "n_activities": len(acts),
            "median_mmp": med_curve,
        }
    return summaries


def _pair_offset(a: Dict[str, float], b: Dict[str, float]) -> Tuple[Optional[float], int]:
    ratios = []
    for dur in _DURATIONS:
        va = _num(a.get(dur) or a.get(str(dur)))
        vb = _num(b.get(dur) or b.get(str(dur)))
        if va and vb and va > 50 and vb > 50:
            ratios.append((vb / va - 1.0) * 100.0)
    if len(ratios) < 2:
        return None, len(ratios)
    return float(median(ratios)), len(ratios)


def analyze_power_source_offsets(
    activities: List[Dict[str, Any]],
    *,
    baseline_source_id: Optional[str] = None,
    warning_threshold_pct: float = 3.0,
    severe_threshold_pct: float = 6.0,
) -> Dict[str, Any]:
    """Detect systematic power offsets between sources from MMP signatures."""
    if not isinstance(activities, list) or not activities:
        return {"status": "insufficient_data", "reason": "NO_ACTIVITIES", "confidence_score": 0.0, "source_summaries": {}, "warnings": []}
    summaries = _source_signature(activities)
    if len(summaries) < 2:
        return {
            "status": "insufficient_data",
            "reason": "ONE_SOURCE_ONLY",
            "confidence_score": 0.25,
            "source_summaries": summaries,
            "warnings": [{"severity": "low", "type": "one_power_source", "message": "Only one power source detected; cross-source offset cannot be estimated."}],
        }
    if baseline_source_id is None or baseline_source_id not in summaries:
        baseline_source_id = max(summaries.values(), key=lambda s: (s["n_activities"], len(s["median_mmp"]))) ["source_id"]
    baseline_curve = summaries[baseline_source_id]["median_mmp"]
    pairwise: List[Dict[str, Any]] = []
    recommendations: Dict[str, Any] = {}
    warnings: List[Dict[str, Any]] = []
    evidence = 0
    for sid, summary in summaries.items():
        if sid == baseline_source_id:
            recommendations[sid] = {"normalization_factor": 1.0, "offset_vs_baseline_pct": 0.0, "action": "baseline"}
            continue
        offset, n = _pair_offset(baseline_curve, summary["median_mmp"])
        evidence += n
        if offset is None:
            recommendations[sid] = {"normalization_factor": None, "offset_vs_baseline_pct": None, "action": "insufficient_overlap"}
            continue
        factor = 1.0 / (1.0 + offset / 100.0)
        severity = "high" if abs(offset) >= severe_threshold_pct else "medium" if abs(offset) >= warning_threshold_pct else "low"
        action = "normalize_before_profile" if abs(offset) >= warning_threshold_pct else "monitor"
        pairwise.append({
            "baseline_source_id": baseline_source_id,
            "comparison_source_id": sid,
            "offset_vs_baseline_pct": round(offset, 2),
            "overlap_durations": n,
            "severity": severity,
        })
        recommendations[sid] = {
            "normalization_factor": round(factor, 5),
            "offset_vs_baseline_pct": round(offset, 2),
            "action": action,
            "interpretation": "multiply this source power by normalization_factor to align to baseline",
        }
        if abs(offset) >= warning_threshold_pct:
            warnings.append({
                "severity": severity,
                "type": "power_source_offset",
                "source_id": sid,
                "message": f"Power source {sid} differs from baseline by {offset:+.1f}%; downstream CP/MMP may be biased if mixed unnormalized.",
            })
    confidence = min(0.9, 0.25 + 0.08 * evidence + 0.05 * len(activities))
    return {
        "status": "success",
        "schema_version": "power_source_normalization.v1",
        "baseline_source_id": baseline_source_id,
        "confidence_score": round(confidence, 2),
        "source_summaries": summaries,
        "pairwise_offsets": pairwise,
        "normalization_recommendations": recommendations,
        "warnings": warnings,
    }
