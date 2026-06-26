"""Neuromuscular sprint profile.

Extracts sprint-oriented metrics that CP/W′/VLaMax do not represent well:
Pmax, cadence at peak, torque proxy, sprint repeatability and L/R balance during
high-power efforts.  Works from the already parsed ActivityStream, so it reuses
FIT support for cadence, balance and cycling dynamics without re-reading files.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def _arr(stream: Any, name: str) -> np.ndarray:
    value = getattr(stream, name, None)
    if value is None:
        return np.array([], dtype=float)
    return np.asarray(value, dtype=float)


def _finite(values: np.ndarray) -> np.ndarray:
    return values[np.isfinite(values)]


def _mean(values: np.ndarray) -> Optional[float]:
    valid = _finite(values)
    if valid.size == 0:
        return None
    return float(np.mean(valid))


def _rolling_best(power: np.ndarray, seconds: int) -> Tuple[Optional[float], Optional[int]]:
    if power.size < seconds or seconds <= 0:
        return None, None
    clean = np.where(np.isfinite(power), power, 0.0)
    if seconds == 1:
        idx = int(np.argmax(clean))
        return float(clean[idx]), idx
    kernel = np.ones(seconds, dtype=float) / seconds
    roll = np.convolve(clean, kernel, mode="valid")
    idx = int(np.argmax(roll))
    return float(roll[idx]), idx


def _detect_sprints(
    power: np.ndarray,
    cadence: np.ndarray,
    threshold_w: float,
    min_gap_s: int = 45,
) -> List[Dict[str, Any]]:
    if power.size == 0:
        return []
    candidates = np.where(np.isfinite(power) & (power >= threshold_w))[0]
    if candidates.size == 0:
        return []

    clusters = _cluster_candidates(candidates)
    sprints: List[Dict[str, Any]] = []
    last_peak = -10**9
    for start, end in clusters:
        sprint = _sprint_from_cluster(power, cadence, start, end)
        if sprint is None:
            continue
        peak_idx = int(sprint["peak_idx"])
        if peak_idx - last_peak < min_gap_s:
            if sprints and sprint["peak_power_w"] > sprints[-1]["peak_power_w"]:
                sprints[-1].update(sprint)
                last_peak = peak_idx
            continue
        sprints.append(sprint | {"sprint_id": f"sprint_{len(sprints) + 1}"})
        last_peak = peak_idx
    return sprints[:30]


def _cluster_candidates(candidates: np.ndarray) -> List[Tuple[int, int]]:
    clusters: List[Tuple[int, int]] = []
    start = prev = int(candidates[0])
    for idx_raw in candidates[1:]:
        idx = int(idx_raw)
        if idx - prev <= 3:
            prev = idx
        else:
            clusters.append((start, prev))
            start = prev = idx
    clusters.append((start, prev))
    return clusters


def _sprint_from_cluster(
    power: np.ndarray,
    cadence: np.ndarray,
    start: int,
    end: int,
) -> Optional[Dict[str, Any]]:
    pad_start = max(0, start - 2)
    pad_end = min(power.size, end + 3)
    seg = power[pad_start:pad_end]
    if seg.size == 0:
        return None
    local_peak_offset = int(np.nanargmax(seg))
    peak_idx = pad_start + local_peak_offset
    cseg = cadence[max(0, peak_idx - 2): min(cadence.size, peak_idx + 3)] if cadence.size else np.array([])
    return {
        "start_s": int(pad_start),
        "end_s": int(pad_end),
        "duration_s": int(max(1, pad_end - pad_start)),
        "peak_idx": int(peak_idx),
        "peak_power_w": round(float(power[peak_idx]), 1),
        "mean_power_w": round(float(np.nanmean(seg)), 1),
        "cadence_at_peak_rpm": round(float(np.nanmean(cseg)), 1)
        if cseg.size and np.isfinite(cseg).any()
        else None,
    }


def _torque_nm(power_w: float, cadence_rpm: Optional[float]) -> Optional[float]:
    if cadence_rpm is None or cadence_rpm <= 0:
        return None
    omega = cadence_rpm * 2.0 * np.pi / 60.0
    return float(power_w / omega) if omega > 0 else None


def _insufficient_power(power: np.ndarray) -> Optional[Dict[str, Any]]:
    if power.size > 0 and np.isfinite(power).any() and np.nanmax(power) > 0:
        return None
    return {
        "status": "insufficient_data",
        "reason": "NO_POWER",
        "confidence_score": 0.0,
        "warnings": [
            {"severity": "high", "type": "missing_power", "message": "No usable power samples."}
        ],
    }


def _best_power(clean_power: np.ndarray) -> Dict[str, Tuple[Optional[float], Optional[int]]]:
    return {
        "1s": _rolling_best(clean_power, 1),
        "5s": _rolling_best(clean_power, 5),
        "10s": _rolling_best(clean_power, 10),
        "15s": _rolling_best(clean_power, 15),
        "30s": _rolling_best(clean_power, 30),
    }


def _cadence_at_peak(cadence: np.ndarray, peak_idx: int) -> Optional[float]:
    if cadence.size == 0:
        return None
    window = cadence[max(0, peak_idx - 2): min(cadence.size, peak_idx + 3)]
    return _mean(window)


def _sprint_threshold(
    clean_power: np.ndarray,
    p5: Optional[float],
    sprint_threshold_w: Optional[float],
) -> float:
    if sprint_threshold_w is not None:
        return float(sprint_threshold_w)
    return max(600.0, float(np.nanpercentile(clean_power, 99)) * 0.82, float(p5 or 0) * 0.85)


def _repeatability_and_fatigue(sprints: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    top_peaks = sorted([s["peak_power_w"] for s in sprints], reverse=True)
    if len(top_peaks) >= 3 and top_peaks[0] > 0:
        repeatability = float(np.mean(top_peaks[1:3]) / top_peaks[0] * 100.0)
    elif len(top_peaks) == 2 and top_peaks[0] > 0:
        repeatability = float(top_peaks[1] / top_peaks[0] * 100.0)
    else:
        repeatability = None

    if len(sprints) >= 2 and sprints[0]["peak_power_w"] > 0:
        fatigue_index = max(
            0.0,
            (sprints[0]["peak_power_w"] - sprints[-1]["peak_power_w"])
            / sprints[0]["peak_power_w"]
            * 100.0,
        )
    else:
        fatigue_index = None
    return repeatability, fatigue_index


def _resolve_weight(weight_kg: Optional[float]) -> Optional[float]:
    if weight_kg is None:
        return None
    try:
        weight = float(weight_kg)
    except (TypeError, ValueError):
        return None
    return weight if weight > 0 else None


def _balance_at_peak(balance: np.ndarray, peak_idx: int) -> Optional[float]:
    if balance.size == 0:
        return None
    bseg = balance[max(0, peak_idx - 5): min(balance.size, peak_idx + 6)]
    return _mean(bseg)


def _phenotype_from_pmax(pmax_wkg: Optional[float]) -> str:
    if pmax_wkg is not None and pmax_wkg >= 14:
        return "neuromuscular_sprinter"
    if pmax_wkg is not None and pmax_wkg >= 10:
        return "mixed_power"
    return "endurance_limited_sprint"


def _profile_warnings(
    cadence_peak: Optional[float],
    repeatability: Optional[float],
    resolved_weight: Optional[float],
) -> List[Dict[str, Any]]:
    warnings: List[Dict[str, Any]] = []
    if cadence_peak is None:
        warnings.append({
            "severity": "medium",
            "type": "missing_cadence",
            "message": "Cadence missing: torque and optimal cadence confidence reduced.",
        })
    if repeatability is None:
        warnings.append({
            "severity": "low",
            "type": "few_sprints",
            "message": "Few repeat sprint candidates detected; repeatability is uncertain.",
        })
    if resolved_weight is None:
        warnings.append({
            "severity": "medium",
            "type": "missing_body_weight",
            "message": "Body weight missing: W/kg metrics are not computed.",
        })
    return warnings


def _confidence(
    cadence_peak: Optional[float],
    n_sprints: int,
    left_balance_peak: Optional[float],
) -> float:
    value = 0.45
    value += 0.2 if cadence_peak is not None else 0.0
    value += 0.2 if n_sprints >= 2 else 0.0
    value += 0.1 if left_balance_peak is not None else 0.0
    return round(min(0.95, value), 2)


def _best_power_payload(best: Dict[str, Tuple[Optional[float], Optional[int]]]) -> Dict[str, Optional[float]]:
    return {
        "1s_w": round(best["1s"][0], 1) if best["1s"][0] is not None else None,
        "5s_w": round(best["5s"][0], 1) if best["5s"][0] is not None else None,
        "10s_w": round(best["10s"][0], 1) if best["10s"][0] is not None else None,
        "15s_w": round(best["15s"][0], 1) if best["15s"][0] is not None else None,
        "30s_w": round(best["30s"][0], 1) if best["30s"][0] is not None else None,
    }


def analyze_neuromuscular_profile(
    stream: Any,
    *,
    weight_kg: Optional[float] = None,
    sprint_threshold_w: Optional[float] = None,
) -> Dict[str, Any]:
    """Return a JSON-safe neuromuscular sprint profile from an ActivityStream."""
    power = _arr(stream, "power")
    insufficient = _insufficient_power(power)
    if insufficient is not None:
        return insufficient

    cadence = _arr(stream, "cadence")
    balance = _arr(stream, "left_right_balance")
    clean_power = np.where(np.isfinite(power), power, 0.0)
    best = _best_power(clean_power)
    p1, p1_idx = best["1s"]
    p5, _ = best["5s"]
    peak_idx = int(p1_idx or 0)

    cadence_peak = _cadence_at_peak(cadence, peak_idx)
    threshold = _sprint_threshold(clean_power, p5, sprint_threshold_w)
    sprints = _detect_sprints(clean_power, cadence, threshold_w=threshold)
    repeatability, fatigue_index = _repeatability_and_fatigue(sprints)

    pmax_w = float(p1 or 0.0)
    resolved_weight = _resolve_weight(weight_kg)
    pmax_wkg = (pmax_w / resolved_weight) if resolved_weight else None
    torque = _torque_nm(pmax_w, cadence_peak)
    left_balance_peak = _balance_at_peak(balance, peak_idx)
    phenotype = _phenotype_from_pmax(pmax_wkg)
    warnings = _profile_warnings(cadence_peak, repeatability, resolved_weight)

    return {
        "status": "success",
        "schema_version": "neuromuscular_profile.v1",
        "confidence_score": _confidence(cadence_peak, len(sprints), left_balance_peak),
        "summary": {
            "phenotype": phenotype,
            "pmax_w": round(pmax_w, 1),
            "pmax_wkg": round(pmax_wkg, 2) if pmax_wkg is not None else None,
            "cadence_at_pmax_rpm": round(cadence_peak, 1) if cadence_peak is not None else None,
            "torque_at_pmax_nm": round(torque, 1) if torque is not None else None,
            "repeatability_score": round(repeatability, 1) if repeatability is not None else None,
            "fatigue_index_pct": round(fatigue_index, 1) if fatigue_index is not None else None,
            "left_balance_at_pmax_pct": round(left_balance_peak, 1) if left_balance_peak is not None else None,
            "right_balance_at_pmax_pct": round(100.0 - left_balance_peak, 1) if left_balance_peak is not None else None,
            "n_sprints_detected": len(sprints),
        },
        "best_power": _best_power_payload(best),
        "sprint_candidates": sprints,
        "recommendations": _recommendations(pmax_wkg, repeatability, cadence_peak),
        "warnings": warnings,
    }


def _recommendations(
    pmax_wkg: Optional[float],
    repeatability: Optional[float],
    cadence_peak: Optional[float],
) -> List[Dict[str, Any]]:
    recs: List[Dict[str, Any]] = []
    if pmax_wkg is not None and pmax_wkg >= 12 and (repeatability is None or repeatability < 82):
        recs.append({
            "type": "repeat_sprint_capacity",
            "message": "Pmax is strong but repeatability is limited: add full-recovery repeat sprint work.",
        })
    if cadence_peak is not None and cadence_peak < 85:
        recs.append({
            "type": "cadence_velocity",
            "message": "Peak power occurs at low cadence: include high-cadence accelerations to improve velocity side.",
        })
    if cadence_peak is not None and cadence_peak > 120:
        recs.append({
            "type": "force_side",
            "message": "Peak power occurs at very high cadence: include torque/standing starts if appropriate.",
        })
    if not recs:
        recs.append({"type": "monitor", "message": "Use future maximal sprint files to track Pmax and repeatability trend."})
    return recs
