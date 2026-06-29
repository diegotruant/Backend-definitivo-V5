"""Assigned-vs-performed workout compliance engine.

Compares a machine-readable planned workout against an ActivityStream-like object
(parsed from FIT by engines.io.fit_parser).  V1 uses sequential alignment from
activity start; later versions can replace the aligner with dynamic matching
without changing the API contract.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .models import WorkoutDefinition, normalize_workout


def _arr(stream: Any, name: str) -> np.ndarray:
    value = getattr(stream, name, None)
    if value is None:
        return np.array([], dtype=float)
    return np.asarray(value, dtype=float)


def _in_range_pct(values: np.ndarray, lo: float, hi: float) -> float:
    if values.size == 0:
        return 0.0
    mask = np.isfinite(values)
    if not mask.any():
        return 0.0
    valid = values[mask]
    return float(np.mean((valid >= lo) & (valid <= hi)) * 100.0)


def _mean(values: np.ndarray) -> Optional[float]:
    if values.size == 0:
        return None
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    return float(np.mean(finite))


def _duration_score(actual_s: int, planned_s: int, tolerance_pct: float) -> float:
    if planned_s <= 0:
        return 0.0
    error_pct = abs(actual_s - planned_s) / planned_s * 100.0
    if error_pct <= tolerance_pct:
        return 100.0
    # 0 score once the step is off by tolerance + 50%.
    return max(0.0, 100.0 * (1.0 - (error_pct - tolerance_pct) / 50.0))


def _intensity_score(time_in_target_pct: Optional[float], mean_value: Optional[float], target: Optional[Tuple[float, float]]) -> float:
    if time_in_target_pct is None:
        return 50.0
    base = time_in_target_pct
    if mean_value is None or target is None:
        return base
    lo, hi = target
    if lo <= mean_value <= hi:
        return max(base, 85.0)
    center = (lo + hi) / 2.0
    width = max(1.0, (hi - lo) / 2.0)
    distance = abs(mean_value - center)
    mean_penalty = min(50.0, max(0.0, distance - width) / max(center, 1.0) * 200.0)
    return max(0.0, min(100.0, 0.75 * base + 25.0 - mean_penalty))


def compare_workout_to_activity(
    workout_payload: Dict[str, Any],
    stream: Any,
    athlete_profile: Optional[Dict[str, Any]] = None,
    tolerance_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return compliance score, confidence score and step discrepancies."""
    workout: WorkoutDefinition = normalize_workout(workout_payload)
    athlete_profile = athlete_profile or {}
    tolerance_policy = tolerance_policy or {}

    duration_tolerance_pct = float(tolerance_policy.get("duration_tolerance_pct", 10.0))
    min_time_in_target_pct = float(tolerance_policy.get("min_time_in_target_pct", 75.0))
    major_miss_pct = float(tolerance_policy.get("major_miss_pct", 35.0))
    exact_power_tolerance_pct = float(tolerance_policy.get("exact_power_tolerance_pct", 5.0))
    exact_hr_tolerance_bpm = float(tolerance_policy.get("exact_hr_tolerance_bpm", 3.0))

    power = _arr(stream, "power")
    hr = _arr(stream, "heart_rate")
    cadence = _arr(stream, "cadence")
    n_samples = int(getattr(stream, "n_samples", max(len(power), len(hr), len(cadence))))
    if n_samples <= 0:
        return {
            "status": "failed",
            "reason": "EMPTY_ACTIVITY_STREAM",
            "compliance_score": None,
            "confidence_score": 0.0,
            "classification": "unknown",
            "discrepancies": [{
                "severity": "high",
                "type": "empty_activity",
                "message": "FIT file contains no usable samples.",
            }],
            "intervals": [],
        }

    has_power = bool(getattr(stream, "has_power", False) or np.any(power > 0))
    has_hr = bool(getattr(stream, "has_heart_rate", False) or np.any(hr > 0))
    has_cadence = bool(np.any(cadence > 0))

    intervals: List[Dict[str, Any]] = []
    discrepancies: List[Dict[str, Any]] = []
    total_weight = 0.0
    weighted_score = 0.0
    matched_key = 0
    planned_key = 0
    time_in_target_weighted = 0.0
    time_in_target_weight = 0.0

    cursor = int(tolerance_policy.get("trim_leading_s", 0) or 0)
    planned_duration = workout.duration_s

    for step in workout.steps:
        start = cursor
        end = min(n_samples, cursor + step.duration_s)
        actual_duration = max(0, end - start)
        cursor += step.duration_s

        is_key = step.is_key_step or step.type.lower() in {"work", "interval"}
        if is_key:
            planned_key += 1
        weight = float(step.duration_s) * (1.5 if is_key else 1.0)
        total_weight += weight

        power_target = step.power_range(athlete_profile)
        hr_target = step.hr_range()
        target_used = None
        target_range = None
        time_in_target_pct: Optional[float] = None
        actual_mean: Optional[float] = None
        intensity_unverifiable = False

        if power_target and not has_power:
            intensity_unverifiable = True
            target_used = "power"
            target_range = power_target
            time_in_target_pct = 0.0
        elif hr_target and not has_hr:
            intensity_unverifiable = True
            target_used = "heart_rate"
            target_range = hr_target
            time_in_target_pct = 0.0
        elif power_target and has_power:
            segment = power[start:end]
            target_used = "power"
            target_range = power_target
            if target_range[0] == target_range[1]:
                pad = max(1.0, target_range[0] * exact_power_tolerance_pct / 100.0)
                target_range = (target_range[0] - pad, target_range[1] + pad)
            actual_mean = _mean(segment)
            time_in_target_pct = _in_range_pct(segment, power_target[0], power_target[1])
        elif hr_target and has_hr:
            segment = hr[start:end]
            target_used = "heart_rate"
            target_range = hr_target
            if target_range[0] == target_range[1]:
                target_range = (target_range[0] - exact_hr_tolerance_bpm, target_range[1] + exact_hr_tolerance_bpm)
            actual_mean = _mean(segment)
            time_in_target_pct = _in_range_pct(segment, hr_target[0], hr_target[1])
        elif step.cadence_min_rpm is not None and step.cadence_max_rpm is not None and has_cadence:
            segment = cadence[start:end]
            target_used = "cadence"
            target_range = (float(step.cadence_min_rpm), float(step.cadence_max_rpm))
            actual_mean = _mean(segment)
            time_in_target_pct = _in_range_pct(segment, target_range[0], target_range[1])

        dur_score = _duration_score(actual_duration, step.duration_s, duration_tolerance_pct)
        if intensity_unverifiable:
            int_score = 0.0
            step_score = 0.35 * dur_score
            discrepancies.append({
                "severity": "high" if is_key else "medium",
                "type": "intensity_unverifiable",
                "step_id": step.step_id,
                "message": (
                    f"Step {step.step_id}: {target_used} target prescribed but sensor data unavailable."
                ),
            })
        else:
            int_score = _intensity_score(time_in_target_pct, actual_mean, target_range)
            if target_used is None:
                step_score = dur_score * 0.75 + 25.0
            else:
                step_score = 0.35 * dur_score + 0.65 * int_score
                time_in_target_weighted += (time_in_target_pct or 0.0) * weight
                time_in_target_weight += weight

        if is_key and step_score >= 70:
            matched_key += 1

        status = "completed"
        if actual_duration < step.duration_s * (1 - major_miss_pct / 100.0):
            status = "missed_or_short"
            discrepancies.append({
                "severity": "high" if is_key else "medium",
                "type": "short_step",
                "step_id": step.step_id,
                "message": f"Step {step.step_id} shorter than prescribed ({actual_duration}s of {step.duration_s}s).",
            })
        elif target_used and (time_in_target_pct or 0.0) < min_time_in_target_pct:
            status = "outside_target"
            severity = "high" if is_key and (time_in_target_pct or 0.0) < 50 else "medium"
            discrepancies.append({
                "severity": severity,
                "type": "outside_target",
                "step_id": step.step_id,
                "message": f"Step {step.step_id}: only {time_in_target_pct:.1f}% within target {target_used}.",
            })

        intervals.append({
            "step_id": step.step_id,
            "type": step.type,
            "is_key_step": is_key,
            "status": status,
            "score": round(max(0.0, min(100.0, step_score)), 1),
            "planned_start_s": start,
            "planned_duration_s": step.duration_s,
            "actual_matched_duration_s": actual_duration,
            "target_used": target_used,
            "target_range": [round(target_range[0], 1), round(target_range[1], 1)] if target_range else None,
            "actual_mean": round(actual_mean, 1) if actual_mean is not None else None,
            "time_in_target_pct": round(time_in_target_pct, 1) if time_in_target_pct is not None else None,
            "duration_score": round(dur_score, 1),
            "intensity_score": round(int_score, 1),
        })
        weighted_score += max(0.0, min(100.0, step_score)) * weight

    compliance_score = weighted_score / total_weight if total_weight > 0 else 0.0
    actual_duration_s = n_samples
    total_duration_score = _duration_score(actual_duration_s, planned_duration, duration_tolerance_pct)
    compliance_score = 0.85 * compliance_score + 0.15 * total_duration_score

    if compliance_score >= 90:
        classification = "completed_as_prescribed"
        validity = "valid"
    elif compliance_score >= 75:
        classification = "mostly_completed"
        validity = "valid_with_minor_discrepancies"
    elif compliance_score >= 55:
        classification = "partially_completed"
        validity = "partial"
    else:
        classification = "not_completed_as_prescribed"
        validity = "invalid_or_failed"

    targetable_steps = sum(1 for i in intervals if i.get("target_used"))
    confidence = 0.95
    if targetable_steps == 0:
        confidence = 0.35
        discrepancies.append({
            "severity": "medium",
            "type": "no_comparable_targets",
            "message": "No step has a target comparable to sensors available in the FIT file.",
        })
    if any(step.power_range(athlete_profile) for step in workout.steps) and not has_power:
        confidence = min(confidence, 0.45)
        discrepancies.append({
            "severity": "high",
            "type": "missing_power",
            "message": "Workout prescribed on power, but the FIT file has no power data.",
        })
    if actual_duration_s < planned_duration * 0.5:
        confidence = min(confidence, 0.6)

    return {
        "status": "success",
        "workout_id": workout.workout_id,
        "compliance_score": round(max(0.0, min(100.0, compliance_score)), 1),
        "confidence_score": round(max(0.0, min(1.0, confidence)), 2),
        "classification": classification,
        "validity": validity,
        "summary": {
            "planned_duration_s": planned_duration,
            "actual_duration_s": int(actual_duration_s),
            "duration_compliance_pct": round(total_duration_score, 1),
            "intensity_compliance_pct": round(time_in_target_weighted / time_in_target_weight, 1) if time_in_target_weight else None,
            "structure_compliance_pct": round(matched_key / planned_key * 100.0, 1) if planned_key else None,
            "completed_key_intervals": matched_key,
            "planned_key_intervals": planned_key,
            "has_power": has_power,
            "has_hr": has_hr,
            "has_cadence": has_cadence,
        },
        "discrepancies": discrepancies,
        "intervals": intervals,
        "notes": [
            "V1 uses sequential alignment from the activity start; dynamic outdoor matching can be added later.",
        ],
    }
