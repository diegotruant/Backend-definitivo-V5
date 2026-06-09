"""Scoring helpers for adaptive load.

All scores are deterministic 0..100 heuristics designed for trending and
coach decision support. Absolute cutoffs should be tuned with real athlete data.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import numpy as np

from engines.core.analysis import clean_rr_intervals


_MIN_RR_BEATS = 30


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return float(max(lo, min(hi, value)))


def weighted_score(parts: Iterable[tuple[Optional[float], float]]) -> Optional[float]:
    values = [(float(v), float(w)) for v, w in parts if v is not None and w > 0]
    if not values:
        return None
    total_w = sum(w for _, w in values)
    return round(sum(v * w for v, w in values) / total_w, 1)


def score_from_high_is_bad(value: Optional[float], *, good: float, bad: float) -> Optional[float]:
    """Map a metric where higher is worse to 0..100, with good=100 and bad=0."""
    if value is None:
        return None
    if bad == good:
        return None
    return round(clamp(100.0 * (bad - float(value)) / (bad - good)), 1)


def score_from_low_is_bad(value: Optional[float], *, bad: float, good: float) -> Optional[float]:
    """Map a metric where lower is worse to 0..100, with bad=0 and good=100."""
    if value is None:
        return None
    if good == bad:
        return None
    return round(clamp(100.0 * (float(value) - bad) / (good - bad)), 1)


def flatten_rr_intervals(stream: Any) -> list[float]:
    rr_nested = getattr(stream, "rr_intervals", []) or []
    rr: list[float] = []
    for bucket in rr_nested:
        if not bucket:
            continue
        if isinstance(bucket, (list, tuple)):
            rr.extend(float(v) for v in bucket if v is not None)
        else:
            rr.append(float(bucket))
    return rr


def calculate_rr_metrics(stream: Any) -> Dict[str, Any]:
    """Calculate simple session-level HRV descriptors from RR intervals."""
    raw_rr = flatten_rr_intervals(stream)
    if len(raw_rr) < _MIN_RR_BEATS:
        return {
            "available": False,
            "reason": "NO_RR_DATA_OR_TOO_FEW_BEATS",
            "n_beats": len(raw_rr),
            "rmssd_ms": None,
            "lnrmssd": None,
            "sdnn_ms": None,
            "artifact_ratio": None,
            "autonomic_strain_score": None,
        }

    cleaned = clean_rr_intervals(raw_rr)
    artifact_ratio = 1.0 - (len(cleaned) / max(len(raw_rr), 1))
    if len(cleaned) < _MIN_RR_BEATS:
        return {
            "available": False,
            "reason": "RR_DATA_TOO_NOISY_AFTER_CLEANING",
            "n_beats": len(raw_rr),
            "n_clean_beats": int(len(cleaned)),
            "artifact_ratio": round(float(artifact_ratio), 3),
            "rmssd_ms": None,
            "lnrmssd": None,
            "sdnn_ms": None,
            "autonomic_strain_score": None,
        }

    diffs = np.diff(cleaned)
    rmssd = float(np.sqrt(np.mean(diffs ** 2))) if diffs.size else None
    sdnn = float(np.std(cleaned)) if cleaned.size else None
    lnrmssd = float(np.log(rmssd)) if rmssd and rmssd > 0 else None

    # During-session HRV is an acute strain marker, not morning readiness.
    # Low lnRMSSD plus noisy RR increases strain. Broad heuristic only.
    ln_component = score_from_high_is_bad(lnrmssd, good=3.9, bad=2.8)
    artifact_component = score_from_low_is_bad(artifact_ratio, bad=0.20, good=0.02)
    quality_score = weighted_score(((ln_component, 0.75), (artifact_component, 0.25)))
    strain = None if quality_score is None else round(100.0 - quality_score, 1)

    return {
        "available": True,
        "n_beats": len(raw_rr),
        "n_clean_beats": int(len(cleaned)),
        "rmssd_ms": round(rmssd, 2) if rmssd is not None else None,
        "lnrmssd": round(lnrmssd, 3) if lnrmssd is not None else None,
        "sdnn_ms": round(sdnn, 2) if sdnn is not None else None,
        "artifact_ratio": round(float(artifact_ratio), 3),
        "autonomic_strain_score": strain,
    }


def extract_power_metrics(workout_summary: Dict[str, Any]) -> Dict[str, Any]:
    power = (workout_summary.get("sections") or {}).get("power") or {}
    metrics = power.get("metrics") or {}
    return {
        "available": power.get("status") == "success",
        "tss": metrics.get("tss"),
        "intensity_factor": metrics.get("intensity_factor"),
        "normalized_power": metrics.get("normalized_power"),
        "work_kj": metrics.get("work_kj"),
        "duration_s": metrics.get("duration_s") or (workout_summary.get("stream_metadata") or {}).get("duration_s"),
    }


def extract_cardiac_metrics(workout_summary: Dict[str, Any]) -> Dict[str, Any]:
    headline = workout_summary.get("headline") or {}
    cardiac = (workout_summary.get("sections") or {}).get("cardiac") or {}
    return {
        "available": cardiac.get("status") == "success",
        "worst_cardiac_drift_pct": headline.get("worst_cardiac_drift_pct"),
        "worst_aerobic_decoupling_pct": headline.get("worst_aerobic_decoupling_pct"),
        "fitness_class": headline.get("cardiac_fitness_class"),
        "confidence": headline.get("cardiac_confidence"),
    }


def calculate_external_load(power_metrics: Dict[str, Any]) -> Dict[str, Any]:
    tss = _as_float(power_metrics.get("tss"))
    work_kj = _as_float(power_metrics.get("work_kj"))
    duration_s = _as_float(power_metrics.get("duration_s"))

    if tss is not None:
        score = clamp(tss)
        source = "tss"
    elif work_kj is not None:
        score = clamp(work_kj / 10.0)  # 1000 kJ ~= 100 load points fallback
        source = "work_kj_fallback"
    elif duration_s is not None:
        score = clamp(duration_s / 36.0)  # 60 min ~= 100 fallback for no power
        source = "duration_fallback"
    else:
        score = None
        source = "unavailable"

    return {
        "available": score is not None,
        "score": round(score, 1) if score is not None else None,
        "source": source,
        "tss": tss,
        "work_kj": work_kj,
    }


def calculate_internal_load(cardiac_metrics: Dict[str, Any]) -> Dict[str, Any]:
    drift = _as_float(cardiac_metrics.get("worst_cardiac_drift_pct"))
    decoupling = _as_float(cardiac_metrics.get("worst_aerobic_decoupling_pct"))

    drift_strain = score_from_low_is_bad(drift, bad=0.0, good=12.0)
    decoupling_strain = score_from_low_is_bad(decoupling, bad=0.0, good=10.0)
    score = weighted_score(((drift_strain, 0.45), (decoupling_strain, 0.55)))

    return {
        "available": score is not None,
        "score": score,
        "worst_cardiac_drift_pct": drift,
        "worst_aerobic_decoupling_pct": decoupling,
    }


def calculate_thermal_load(thermal_report: Dict[str, Any]) -> Dict[str, Any]:
    if thermal_report.get("data_quality") == "no_data":
        return {
            "available": False,
            "score": None,
            "reason": "NO_CORE_BODY_TEMPERATURE_DATA",
            "report": thermal_report,
        }

    zones = thermal_report.get("time_in_zone_s") or {}
    peak = _as_float(thermal_report.get("core_temp_peak"))
    rise_rate = _as_float(thermal_report.get("thermal_rise_rate"))
    n_valid = max(float(thermal_report.get("n_valid_samples") or 0), 1.0)

    hot_seconds = float(zones.get("hot_38.5_39.0") or 0)
    caution_seconds = float(zones.get("caution_39.0_39.5") or 0)
    danger_seconds = float(zones.get("danger_above_39.5") or 0)
    zone_component = clamp(
        100.0 * (0.6 * hot_seconds + 1.0 * caution_seconds + 1.5 * danger_seconds) / n_valid
    )
    peak_component = score_from_low_is_bad(peak, bad=37.5, good=39.5)
    rise_component = score_from_low_is_bad(rise_rate, bad=0.0, good=0.04)
    score = weighted_score(((zone_component, 0.45), (peak_component, 0.35), (rise_component, 0.20)))

    return {
        "available": score is not None,
        "score": score,
        "core_temp_peak": peak,
        "thermal_rise_rate": rise_rate,
        "time_in_zone_s": zones,
        "report": thermal_report,
    }


def calculate_session_load(
    *,
    external_load: Dict[str, Any],
    internal_load: Dict[str, Any],
    rr_metrics: Dict[str, Any],
    thermal_load: Dict[str, Any],
) -> Dict[str, Any]:
    score = weighted_score(
        (
            (external_load.get("score"), 0.50),
            (internal_load.get("score"), 0.25),
            (rr_metrics.get("autonomic_strain_score"), 0.10),
            (thermal_load.get("score"), 0.15),
        )
    )
    return {
        "status": "success" if score is not None else "insufficient_data",
        "score": score,
        "external_load": external_load,
        "internal_load": internal_load,
        "autonomic_load": rr_metrics,
        "thermal_load": thermal_load,
        "weights": {
            "external": 0.50,
            "internal": 0.25,
            "autonomic": 0.10,
            "thermal": 0.15,
        },
    }


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(value_f):
        return None
    return value_f
