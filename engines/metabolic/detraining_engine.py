"""
Detraining Engine — Metabolic Decay Modeling
Version: 1.0.0-Decay

Models how VO2max, VLamax, MLSS, FatMax, MAP decay over time based on:
- Training load history (CTL/ATL)
- Days since last workout
- Training stimulus quality

DECAY RATES (from literature):
- VO2max: -0.5%/day (inactive), -0.1%/day (maintenance)
- VLamax: -0.3%/day (inactive), -0.05%/day (maintenance)
- MLSS: follows VO2max closely
- FatMax: can improve during detraining (paradox)
- MAP: follows VO2max
"""

from typing import Dict, Any, Optional, List
from datetime import date, timedelta
import numpy as np

from engines.core.metric_contracts import annotate_payload


# =============================================================================
# DECAY PARAMETERS (from literature)
# =============================================================================

DECAY_PARAMS = {
    "vo2max": {
        "inactive_rate": 0.005,      # -0.5% per day (Coyle 1984)
        "partial_rate": 0.003,        # -0.3% per day (CTL 20-40)
        "maintenance_rate": 0.001,    # -0.1% per day (CTL > 40)
        "min_retention": 0.75,        # Floor at 75% of baseline
    },
    "vlamax": {
        "inactive_rate": 0.003,       # -0.3% per day
        "partial_rate": 0.001,        # -0.1% per day
        "maintenance_rate": 0.0005,   # -0.05% per day (more stable)
        "min_retention": 0.80,
    },
    "mlss": {
        "inactive_rate": 0.004,       # -0.4% per day (follows VO2max)
        "partial_rate": 0.002,
        "maintenance_rate": 0.0008,
        "min_retention": 0.75,
    },
    "map": {
        "inactive_rate": 0.005,       # -0.5% per day (tracks VO2max)
        "partial_rate": 0.003,
        "maintenance_rate": 0.001,
        "min_retention": 0.75,
    },
}

# CTL thresholds for decay classification
CTL_MAINTENANCE = 40.0  # TSS/day — maintaining fitness
CTL_PARTIAL = 20.0      # TSS/day — slow decay


def _reliable_number(snapshot: Dict[str, Any], field: str) -> Optional[float]:
    """Return a numeric snapshot field only if it was not masked."""
    value = snapshot.get(field)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# =============================================================================
# TRAINING LOAD CALCULATION (CTL/ATL/TSB)
# =============================================================================

def calculate_ctl_atl_tsb(
    workout_history: List[Dict[str, Any]],
    today: date,
    ctl_tau: int = 42,
    atl_tau: int = 7,
) -> Dict[str, float]:
    """
    Calculate Chronic Training Load (CTL), Acute Training Load (ATL),
    and Training Stress Balance (TSB) from workout history.
    
    Parameters:
        workout_history: List of dicts with 'date' and 'tss' keys
        today: Current date
        ctl_tau: CTL decay constant (default 42 days, Banister model)
        atl_tau: ATL decay constant (default 7 days)
    
    Returns:
        {'ctl': float, 'atl': float, 'tsb': float, 'days_since_last': int}
    """
    if not workout_history:
        return {"ctl": 0.0, "atl": 0.0, "tsb": 0.0, "days_since_last": 999}
    
    # Sort by date
    sorted_history = sorted(workout_history, key=lambda w: w["date"])
    
    # Initialize
    ctl = 0.0
    atl = 0.0
    
    # Process each day from earliest workout to today
    start_date = sorted_history[0]["date"]
    workout_dict = {w["date"]: w["tss"] for w in sorted_history}
    
    current_date = start_date
    while current_date <= today:
        tss_today = workout_dict.get(current_date, 0.0)
        
        # Exponential weighted moving average
        ctl = ctl * np.exp(-1 / ctl_tau) + tss_today * (1 - np.exp(-1 / ctl_tau))
        atl = atl * np.exp(-1 / atl_tau) + tss_today * (1 - np.exp(-1 / atl_tau))
        
        current_date += timedelta(days=1)
    
    tsb = ctl - atl
    
    # Days since last workout
    last_workout_date = sorted_history[-1]["date"]
    days_since_last = (today - last_workout_date).days
    
    return {
        "ctl": round(ctl, 1),
        "atl": round(atl, 1),
        "tsb": round(tsb, 1),
        "days_since_last": days_since_last,
    }


# =============================================================================
# DECAY MODELING
# =============================================================================

def calculate_decay_factor(
    days_inactive: float,
    ctl: float,
    param_name: str,
) -> float:
    """
    Calculate decay factor for a metabolic parameter.
    
    Returns multiplier (e.g., 0.95 = 5% decay)
    """
    params = DECAY_PARAMS.get(param_name, DECAY_PARAMS["vo2max"])
    
    # Select decay rate based on CTL
    if ctl > CTL_MAINTENANCE:
        rate = params["maintenance_rate"]
        regime = "maintenance"
    elif ctl > CTL_PARTIAL:
        rate = params["partial_rate"]
        regime = "partial_detraining"
    else:
        rate = params["inactive_rate"]
        regime = "full_detraining"
    
    # Exponential decay
    decay_factor = (1 - rate) ** days_inactive
    
    # Floor
    decay_factor = max(decay_factor, params["min_retention"])
    
    return decay_factor


def apply_detraining_model(
    baseline_snapshot: Dict[str, Any],
    workout_history: List[Dict[str, Any]],
    today: date,
) -> Dict[str, Any]:
    """
    Apply detraining model to a metabolic snapshot.
    
    Parameters:
        baseline_snapshot: Output from metabolic_profiler.generate_metabolic_snapshot()
        workout_history: List of {'date': date, 'tss': float}
        today: Current date
    
    Returns:
        Enhanced snapshot with:
        - current_* values (decayed)
        - baseline_* values (original)
        - decay_pct for each parameter
        - training_load_status
    """
    # Calculate training load
    tl = calculate_ctl_atl_tsb(workout_history, today)
    
    # Apply decay only to reliable, unmasked model outputs. Silent defaults
    # would make API consumers see precise-looking values with no data support.
    required_fields = {
        "estimated_vo2max": _reliable_number(baseline_snapshot, "estimated_vo2max"),
        "estimated_vlamax_mmol_L_s": _reliable_number(
            baseline_snapshot, "estimated_vlamax_mmol_L_s"
        ),
        "mlss_power_watts": _reliable_number(baseline_snapshot, "mlss_power_watts"),
        "map_aerobic_watts": _reliable_number(baseline_snapshot, "map_aerobic_watts"),
    }
    unavailable = [name for name, value in required_fields.items() if value is None]
    if unavailable:
        return annotate_payload({
            "status": "partial",
            "detraining_applied": False,
            "reference_date": today.isoformat(),
            "reason": "INSUFFICIENT_RELIABLE_METABOLIC_FIELDS",
            "unavailable_fields": unavailable,
            "training_load": {
                "ctl": tl["ctl"],
                "atl": tl["atl"],
                "tsb": tl["tsb"],
                "days_since_last_workout": tl["days_since_last"],
            },
            "baseline_snapshot": {
                "expressiveness": baseline_snapshot.get("expressiveness"),
                "unmasked_estimates": baseline_snapshot.get("unmasked_estimates"),
            },
        }, module_name="detraining_engine", method="ctl_decay_model", confidence=0.0)

    vo2max_baseline = required_fields["estimated_vo2max"]
    vlamax_baseline = required_fields["estimated_vlamax_mmol_L_s"]
    mlss_baseline = required_fields["mlss_power_watts"]
    map_baseline = required_fields["map_aerobic_watts"]
    if vo2max_baseline is None:
        raise ValueError("estimated_vo2max baseline is required")
    if vlamax_baseline is None:
        raise ValueError("estimated_vlamax_mmol_L_s baseline is required")
    if mlss_baseline is None:
        raise ValueError("mlss_power_watts baseline is required")
    if map_baseline is None:
        raise ValueError("map_aerobic_watts baseline is required")
    
    vo2max_decay = calculate_decay_factor(tl["days_since_last"], tl["ctl"], "vo2max")
    vlamax_decay = calculate_decay_factor(tl["days_since_last"], tl["ctl"], "vlamax")
    mlss_decay = calculate_decay_factor(tl["days_since_last"], tl["ctl"], "mlss")
    map_decay = calculate_decay_factor(tl["days_since_last"], tl["ctl"], "map")
    
    # Current (decayed) values
    vo2max_current = vo2max_baseline * vo2max_decay
    vlamax_current = vlamax_baseline * vlamax_decay
    mlss_current = mlss_baseline * mlss_decay
    map_current = map_baseline * map_decay
    
    # FatMax paradox: can improve during detraining if baseline was too high-intensity
    # Simple model: FatMax increases slightly if CTL drops from high levels
    fatmax_baseline = _reliable_number(baseline_snapshot, "fatmax_power_watts")
    fatmax_current: Optional[float]
    if fatmax_baseline is not None and tl["ctl"] < 30 and tl["days_since_last"] > 7:
        fatmax_current = fatmax_baseline * 1.05  # +5% (aerobic metabolism shift)
    else:
        fatmax_current = fatmax_baseline
    
    # Training status classification
    if tl["days_since_last"] > 14:
        status = "DETRAINING"
    elif tl["ctl"] < CTL_PARTIAL:
        status = "DECLINING"
    elif tl["ctl"] < CTL_MAINTENANCE:
        status = "MAINTAINING"
    else:
        status = "IMPROVING"
    
    result = {
        "status": "success",
        "detraining_applied": True,
        "reference_date": today.isoformat(),
        
        # Training load
        "training_load": {
            "ctl": tl["ctl"],
            "atl": tl["atl"],
            "tsb": tl["tsb"],
            "days_since_last_workout": tl["days_since_last"],
            "status": status,
        },
        
        # Current (decayed) values
        "current_vo2max": round(vo2max_current, 1),
        "current_vlamax": round(vlamax_current, 2),
        "current_mlss_watts": round(mlss_current, 0),
        "current_fatmax_watts": round(fatmax_current, 0) if fatmax_current is not None else None,
        "current_map_watts": round(map_current, 0),
        
        # Baseline (peak) values
        "baseline_vo2max": round(vo2max_baseline, 1),
        "baseline_vlamax": round(vlamax_baseline, 2),
        "baseline_mlss_watts": round(mlss_baseline, 0),
        "baseline_fatmax_watts": round(fatmax_baseline, 0) if fatmax_baseline is not None else None,
        "baseline_map_watts": round(map_baseline, 0),
        
        # Decay percentages
        "decay": {
            "vo2max_pct": round((1 - vo2max_decay) * 100, 1),
            "vlamax_pct": round((1 - vlamax_decay) * 100, 1),
            "mlss_pct": round((1 - mlss_decay) * 100, 1),
            "map_pct": round((1 - map_decay) * 100, 1),
        },
        
        # Recommendations
        "recommendations": _generate_recommendations(tl, status),
    }
    confidence = 0.65 if tl["days_since_last"] <= 14 else 0.5
    return annotate_payload(
        result,
        module_name="detraining_engine",
        method="ctl_decay_model",
        confidence=confidence,
        limitations=["Heuristic detraining rates; not lab-validated."],
    )


def _generate_recommendations(tl: Dict[str, float], status: str) -> List[str]:
    """Generate training recommendations based on load status."""
    recs = []
    
    if status == "DETRAINING":
        days_off = tl.get("days_since_last_workout", tl.get("days_since_last", 0))
        recs.append(f"⚠️ {days_off} days without training — estimated VO2max -5-10%")
        recs.append("Recommendation: 2 Z4-Z5 sessions this week to halt decay")
    elif status == "DECLINING":
        recs.append(f"CTL declining ({tl['ctl']:.0f} TSS/day) — aerobic capacity at risk")
        recs.append("Recommendation: increase volume or intensity to maintain fitness")
    elif status == "MAINTAINING":
        recs.append(f"Maintenance regime active (CTL {tl['ctl']:.0f}) — fitness stable")
    else:
        recs.append(f"CTL rising ({tl['ctl']:.0f}) — adaptations in progress")
    
    if tl["tsb"] < -20:
        recs.append("TSB very negative — consider a recovery week next week")
    elif tl["tsb"] > 15:
        recs.append("TSB positive — good time for testing or racing")
    
    return recs


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    from datetime import date, timedelta
    
    # Simulate workout history
    today = date(2026, 5, 15)
    history = [
        {"date": date(2026, 4, 1), "tss": 80},
        {"date": date(2026, 4, 3), "tss": 65},
        {"date": date(2026, 4, 5), "tss": 90},
        {"date": date(2026, 4, 8), "tss": 100},
        # ... more workouts ...
        {"date": date(2026, 4, 28), "tss": 75},
        # Then 17 days inactive
    ]
    
    # Baseline snapshot (from MMP)
    baseline = {
        "estimated_vo2max": 65.0,
        "estimated_vlamax_mmol_L_s": 0.50,
        "mlss_power_watts": 315.0,
        "fatmax_power_watts": 215.0,
        "map_aerobic_watts": 436.0,
    }
    
    # Apply detraining model
    result = apply_detraining_model(baseline, history, today)
    
    print("DETRAINING MODEL OUTPUT")
    print("=" * 60)
    print(f"Status: {result['training_load']['status']}")
    print(f"Days since last: {result['training_load']['days_since_last_workout']}")
    print(f"CTL: {result['training_load']['ctl']:.1f}")
    print()
    print("METABOLIC PARAMETERS:")
    print(f"  VO2max:  {result['baseline_vo2max']:.1f} → {result['current_vo2max']:.1f} ml/kg/min  ({result['decay']['vo2max_pct']:.1f}% decay)")
    print(f"  VLamax:  {result['baseline_vlamax']:.2f} → {result['current_vlamax']:.2f} mmol/L/s  ({result['decay']['vlamax_pct']:.1f}% decay)")
    print(f"  MLSS:    {result['baseline_mlss_watts']:.0f} → {result['current_mlss_watts']:.0f}W  ({result['decay']['mlss_pct']:.1f}% decay)")
    print(f"  MAP:     {result['baseline_map_watts']:.0f} → {result['current_map_watts']:.0f}W  ({result['decay']['map_pct']:.1f}% decay)")
    print()
    print("RECOMMENDATIONS:")
    for rec in result['recommendations']:
        print(f"  • {rec}")
