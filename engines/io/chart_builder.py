"""
Chart Builder — Visualization Config Generator
Version: 1.0.0

Generates chart configurations (JSON) for all Digital Twin backend data.
Output is frontend-agnostic (Recharts, Chart.js, Plotly compatible).

Each function returns a dict with:
- type: chart type (line, bar, scatter, area, radar, heatmap)
- data: formatted data points
- config: axis labels, colors, legends
- metadata: title, description, units
"""

from typing import Dict, Any, List, Optional, Tuple
import numpy as np
from datetime import date, timedelta


# =============================================================================
# DESIGN TOKENS — Consistent colors across all charts
# =============================================================================

COLORS = {
    # Zones
    "zone1": "#10b981",  # green (recovery)
    "zone2": "#3b82f6",  # blue (endurance)
    "zone3": "#f59e0b",  # amber (tempo)
    "zone4": "#ef4444",  # red (threshold)
    "zone5": "#dc2626",  # dark red (VO2max)
    "zone6": "#991b1b",  # darker red (anaerobic)
    "zone7": "#450a0a",  # darkest red (neuromuscular)
    
    # Metabolic
    "fat": "#10b981",      # green
    "carb": "#f59e0b",     # amber
    "anaerobic": "#ef4444", # red
    
    # Training load
    "ctl": "#3b82f6",      # blue (chronic)
    "atl": "#f59e0b",      # amber (acute)
    "tsb": "#10b981",      # green (balance)
    
    # Decay
    "baseline": "#6b7280",  # gray (peak)
    "current": "#ef4444",   # red (decayed)
    
    # HRV
    "hrv_good": "#10b981",
    "hrv_moderate": "#f59e0b",
    "hrv_poor": "#ef4444",
    
    # Generic
    "primary": "#3b82f6",
    "secondary": "#8b5cf6",
    "success": "#10b981",
    "warning": "#f59e0b",
    "danger": "#ef4444",
    "gray": "#6b7280",
}


# =============================================================================
# 1. POWER DURATION CURVE (MMP)
# =============================================================================

def chart_power_duration_curve(
    mmp: Dict[int, float],
    cp_model: Optional[Dict[str, float]] = None,
    ftp: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Power-duration curve with MMP data points + CP model fit.
    
    Args:
        mmp: {duration_seconds: power_watts}
        cp_model: Optional {'cp': watts, 'w_prime': joules}
        ftp: Optional FTP reference line
    
    Returns:
        Chart config dict
    """
    # Sort MMP by duration
    durations = sorted(mmp.keys())
    powers = [mmp[d] for d in durations]
    
    # Convert durations to minutes for x-axis
    duration_minutes = [d / 60 for d in durations]
    
    # Generate CP model curve if provided
    cp_curve = None
    if cp_model:
        cp = cp_model['cp']
        w_prime = cp_model['w_prime']
        
        # CP model: P(t) = W' / t + CP
        model_durations = np.logspace(0, 3.5, 50)  # 1s to ~3000s
        model_powers = [w_prime / t + cp for t in model_durations]
        model_minutes = model_durations / 60
        
        cp_curve = {
            "x": model_minutes.tolist(),
            "y": model_powers,
            "name": "CP Model Fit",
            "type": "line",
            "color": COLORS["secondary"],
            "dash": "dash",
        }
    
    return {
        "type": "line_scatter",
        "title": "Power Duration Curve",
        "description": "Mean maximal power across durations with CP model fit",
        
        "x_axis": {
            "label": "Duration (minutes)",
            "scale": "log",
            "domain": [0.1, 100],
            "format": ".1f",
        },
        
        "y_axis": {
            "label": "Power (W)",
            "scale": "linear",
            "format": ".0f",
        },
        
        "series": [
            {
                "name": "MMP",
                "type": "scatter",
                "x": duration_minutes,
                "y": powers,
                "color": COLORS["primary"],
                "marker": {"size": 8, "symbol": "circle"},
            },
            cp_curve,  # Can be None
            {
                "name": "FTP",
                "type": "line",
                "x": [0.1, 100],
                "y": [ftp, ftp] if ftp else None,
                "color": COLORS["warning"],
                "dash": "dot",
            } if ftp else None,
        ],
        
        "legend": {"position": "top-right"},
    }


# =============================================================================
# 2. ZONES DISTRIBUTION (4 systems)
# =============================================================================

def chart_zones_distribution(
    zones_data: Dict[str, Dict[str, float]],
    system: str = "coggan",
) -> Dict[str, Any]:
    """
    Stacked bar chart showing time-in-zone distribution.
    
    Args:
        zones_data: {
            'coggan': {'Z1': 30.5, 'Z2': 45.2, ...},
            'friel': {...},
            'seiler': {...},
            'metabolic': {...},
        }
        system: Which zone system to display
    
    Returns:
        Chart config
    """
    data = zones_data.get(system, {})
    
    # Map zone names to colors
    zone_colors = {
        'Z1': COLORS["zone1"],
        'Z2': COLORS["zone2"],
        'Z3': COLORS["zone3"],
        'Z4': COLORS["zone4"],
        'Z5': COLORS["zone5"],
        'Z6': COLORS["zone6"],
        'Z7': COLORS["zone7"],
    }
    
    # Extract zones and percentages
    zones = sorted(data.keys())
    percentages = [data[z] for z in zones]
    colors = [zone_colors.get(z, COLORS["gray"]) for z in zones]
    
    return {
        "type": "bar_stacked",
        "title": f"Time in Zone — {system.capitalize()}",
        "description": f"Distribution of workout time across {system} zones",
        
        "x_axis": {
            "label": "Zone",
            "categories": zones,
        },
        
        "y_axis": {
            "label": "Time (%)",
            "domain": [0, 100],
            "format": ".1f",
        },
        
        "series": [
            {
                "name": zone,
                "data": [pct],
                "color": color,
            }
            for zone, pct, color in zip(zones, percentages, colors)
        ],
        
        "stacked": True,
        "orientation": "vertical",
    }


# =============================================================================
# 3. METABOLIC COMBUSTION CURVE
# =============================================================================

def chart_metabolic_combustion(
    power_points: List[int],
    fat_contribution: List[float],
    carb_contribution: List[float],
    anaerobic_contribution: List[float],
    markers: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Stacked area chart showing fat/carb/anaerobic energy contribution.
    
    Args:
        power_points: Power values (x-axis)
        fat_contribution: % from fat at each power
        carb_contribution: % from carbs
        anaerobic_contribution: % from anaerobic
        markers: Optional {'FatMax': 215, 'VT1': 250, 'MLSS': 315}
    
    Returns:
        Chart config
    """
    return {
        "type": "area_stacked",
        "title": "Metabolic Combustion Profile",
        "description": "Energy substrate contribution across power outputs",
        
        "x_axis": {
            "label": "Power (W)",
            "format": ".0f",
        },
        
        "y_axis": {
            "label": "Energy Contribution (%)",
            "domain": [0, 100],
            "format": ".0f",
        },
        
        "series": [
            {
                "name": "Fat Oxidation",
                "data": list(zip(power_points, fat_contribution)),
                "color": COLORS["fat"],
                "fill": "tonexty",
            },
            {
                "name": "Carbohydrate",
                "data": list(zip(power_points, carb_contribution)),
                "color": COLORS["carb"],
                "fill": "tonexty",
            },
            {
                "name": "Anaerobic",
                "data": list(zip(power_points, anaerobic_contribution)),
                "color": COLORS["anaerobic"],
                "fill": "tonexty",
            },
        ],
        
        "markers": [
            {"x": power, "label": name, "color": COLORS["gray"]}
            for name, power in (markers or {}).items()
        ],
        
        "stacked": True,
    }


# =============================================================================
# 4. HRV TIMELINE + VT DETECTION
# =============================================================================

def chart_hrv_timeline(
    time_seconds: List[float],
    dfa_alpha1: List[float],
    vt1_power: Optional[float] = None,
    vt2_power: Optional[float] = None,
    power_series: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    DFA-α1 over time with VT1/VT2 detection points.
    
    Args:
        time_seconds: Time points
        dfa_alpha1: DFA-α1 values
        vt1_power: VT1 threshold power
        vt2_power: VT2 threshold power
        power_series: Optional power values for overlay
    
    Returns:
        Chart config
    """
    time_minutes = [t / 60 for t in time_seconds]
    
    # Find VT crossing points
    vt1_time = None
    vt2_time = None
    
    if power_series and vt1_power:
        for i, p in enumerate(power_series):
            if p >= vt1_power and vt1_time is None:
                vt1_time = time_minutes[i]
            if p >= vt2_power and vt2_time is None:
                vt2_time = time_minutes[i]
    
    series = [
        {
            "name": "DFA-α1",
            "type": "line",
            "x": time_minutes,
            "y": dfa_alpha1,
            "color": COLORS["primary"],
            "y_axis": "left",
        }
    ]
    
    # Add power overlay if provided
    if power_series:
        series.append({
            "name": "Power",
            "type": "line",
            "x": time_minutes,
            "y": power_series,
            "color": COLORS["gray"],
            "opacity": 0.3,
            "y_axis": "right",
        })
    
    # VT markers
    markers = []
    if vt1_time:
        markers.append({
            "x": vt1_time,
            "label": "VT1",
            "color": COLORS["warning"],
        })
    if vt2_time:
        markers.append({
            "x": vt2_time,
            "label": "VT2",
            "color": COLORS["danger"],
        })
    
    return {
        "type": "line_multi_axis",
        "title": "HRV-Derived Ventilatory Threshold Detection",
        "description": "DFA-α1 crossing 0.75 (VT1) and 0.50 (VT2)",
        
        "x_axis": {
            "label": "Time (minutes)",
            "format": ".0f",
        },
        
        "y_axes": [
            {
                "id": "left",
                "label": "DFA-α1",
                "position": "left",
                "domain": [0.2, 1.2],
                "format": ".2f",
            },
            {
                "id": "right",
                "label": "Power (W)",
                "position": "right",
                "format": ".0f",
            },
        ],
        
        "series": series,
        "markers": markers,
        
        "reference_lines": [
            {"y": 0.75, "label": "VT1 threshold", "color": COLORS["warning"], "dash": "dash"},
            {"y": 0.50, "label": "VT2 threshold", "color": COLORS["danger"], "dash": "dash"},
        ],
    }


# =============================================================================
# 5. CARDIAC DRIFT
# =============================================================================

def chart_cardiac_drift(
    segments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Bar chart showing cardiac drift % by segment.
    
    Args:
        segments: [
            {'segment': 'First Half', 'drift_pct': 2.3, 'fitness': 'EXCELLENT'},
            {'segment': 'Second Half', 'drift_pct': 5.1, 'fitness': 'GOOD'},
        ]
    
    Returns:
        Chart config
    """
    segment_names = [s['segment'] for s in segments]
    drift_values = [s['drift_pct'] for s in segments]
    
    # Color by fitness level
    fitness_colors = {
        'EXCELLENT': COLORS["success"],
        'GOOD': COLORS["hrv_good"],
        'FAIR': COLORS["warning"],
        'POOR': COLORS["danger"],
    }
    colors = [fitness_colors.get(s.get('fitness', 'FAIR'), COLORS["gray"]) for s in segments]
    
    return {
        "type": "bar",
        "title": "Cardiac Drift Analysis",
        "description": "Heart rate drift as indicator of aerobic fitness",
        
        "x_axis": {
            "label": "Segment",
            "categories": segment_names,
        },
        
        "y_axis": {
            "label": "Drift (%)",
            "format": ".1f",
        },
        
        "series": [
            {
                "name": "HR Drift",
                "data": drift_values,
                "colors": colors,
            }
        ],
        
        "reference_lines": [
            {"y": 5, "label": "Excellent threshold", "color": COLORS["success"]},
        ],
    }


# =============================================================================
# 6. TRAINING LOAD (PMC — Performance Management Chart)
# =============================================================================

def chart_training_load(
    dates: List[date],
    ctl_values: List[float],
    atl_values: List[float],
    tsb_values: List[float],
) -> Dict[str, Any]:
    """
    Multi-line chart showing CTL/ATL/TSB over time.
    
    Args:
        dates: Date points
        ctl_values: Chronic Training Load
        atl_values: Acute Training Load
        tsb_values: Training Stress Balance
    
    Returns:
        Chart config
    """
    date_strings = [d.isoformat() for d in dates]
    
    return {
        "type": "line_multi",
        "title": "Performance Management Chart (PMC)",
        "description": "Chronic load, acute fatigue, and training balance",
        
        "x_axis": {
            "label": "Date",
            "type": "date",
            "format": "%b %d",
        },
        
        "y_axis": {
            "label": "TSS/day",
            "format": ".0f",
        },
        
        "series": [
            {
                "name": "CTL (Fitness)",
                "x": date_strings,
                "y": ctl_values,
                "color": COLORS["ctl"],
                "line_width": 2,
            },
            {
                "name": "ATL (Fatigue)",
                "x": date_strings,
                "y": atl_values,
                "color": COLORS["atl"],
                "line_width": 2,
            },
            {
                "name": "TSB (Form)",
                "x": date_strings,
                "y": tsb_values,
                "color": COLORS["tsb"],
                "line_width": 2,
                "fill": "tozeroy",
                "fill_color": "rgba(16, 185, 129, 0.1)",
            },
        ],
        
        "zones": [
            {"y_range": [-30, -10], "label": "Overreaching", "color": COLORS["danger"]},
            {"y_range": [-10, 5], "label": "Optimal", "color": COLORS["success"]},
            {"y_range": [5, 25], "label": "Taper", "color": COLORS["warning"]},
        ],
    }


# =============================================================================
# 7. DETRAINING DECAY
# =============================================================================

def chart_detraining_decay(
    parameters: List[str],
    baseline_values: List[float],
    current_values: List[float],
    units: List[str],
) -> Dict[str, Any]:
    """
    Grouped bar chart comparing baseline vs current metabolic parameters.
    
    Args:
        parameters: ['VO2max', 'VLamax', 'MLSS', 'MAP']
        baseline_values: Peak values
        current_values: Decayed values
        units: ['ml/kg/min', 'mmol/L/s', 'W', 'W']
    
    Returns:
        Chart config
    """
    return {
        "type": "bar_grouped",
        "title": "Detraining Effect on Metabolic Parameters",
        "description": "Baseline (peak) vs current (decayed) values",
        
        "x_axis": {
            "label": "Parameter",
            "categories": parameters,
        },
        
        "y_axis": {
            "label": "Value",
            "format": ".1f",
        },
        
        "series": [
            {
                "name": "Baseline (Peak)",
                "data": baseline_values,
                "color": COLORS["baseline"],
            },
            {
                "name": "Current (Decayed)",
                "data": current_values,
                "color": COLORS["current"],
            },
        ],
        
        "annotations": [
            {
                "x": i,
                "text": f"{unit}",
                "y_offset": -20,
            }
            for i, unit in enumerate(units)
        ],
    }


# =============================================================================
# 8. EFFORTS COMPARISON (Radar Chart)
# =============================================================================

def chart_efforts_radar(
    durations: List[str],
    pct_ftp: List[float],
    pct_cp: List[float],
    pct_mlss: List[float],
    pct_map: List[float],
) -> Dict[str, Any]:
    """
    Radar/spider chart comparing peak efforts against multiple references.
    
    Args:
        durations: ['5s', '1min', '5min', '20min']
        pct_ftp: % of FTP for each duration
        pct_cp: % of CP
        pct_mlss: % of MLSS
        pct_map: % of MAP
    
    Returns:
        Chart config
    """
    return {
        "type": "radar",
        "title": "Peak Efforts — Multi-Reference Comparison",
        "description": "Relative to FTP, CP, MLSS, and MAP",
        
        "theta": durations,
        
        "series": [
            {
                "name": "% FTP",
                "r": pct_ftp,
                "color": COLORS["zone3"],
                "fill": "toself",
                "opacity": 0.3,
            },
            {
                "name": "% CP",
                "r": pct_cp,
                "color": COLORS["zone4"],
                "fill": "toself",
                "opacity": 0.3,
            },
            {
                "name": "% MLSS",
                "r": pct_mlss,
                "color": COLORS["warning"],
                "fill": "toself",
                "opacity": 0.3,
            },
            {
                "name": "% MAP",
                "r": pct_map,
                "color": COLORS["danger"],
                "fill": "toself",
                "opacity": 0.3,
            },
        ],
        
        "r_axis": {
            "range": [0, 200],
            "format": ".0f",
        },
    }


# =============================================================================
# 9. PHENOTYPE SPIDER (Coggan Percentiles)
# =============================================================================

def chart_phenotype_spider(
    percentiles: Dict[str, int],
) -> Dict[str, Any]:
    """
    Radar chart showing Coggan percentile tiers across durations.
    
    Args:
        percentiles: {'5s': 7, '1min': 6, '5min': 4, 'FTP': 3}
        (1-8 scale, 8 = world-class)
    
    Returns:
        Chart config
    """
    durations = list(percentiles.keys())
    tiers = list(percentiles.values())
    
    return {
        "type": "radar",
        "title": "Performance Phenotype (Coggan Percentiles)",
        "description": "Percentile tier across power durations (1=untrained, 8=world-class)",
        
        "theta": durations,
        
        "series": [
            {
                "name": "Percentile Tier",
                "r": tiers,
                "color": COLORS["primary"],
                "fill": "toself",
                "opacity": 0.5,
                "marker": {"size": 10},
            }
        ],
        
        "r_axis": {
            "range": [0, 8],
            "tick_values": [1, 2, 3, 4, 5, 6, 7, 8],
            "tick_text": ["Untrained", "Fair", "Moderate", "Good", "Very Good", "Excellent", "Exceptional", "World Class"],
        },
    }


# =============================================================================
# 10. CROSS-VALIDATION MATRIX (HRV vs Mader)
# =============================================================================

def chart_cross_validation_matrix(
    methods: List[str],
    vt1_powers: List[Optional[float]],
    vt2_powers: List[Optional[float]],
) -> Dict[str, Any]:
    """
    Table/heatmap comparing VT1/VT2 detection across methods.
    
    Args:
        methods: ['HRV (DFA-α1)', 'Mader Model', 'HR Method']
        vt1_powers: [250, 255, 248] or [None, ...]
        vt2_powers: [315, 318, None]
    
    Returns:
        Chart config (table format)
    """
    return {
        "type": "table",
        "title": "Cross-Validation: VT Detection Methods",
        "description": "Comparing threshold detection across different approaches",
        
        "columns": ["Method", "VT1 (W)", "VT2 (W)", "Agreement"],
        
        "data": [
            {
                "Method": method,
                "VT1 (W)": f"{vt1:.0f}" if vt1 else "N/A",
                "VT2 (W)": f"{vt2:.0f}" if vt2 else "N/A",
                "Agreement": "\u2713" if vt1 and vt2 else "Partial",
            }
            for method, vt1, vt2 in zip(methods, vt1_powers, vt2_powers)
        ],
        
        "highlight_divergence": True,  # Highlight if values differ >10W
    }


# =============================================================================
# 11. HR KINETICS (Exponential Curve)
# =============================================================================

def chart_hr_kinetics(
    time_seconds: List[float],
    hr_values: List[int],
    tau: Optional[float] = None,
    steady_state_hr: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Heart rate rise with exponential fit showing time constant \u03c4.
    
    Args:
        time_seconds: Time from work start
        hr_values: Actual HR
        tau: Time constant (seconds)
        steady_state_hr: Plateau HR
    
    Returns:
        Chart config
    """
    time_minutes = [t / 60 for t in time_seconds]
    
    # Generate exponential fit if tau provided
    fit_curve = None
    if tau and steady_state_hr:
        fit_time = np.linspace(0, max(time_seconds), 100)
        fit_hr = steady_state_hr * (1 - np.exp(-fit_time / tau))
        
        fit_curve = {
            "name": f"Exponential Fit (\u03c4={tau:.0f}s)",
            "x": (fit_time / 60).tolist(),
            "y": fit_hr.tolist(),
            "color": COLORS["danger"],
            "dash": "dash",
        }
    
    return {
        "type": "line_scatter",
        "title": "Heart Rate Kinetics",
        "description": f"Time constant \u03c4 = {tau:.0f}s" if tau else "HR response to work",
        
        "x_axis": {
            "label": "Time (minutes)",
            "format": ".1f",
        },
        
        "y_axis": {
            "label": "Heart Rate (bpm)",
            "format": ".0f",
        },
        
        "series": [
            {
                "name": "Actual HR",
                "type": "scatter",
                "x": time_minutes,
                "y": hr_values,
                "color": COLORS["primary"],
                "marker": {"size": 4},
            },
            fit_curve,
        ],
    }


# =============================================================================
# 12. POWER-HR SCATTER (CEI)
# =============================================================================

def chart_power_hr_scatter(
    power_values: List[float],
    hr_values: List[int],
    mlss_power: Optional[float] = None,
    cei: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Power vs HR scatter with MLSS point highlighted + CEI classification.
    
    Args:
        power_values: Power data points
        hr_values: Corresponding HR
        mlss_power: MLSS threshold
        cei: Cardiac Efficiency Index
    
    Returns:
        Chart config
    """
    # Highlight MLSS point
    mlss_hr = None
    if mlss_power:
        # Find HR closest to MLSS power
        closest_idx = min(range(len(power_values)), 
                         key=lambda i: abs(power_values[i] - mlss_power))
        mlss_hr = hr_values[closest_idx]
    
    cei_label = ""
    if cei:
        if cei > 1.10:
            cei_label = "EXCELLENT"
        elif cei > 1.00:
            cei_label = "GOOD"
        elif cei >= 0.90:
            cei_label = "FAIR"
        else:
            cei_label = "POOR"
    
    return {
        "type": "scatter",
        "title": f"Cardiac Efficiency Index — {cei_label}" if cei else "Power-HR Relationship",
        "description": f"CEI = {cei:.2f}" if cei else "Scatter plot of power vs heart rate",
        
        "x_axis": {
            "label": "Power (W)",
            "format": ".0f",
        },
        
        "y_axis": {
            "label": "Heart Rate (bpm)",
            "format": ".0f",
        },
        
        "series": [
            {
                "name": "Data Points",
                "x": power_values,
                "y": hr_values,
                "color": COLORS["gray"],
                "marker": {"size": 3, "opacity": 0.5},
            },
            {
                "name": "MLSS Point",
                "x": [mlss_power],
                "y": [mlss_hr],
                "color": COLORS["danger"],
                "marker": {"size": 12, "symbol": "star"},
            } if mlss_power and mlss_hr else None,
        ],
    }


# =============================================================================
# 13. HEART RATE RECOVERY
# =============================================================================

def chart_hr_recovery(
    recovery_segments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Bar chart showing HRR60s and HRR120s with quality thresholds.
    
    Args:
        recovery_segments: [
            {'name': 'Recovery 1', 'hrr_60s': 25, 'hrr_120s': 42},
            {'name': 'Recovery 2', 'hrr_60s': 22, 'hrr_120s': 38},
        ]
    
    Returns:
        Chart config
    """
    segment_names = [s['name'] for s in recovery_segments]
    hrr_60s = [s.get('hrr_60s', 0) for s in recovery_segments]
    hrr_120s = [s.get('hrr_120s', 0) for s in recovery_segments]
    
    return {
        "type": "bar_grouped",
        "title": "Heart Rate Recovery Analysis",
        "description": "HRR60s and HRR120s as indicators of autonomic function",
        
        "x_axis": {
            "label": "Recovery Segment",
            "categories": segment_names,
        },
        
        "y_axis": {
            "label": "HR Drop (bpm)",
            "format": ".0f",
        },
        
        "series": [
            {
                "name": "HRR 60s",
                "data": hrr_60s,
                "color": COLORS["warning"],
            },
            {
                "name": "HRR 120s",
                "data": hrr_120s,
                "color": COLORS["success"],
            },
        ],
        
        "reference_lines": [
            {"y": 12, "label": "HRR60 minimum (fair)", "color": COLORS["warning"]},
            {"y": 25, "label": "HRR60 excellent", "color": COLORS["success"]},
        ],
    }


# =============================================================================
# HELPER: Generate all charts for a workout
# =============================================================================

def generate_workout_charts(workout_summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate all applicable charts for a workout summary.
    
    Args:
        workout_summary: Output from workout_summary.generate_complete_summary()
    
    Returns:
        Dict of chart configs keyed by chart name
    """
    charts = {}
    
    # Extract data sections
    power_data = workout_summary.get('power_metrics', {})
    zones_data = workout_summary.get('zones_distribution', {})
    cardiac_data = workout_summary.get('cardiac_metrics', {})
    
    # 1. Power Duration Curve (if MMP available)
    if power_data.get('mmp_curve'):
        charts['power_duration'] = chart_power_duration_curve(
            mmp=power_data['mmp_curve'],
            cp_model=power_data.get('cp_model'),
            ftp=power_data.get('ftp'),
        )
    
    # 2. Zones Distribution (all 4 systems)
    if zones_data:
        for system in ['coggan', 'friel', 'seiler', 'metabolic']:
            if system in zones_data:
                charts[f'zones_{system}'] = chart_zones_distribution(
                    zones_data,
                    system=system,
                )
    
    # 3. Cardiac Drift (if available)
    if cardiac_data.get('drift'):
        charts['cardiac_drift'] = chart_cardiac_drift(
            segments=cardiac_data['drift'].get('segments', []),
        )
    
    # 4. HR Recovery (if available)
    if cardiac_data.get('recovery_segments'):
        charts['hr_recovery'] = chart_hr_recovery(
            recovery_segments=cardiac_data['recovery_segments'],
        )
    
    # Add more charts as data becomes available...
    
    return charts


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    import json
    
    # Example: Power Duration Curve
    mmp = {30: 850, 60: 720, 180: 520, 300: 420, 600: 340, 1200: 290}
    cp_model = {'cp': 275, 'w_prime': 18000}
    
    chart = chart_power_duration_curve(mmp, cp_model, ftp=290)
    
    print("=" * 80)
    print("POWER DURATION CURVE — Chart Config")
    print("=" * 80)
    print(json.dumps(chart, indent=2, default=str))
