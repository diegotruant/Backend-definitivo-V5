"""
Durability Engine — Fatigue Resistance & Power Sustainability
Version: 1.0.0

Measures athlete's ability to sustain power output over long durations.

RESEARCH FOUNDATION:
- Riis & Paton (2022): Durability in professional cyclists
- Leo et al. (2022): TTE (time to exhaustion) decay
- Clark et al. (2018): Fatigue resistance index
- San-Millán & Brooks (2017): Mitochondrial efficiency

CONCEPT:
"Durability" = resistance to performance decay during prolonged exercise.
Two phenotypes:
- High durability: Maintains power well (>95% first→last hour)
- Low durability: Significant decay (<90% first→last hour)

METRICS:
1. Durability Index (DI) = (Power_last_hour / Power_first_hour) × 100
2. Power Decay Rate = (ΔPower / Duration_hours)
3. Normalized Power Drift = (NP_second_half / NP_first_half) × 100
4. TTE Sustainability = Time at threshold before 5% decay

APPLICATIONS:
- Identify aerobic base weaknesses
- Prescribe endurance vs intensity work
- Predict long-race performance
"""

from typing import Dict, Any, List
import numpy as np

from engines.core.metric_contracts import annotate_payload
from engines.performance.power_engine import normalized_power


# =============================================================================
# DURABILITY INDEX (Riis & Paton 2022)
# =============================================================================

def calculate_durability_index(
    power_stream: List[float],
    duration_seconds: int,
    min_duration_hours: float = 2.0,
) -> Dict[str, Any]:
    """
    Calculate Durability Index from power stream.
    
    Parameters:
        power_stream: 1Hz power data
        duration_seconds: Total duration
        min_duration_hours: Minimum duration for valid test (default 2h)
    
    Returns:
        {
            'durability_index': float,  # % of power maintained
            'classification': str,      # EXCELLENT/GOOD/FAIR/POOR
            'first_hour_avg': float,
            'last_hour_avg': float,
            'decay_watts': float,
        }
    """
    duration_hours = duration_seconds / 3600
    
    if duration_hours < min_duration_hours:
        return annotate_payload({
            "status": "insufficient_duration",
            "duration_hours": round(duration_hours, 1),
            "required_hours": min_duration_hours,
        }, module_name="durability_engine", method="elapsed_time_durability_index", confidence=0.0)
    
    power = np.asarray(power_stream[:duration_seconds], dtype=float)
    if power.size == 0:
        return annotate_payload(
            {"status": "invalid_data", "reason": "empty_power_stream"},
            module_name="durability_engine",
            method="elapsed_time_durability_index",
            confidence=0.0,
        )

    # Preserve elapsed time. Removing zeros compresses stops/coasting and makes
    # the first/last hour no longer represent real clock-time windows.
    if power.size >= 7200:
        first_hour = power[:3600]
        last_hour = power[-3600:]
    else:
        midpoint = power.size // 2
        first_hour = power[:midpoint]
        last_hour = power[midpoint:]

    if first_hour.size == 0 or last_hour.size == 0:
        return annotate_payload(
            {"status": "invalid_data", "reason": "insufficient_power_samples"},
            module_name="durability_engine",
            method="elapsed_time_durability_index",
            confidence=0.0,
        )

    first_hour_finite = first_hour[np.isfinite(first_hour)]
    last_hour_finite = last_hour[np.isfinite(last_hour)]
    if first_hour_finite.size == 0 or last_hour_finite.size == 0:
        return annotate_payload(
            {"status": "invalid_data", "reason": "non_finite_power_window"},
            module_name="durability_engine",
            method="elapsed_time_durability_index",
            confidence=0.0,
        )

    first_hour_avg = float(np.mean(first_hour_finite))
    last_hour_avg = float(np.mean(last_hour_finite))
    if not np.isfinite(first_hour_avg) or not np.isfinite(last_hour_avg):
        return annotate_payload(
            {"status": "invalid_data", "reason": "non_finite_power_window"},
            module_name="durability_engine",
            method="elapsed_time_durability_index",
            confidence=0.0,
        )
    
    # Durability Index
    durability_index = (last_hour_avg / first_hour_avg) * 100 if first_hour_avg > 0 else 0
    
    # Classification (Riis & Paton thresholds)
    if durability_index >= 97:
        classification = "EXCELLENT"
        interpretation = "Elite-level durability — sustained power over long efforts"
    elif durability_index >= 93:
        classification = "GOOD"
        interpretation = "Good durability — minor decay within normal range"
    elif durability_index >= 88:
        classification = "FAIR"
        interpretation = "Moderate durability — room for aerobic base improvement"
    else:
        classification = "POOR"
        interpretation = "Low durability — prioritize base endurance work"
    
    decay_watts = first_hour_avg - last_hour_avg
    decay_pct_per_hour = decay_watts / duration_hours
    
    result = {
        "status": "success",
        "durability_index": round(durability_index, 1),
        "classification": classification,
        "interpretation": interpretation,
        "first_hour_avg": round(first_hour_avg, 0),
        "last_hour_avg": round(last_hour_avg, 0),
        "decay_watts": round(decay_watts, 0),
        "decay_watts_per_hour": round(decay_pct_per_hour, 1),
        "duration_hours": round(duration_hours, 1),
    }
    confidence = min(0.9, 0.55 + max(0.0, min(duration_hours, 4.0) - 2.0) * 0.15)
    return annotate_payload(
        result,
        module_name="durability_engine",
        method="elapsed_time_durability_index",
        confidence=confidence,
        limitations=["Durability thresholds are heuristic and context-sensitive."],
    )


# =============================================================================
# NORMALIZED POWER DRIFT
# =============================================================================

def calculate_np_drift(
    power_stream: List[float],
    duration_seconds: int,
) -> Dict[str, Any]:
    """
    Calculate Normalized Power drift between first and second half.

    Uses the canonical Coggan NP implementation from ``power_engine`` so drift
    matches NP/IF/TSS elsewhere in the backend.
    """
    if duration_seconds < 1800:  # Need at least 30min
        return annotate_payload(
            {"status": "insufficient_duration"},
            module_name="durability_engine",
            method="normalized_power_drift",
            confidence=0.0,
            limitations=["Requires at least 30 minutes of power data."],
        )

    power = np.asarray(power_stream[:duration_seconds], dtype=float)
    if power.size < 60:
        return annotate_payload(
            {"status": "invalid_data", "reason": "empty_power_stream"},
            module_name="durability_engine",
            method="normalized_power_drift",
            confidence=0.0,
        )

    midpoint = power.size // 2
    np_first = normalized_power(power[:midpoint])
    np_second = normalized_power(power[midpoint:])

    if np_first <= 0:
        return annotate_payload(
            {"status": "invalid_data", "reason": "zero_np_first_half"},
            module_name="durability_engine",
            method="normalized_power_drift",
            confidence=0.0,
        )

    np_drift_pct = ((np_second / np_first) - 1) * 100

    if np_drift_pct > -2:
        classification = "EXCELLENT"
    elif np_drift_pct > -5:
        classification = "GOOD"
    elif np_drift_pct > -8:
        classification = "FAIR"
    else:
        classification = "POOR"

    return annotate_payload(
        {
            "status": "success",
            "np_first_half": round(np_first, 0),
            "np_second_half": round(np_second, 0),
            "np_drift_pct": round(np_drift_pct, 1),
            "classification": classification,
            "np_method": "power_engine.normalized_power",
        },
        module_name="durability_engine",
        method="normalized_power_drift",
        confidence=0.75,
        limitations=["Half-session NP drift is heuristic; compare with full-session NP from power_engine."],
    )


# =============================================================================
# TTE (TIME TO EXHAUSTION) SUSTAINABILITY
# =============================================================================

def calculate_tte_sustainability(
    power_stream: List[float],
    threshold_power: float,
    tolerance_pct: float = 5.0,
) -> Dict[str, Any]:
    """
    Calculate how long athlete can sustain threshold power before decay.
    
    Research: Leo et al. (2022) - TTE at threshold
    
    Definition:
    TTE = time until power drops >5% below threshold
    
    Parameters:
        power_stream: 1Hz power data
        threshold_power: FTP or MLSS
        tolerance_pct: % drop threshold (default 5%)
    
    Returns:
        Time to exhaustion in minutes
    """
    # Find continuous segments above threshold - tolerance
    min_power = threshold_power * (1 - tolerance_pct / 100)
    
    current_duration = 0
    max_duration = 0
    
    for p in power_stream:
        if p >= min_power:
            current_duration += 1
        else:
            if current_duration > max_duration:
                max_duration = current_duration
            current_duration = 0
    
    # Check final segment
    if current_duration > max_duration:
        max_duration = current_duration
    
    tte_minutes = max_duration / 60
    
    # Classification (based on FTP TTE benchmarks)
    if tte_minutes >= 60:
        classification = "EXCELLENT"
        interpretation = "Elite durability — can sustain threshold >1 hour"
    elif tte_minutes >= 40:
        classification = "GOOD"
        interpretation = "Good durability — 40-60min at threshold"
    elif tte_minutes >= 20:
        classification = "FAIR"
        interpretation = "Moderate durability — 20-40min at threshold"
    else:
        classification = "POOR"
        interpretation = "Low durability — <20min at threshold"
    
    return {
        "status": "success",
        "tte_minutes": round(tte_minutes, 1),
        "classification": classification,
        "interpretation": interpretation,
        "threshold_power": threshold_power,
        "tolerance_pct": tolerance_pct,
    }


# =============================================================================
# HOURLY POWER DECAY CURVE
# =============================================================================

def generate_hourly_decay_curve(
    power_stream: List[float],
    duration_seconds: int,
) -> Dict[str, Any]:
    """
    Generate hour-by-hour power averages to visualize decay.
    
    Returns data for chart visualization.
    """
    duration_hours = duration_seconds / 3600
    
    if duration_hours < 1:
        return {"status": "insufficient_duration"}
    
    # Split into hourly segments
    hourly_averages = []
    samples_per_hour = 3600
    
    for hour in range(int(duration_hours)):
        start_idx = hour * samples_per_hour
        end_idx = min(start_idx + samples_per_hour, len(power_stream))
        
        hour_data = np.asarray(power_stream[start_idx:end_idx], dtype=float)
        valid_positive = hour_data[np.isfinite(hour_data) & (hour_data > 0)]
        hour_avg = float(np.mean(valid_positive)) if valid_positive.size > 0 else 0.0
        
        hourly_averages.append({
            "hour": hour + 1,
            "average_power": round(hour_avg, 0),
        })
    
    # Calculate decay rate (linear regression)
    if len(hourly_averages) >= 2:
        hours = [h["hour"] for h in hourly_averages]
        powers = [h["average_power"] for h in hourly_averages]
        
        slope, intercept = np.polyfit(hours, powers, 1)
        decay_rate = slope  # Watts per hour
    else:
        decay_rate = 0
    
    return {
        "status": "success",
        "hourly_data": hourly_averages,
        "decay_rate_watts_per_hour": round(decay_rate, 1),
        "total_hours": len(hourly_averages),
    }


# =============================================================================
# TRAINING PRESCRIPTION
# =============================================================================

def generate_durability_prescription(
    durability_index: float,
    classification: str,
) -> Dict[str, Any]:
    """Generate training recommendations based on durability assessment."""
    if classification == "EXCELLENT":
        return {
            "focus": "Maintain current aerobic base",
            "volume": "70-80% Zone 2, 15-20% Zone 3-4, 5-10% Zone 5+",
            "key_sessions": [
                "3-4h endurance rides weekly",
                "1x sweet-spot intervals",
                "1x threshold work",
            ],
        }
    if classification == "GOOD":
        return {
            "focus": "Fine-tune aerobic efficiency",
            "volume": "75-85% Zone 2, 10-15% Zone 3-4, 5% Zone 5+",
            "key_sessions": [
                "2-3h base rides 3x/week",
                "1x tempo intervals",
                "Optional: 1x VO2max work",
            ],
        }
    if classification == "FAIR":
        return {
            "focus": "Build aerobic base — reduce intensity",
            "volume": "80-90% Zone 1-2, 10-15% Zone 3, <5% Zone 4+",
            "key_sessions": [
                "Long endurance rides (3-5h) 1-2x/week",
                "Tempo intervals 1x/week",
                "Limit high-intensity work",
            ],
        }
    return {
        "focus": "URGENT: Rebuild aerobic foundation",
        "volume": "85-95% Zone 1-2, 5-10% Zone 3, AVOID Zone 4+",
        "key_sessions": [
            "Consistent base rides 4-5x/week",
            "2-4h endurance pace",
            "NO threshold or VO2max work for 4-6 weeks",
        ],
    }
