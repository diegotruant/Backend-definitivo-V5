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

from typing import Dict, Any, List, Optional
import numpy as np
from datetime import date


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
                "Agreement": "✓" if vt1 and vt2 else "Partial",
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
    Heart rate rise with exponential fit showing time constant τ.
    
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
            "name": f"Exponential Fit (τ={tau:.0f}s)",
            "x": (fit_time / 60).tolist(),
            "y": fit_hr.tolist(),
            "color": COLORS["danger"],
            "dash": "dash",
        }
    
    return {
        "type": "line_scatter",
        "title": "Heart Rate Kinetics",
        "description": f"Time constant τ = {tau:.0f}s" if tau else "HR response to work",
        
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
# METABOLIC / SESSION CURVES (coach curve contract → chart config)
# =============================================================================

CHART_CONFIG_SCHEMA_VERSION = "chart_config.v1"


def chart_from_metabolic_curve(curve: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap a metabolic_coach_curves single-curve dict into a chart config envelope."""
    if not isinstance(curve, dict) or not curve.get("points"):
        return {
            "schema_version": CHART_CONFIG_SCHEMA_VERSION,
            "type": "unavailable",
            "available": False,
            "reason": "empty_or_missing_curve",
            "curve_id": curve.get("curve_id") if isinstance(curve, dict) else None,
        }

    x_axis = curve.get("x_axis") or {}
    x_key = x_axis.get("key", "x")
    y_defs = curve.get("y_axis") or []
    points = curve["points"]

    series: List[Dict[str, Any]] = []
    palette = [COLORS["primary"], COLORS["fat"], COLORS["carb"], COLORS["secondary"]]
    for idx, y_def in enumerate(y_defs):
        y_key = y_def.get("key")
        if not y_key:
            continue
        series.append({
            "name": y_def.get("label", y_key),
            "x": [p.get(x_key) for p in points],
            "y": [p.get(y_key) for p in points],
            "color": palette[idx % len(palette)],
        })

    hint = curve.get("frontend_hint") or {}
    return {
        "schema_version": CHART_CONFIG_SCHEMA_VERSION,
        "type": hint.get("chart_type", "line"),
        "title": curve.get("title", curve.get("curve_id", "Curve")),
        "description": "; ".join(curve.get("limitations") or []),
        "curve_id": curve.get("curve_id"),
        "measurement_tier": curve.get("measurement_tier"),
        "confidence_score": curve.get("confidence_score"),
        "x_axis": {"label": x_key, "unit": x_axis.get("unit", "")},
        "y_axes": y_defs,
        "series": series,
        "anchors": curve.get("anchors") or [],
        "multi_series": bool(hint.get("multi_series")),
        "show_anchors": bool(hint.get("show_anchors", True)),
        "summary": curve.get("summary"),
    }


def chart_session_fuel_partitioning(
    points: List[Dict[str, Any]],
    *,
    summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """CHO vs fat oxidation rate (g/min) and cumulative demand over the session."""
    if not points:
        return {
            "schema_version": CHART_CONFIG_SCHEMA_VERSION,
            "type": "unavailable",
            "available": False,
            "reason": "empty_session_fuel_points",
        }

    time_s = [p.get("time_s") for p in points]
    return {
        "schema_version": CHART_CONFIG_SCHEMA_VERSION,
        "type": "line_multi",
        "title": "Session fuel partitioning",
        "description": "Estimated CHO and fat oxidation rates and cumulative demand (model, not calorimetry).",
        "measurement_tier": "MODEL_ESTIMATE",
        "x_axis": {"label": "Time", "unit": "s", "data": time_s},
        "y_axes": [
            {"id": "rate", "label": "Oxidation rate", "unit": "g/min"},
            {"id": "cumulative", "label": "Cumulative demand", "unit": "g"},
        ],
        "series": [
            {
                "name": "CHO rate",
                "y_axis_id": "rate",
                "x": time_s,
                "y": [p.get("carbohydrate_g_min_est") for p in points],
                "color": COLORS["carb"],
            },
            {
                "name": "Fat rate",
                "y_axis_id": "rate",
                "x": time_s,
                "y": [p.get("fat_g_min_est") for p in points],
                "color": COLORS["fat"],
            },
            {
                "name": "Cumulative CHO",
                "y_axis_id": "cumulative",
                "x": time_s,
                "y": [p.get("cumulative_carbohydrate_g") for p in points],
                "color": COLORS["warning"],
                "dash": "dash",
            },
            {
                "name": "Cumulative fat",
                "y_axis_id": "cumulative",
                "x": time_s,
                "y": [p.get("cumulative_fat_g") for p in points],
                "color": COLORS["success"],
                "dash": "dash",
            },
        ],
        "summary": summary or {},
    }


def chart_w_prime_balance(
    time_s: List[float],
    w_prime_balance_pct: List[float],
    *,
    w_prime_balance_j: Optional[List[float]] = None,
    cp_w: Optional[float] = None,
) -> Dict[str, Any]:
    """W′ balance depletion/recovery over a session."""
    series: List[Dict[str, Any]] = [
        {
            "name": "W′ balance %",
            "x": time_s,
            "y": w_prime_balance_pct,
            "color": COLORS["primary"],
            "y_axis_id": "pct",
        }
    ]
    if w_prime_balance_j:
        series.append({
            "name": "W′ balance (J)",
            "x": time_s,
            "y": w_prime_balance_j,
            "color": COLORS["secondary"],
            "y_axis_id": "joules",
            "opacity": 0.5,
        })

    return {
        "schema_version": CHART_CONFIG_SCHEMA_VERSION,
        "type": "line_multi",
        "title": "W′ balance",
        "description": f"Anaerobic work capacity relative to CP={cp_w:.0f} W" if cp_w else "W′ depletion and recovery",
        "measurement_tier": "MODEL_ESTIMATE",
        "x_axis": {"label": "Time", "unit": "s"},
        "y_axes": [
            {"id": "pct", "label": "W′ remaining", "unit": "%"},
            {"id": "joules", "label": "W′ remaining", "unit": "J"},
        ],
        "series": series,
        "reference_lines": [
            {"y": 40, "label": "Low W′ warning", "color": COLORS["warning"], "y_axis_id": "pct"},
        ],
    }


# =============================================================================
# LOAD / READINESS / FORECAST CHARTS
# =============================================================================

def chart_acwr_trend(
    dates: List[date],
    acwr_values: List[float],
    *,
    risk_zones: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """ACWR trend with Gabbett-style risk bands."""
    zones = risk_zones or {"detraining": 0.8, "optimal_high": 1.3, "high_risk": 1.5}
    date_strings = [d.isoformat() if isinstance(d, date) else str(d) for d in dates]

    return {
        "schema_version": CHART_CONFIG_SCHEMA_VERSION,
        "type": "line_multi",
        "title": "ACWR trend",
        "description": "Acute:chronic workload ratio over time",
        "measurement_tier": "MODEL_ESTIMATE",
        "x_axis": {"label": "Date", "type": "date", "format": "%b %d"},
        "y_axis": {"label": "ACWR", "format": ".2f"},
        "series": [
            {
                "name": "ACWR",
                "x": date_strings,
                "y": acwr_values,
                "color": COLORS["primary"],
            }
        ],
        "reference_bands": [
            {"y_min": zones["detraining"], "y_max": zones["optimal_high"], "label": "Optimal zone", "color": COLORS["success"], "opacity": 0.15},
            {"y_min": zones["optimal_high"], "y_max": zones["high_risk"], "label": "Caution", "color": COLORS["warning"], "opacity": 0.12},
            {"y_min": zones["high_risk"], "y_max": 2.5, "label": "High risk", "color": COLORS["danger"], "opacity": 0.1},
        ],
        "reference_lines": [
            {"y": zones["detraining"], "label": "Detraining", "color": COLORS["gray"], "dash": "dot"},
            {"y": zones["high_risk"], "label": "High risk", "color": COLORS["danger"], "dash": "dash"},
        ],
    }


def chart_monotony_strain(
    week_labels: List[str],
    monotony_values: List[Optional[float]],
    strain_values: List[Optional[float]],
) -> Dict[str, Any]:
    """Weekly monotony (line) and strain (bars) chart."""
    return {
        "schema_version": CHART_CONFIG_SCHEMA_VERSION,
        "type": "combo",
        "title": "Training monotony & strain",
        "description": "Foster monotony and strain by week",
        "measurement_tier": "MODEL_ESTIMATE",
        "x_axis": {"label": "Week", "categories": week_labels},
        "y_axes": [
            {"id": "monotony", "label": "Monotony", "format": ".2f"},
            {"id": "strain", "label": "Strain", "format": ".0f"},
        ],
        "series": [
            {"name": "Monotony", "type": "line", "y_axis_id": "monotony", "x": week_labels, "y": monotony_values, "color": COLORS["warning"]},
            {"name": "Strain", "type": "bar", "y_axis_id": "strain", "x": week_labels, "y": strain_values, "color": COLORS["secondary"], "opacity": 0.7},
        ],
        "reference_lines": [
            {"y": 1.5, "label": "Moderate", "color": COLORS["warning"], "y_axis_id": "monotony", "dash": "dot"},
            {"y": 2.0, "label": "High risk", "color": COLORS["danger"], "y_axis_id": "monotony", "dash": "dash"},
        ],
    }


def chart_readiness_trend(
    dates: List[date],
    readiness_scores: List[float],
    *,
    load_component: Optional[List[float]] = None,
    hrv_component: Optional[List[float]] = None,
    sleep_component: Optional[List[float]] = None,
    subjective_component: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Composite readiness score with optional component overlays."""
    date_strings = [d.isoformat() if isinstance(d, date) else str(d) for d in dates]
    series: List[Dict[str, Any]] = [
        {"name": "Readiness", "x": date_strings, "y": readiness_scores, "color": COLORS["primary"], "stroke_width": 2.5},
    ]
    component_specs = [
        ("Load", load_component, COLORS["ctl"]),
        ("HRV", hrv_component, COLORS["success"]),
        ("Sleep", sleep_component, COLORS["secondary"]),
        ("Subjective", subjective_component, COLORS["warning"]),
    ]
    for name, values, color in component_specs:
        if values:
            series.append({
                "name": name,
                "x": date_strings,
                "y": [round(v * 100, 1) if v <= 1.0 else round(v, 1) for v in values],
                "color": color,
                "opacity": 0.55,
                "y_axis_id": "components",
            })

    y_axes = [{"id": "score", "label": "Readiness", "domain": [0, 100]}]
    if any(v for _, v, _ in component_specs if v):
        y_axes.append({"id": "components", "label": "Components", "domain": [0, 100]})

    return {
        "schema_version": CHART_CONFIG_SCHEMA_VERSION,
        "type": "line_multi",
        "title": "Readiness trend",
        "description": "Daily readiness score and contributing signals",
        "measurement_tier": "MODEL_ESTIMATE",
        "x_axis": {"label": "Date", "type": "date"},
        "y_axes": y_axes,
        "series": series,
        "reference_bands": [
            {"y_min": 0, "y_max": 45, "label": "Recovery", "color": COLORS["danger"], "opacity": 0.08, "y_axis_id": "score"},
            {"y_min": 45, "y_max": 65, "label": "Moderate", "color": COLORS["warning"], "opacity": 0.08, "y_axis_id": "score"},
            {"y_min": 65, "y_max": 100, "label": "Ready", "color": COLORS["success"], "opacity": 0.08, "y_axis_id": "score"},
        ],
    }


def chart_durability_fingerprint(
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Radar fingerprint from durability engine outputs."""
    di = float(metrics.get("durability_index") or metrics.get("durability_index_pct") or 0)
    np_drift = float(metrics.get("np_drift_pct") or 0)
    tte = float(metrics.get("tte_minutes") or 0)
    decay_rate = abs(float(metrics.get("decay_rate_watts_per_hour") or metrics.get("decay_watts_per_hour") or 0))

    di_score = min(100.0, max(0.0, di))
    np_score = min(100.0, max(0.0, 100.0 + np_drift * 2.0))
    tte_score = min(100.0, tte / 60.0 * 100.0)
    decay_score = min(100.0, max(0.0, 100.0 - decay_rate * 3.0))

    categories = ["Durability index", "NP stability", "TTE @ threshold", "Decay resistance"]
    values = [round(di_score, 1), round(np_score, 1), round(tte_score, 1), round(decay_score, 1)]

    return {
        "schema_version": CHART_CONFIG_SCHEMA_VERSION,
        "type": "radar",
        "title": "Durability fingerprint",
        "description": metrics.get("classification") or metrics.get("interpretation") or "Fatigue resistance profile",
        "measurement_tier": "MODEL_ESTIMATE",
        "categories": categories,
        "series": [
            {"name": "Athlete", "values": values, "color": COLORS["primary"], "fill_opacity": 0.25},
            {"name": "Reference (good)", "values": [93, 95, 70, 80], "color": COLORS["gray"], "dash": "dash", "fill_opacity": 0},
        ],
        "domain": [0, 100],
        "raw_metrics": {
            "durability_index": di,
            "np_drift_pct": np_drift,
            "tte_minutes": tte,
            "decay_rate_watts_per_hour": decay_rate,
        },
    }


def chart_race_simulation_overlay(
    distance_km: List[float],
    elevation_m: List[float],
    pacing_plan: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Elevation profile with simulated target power overlay."""
    power_by_km: Dict[float, float] = {}
    for seg in pacing_plan:
        start = float(seg.get("start_km", 0))
        end = float(seg.get("end_km", start))
        power = float(seg.get("target_power_w", 0))
        mid = (start + end) / 2.0
        power_by_km[mid] = power

    power_x = sorted(power_by_km.keys())
    power_y = [power_by_km[k] for k in power_x]

    return {
        "schema_version": CHART_CONFIG_SCHEMA_VERSION,
        "type": "line_multi",
        "title": "Race simulation overlay",
        "description": "Course elevation with predicted target power",
        "measurement_tier": "MODEL_ESTIMATE",
        "x_axis": {"label": "Distance", "unit": "km"},
        "y_axes": [
            {"id": "elevation", "label": "Elevation", "unit": "m"},
            {"id": "power", "label": "Target power", "unit": "W"},
        ],
        "series": [
            {"name": "Elevation", "x": distance_km, "y": elevation_m, "color": COLORS["gray"], "y_axis_id": "elevation", "fill": True, "opacity": 0.35},
            {"name": "Target power", "x": power_x, "y": power_y, "color": COLORS["danger"], "y_axis_id": "power", "stroke_width": 2},
        ],
    }


def chart_kalman_trajectory(
    states: List[Dict[str, Any]],
    *,
    metric: str = "vo2max",
) -> Dict[str, Any]:
    """Kalman state trajectory with 95% confidence bands."""
    dates = [s.get("date") for s in states]
    values = [float(s.get(metric, 0) or 0) for s in states]
    std_key = f"{metric}_std"
    ci_key = f"{metric}_ci95"
    lower: List[float] = []
    upper: List[float] = []
    for s in states:
        if ci_key in s and isinstance(s[ci_key], (list, tuple)) and len(s[ci_key]) == 2:
            lower.append(float(s[ci_key][0]))
            upper.append(float(s[ci_key][1]))
        else:
            std = float(s.get(std_key, 0) or 0)
            val = float(s.get(metric, 0) or 0)
            lower.append(val - 1.96 * std)
            upper.append(val + 1.96 * std)

    label = "VO2max" if metric == "vo2max" else metric.replace("_", " ").title()
    unit = "ml/kg/min" if metric == "vo2max" else ""

    return {
        "schema_version": CHART_CONFIG_SCHEMA_VERSION,
        "type": "line_band",
        "title": f"{label} trajectory",
        "description": "Kalman-filtered metabolic state with 95% CI",
        "measurement_tier": "MODEL_ESTIMATE",
        "x_axis": {"label": "Date", "type": "date"},
        "y_axis": {"label": label, "unit": unit},
        "series": [
            {"name": label, "x": dates, "y": values, "color": COLORS["primary"]},
            {"name": "95% CI lower", "x": dates, "y": lower, "color": COLORS["primary"], "opacity": 0.2, "fill": False},
            {"name": "95% CI upper", "x": dates, "y": upper, "color": COLORS["primary"], "opacity": 0.2, "fill_between": "95% CI lower"},
        ],
    }


def chart_pmc_forecast(
    dates: List[date],
    ctl_values: List[float],
    atl_values: List[float],
    tsb_values: List[float],
    *,
    forecast_start_index: Optional[int] = None,
) -> Dict[str, Any]:
    """PMC with optional forecast segment styling."""
    date_strings = [d.isoformat() if isinstance(d, date) else str(d) for d in dates]
    split = forecast_start_index if forecast_start_index is not None else len(dates)

    def _segment(values: List[float], start: int, end: int) -> List[Optional[float]]:
        out: List[Optional[float]] = [None] * len(values)
        for i in range(start, min(end, len(values))):
            out[i] = values[i]
        return out

    series = [
        {"name": "CTL (Fitness)", "x": date_strings, "y": _segment(ctl_values, 0, split), "color": COLORS["ctl"]},
        {"name": "ATL (Fatigue)", "x": date_strings, "y": _segment(atl_values, 0, split), "color": COLORS["atl"]},
        {"name": "TSB (Form)", "x": date_strings, "y": _segment(tsb_values, 0, split), "color": COLORS["tsb"]},
    ]
    if split < len(dates):
        series.extend([
            {"name": "CTL forecast", "x": date_strings, "y": _segment(ctl_values, split, len(dates)), "color": COLORS["ctl"], "dash": "dash"},
            {"name": "ATL forecast", "x": date_strings, "y": _segment(atl_values, split, len(dates)), "color": COLORS["atl"], "dash": "dash"},
            {"name": "TSB forecast", "x": date_strings, "y": _segment(tsb_values, split, len(dates)), "color": COLORS["tsb"], "dash": "dash"},
        ])

    return {
        "schema_version": CHART_CONFIG_SCHEMA_VERSION,
        "type": "line_multi",
        "title": "PMC forecast",
        "description": "Performance management chart with planned-load projection",
        "measurement_tier": "MODEL_ESTIMATE",
        "x_axis": {"label": "Date", "type": "date"},
        "y_axis": {"label": "TSS/day"},
        "series": series,
        "forecast_start_date": date_strings[split] if split < len(date_strings) else None,
    }


def chart_segment_history(
    segments: List[Dict[str, Any]],
    *,
    metric_key: str = "elapsed_s",
) -> Dict[str, Any]:
    """Bar chart of best vs latest segment attempts."""
    labels = [str(s.get("segment_id") or s.get("name") or f"Seg {i+1}") for i, s in enumerate(segments)]
    best = [s.get("best") for s in segments]
    latest = [s.get("latest") for s in segments]

    return {
        "schema_version": CHART_CONFIG_SCHEMA_VERSION,
        "type": "bar_grouped",
        "title": "Segment history",
        "description": f"Best vs latest {metric_key}",
        "measurement_tier": "FIELD_MEASURED",
        "x_axis": {"label": "Segment", "categories": labels},
        "y_axis": {"label": metric_key},
        "series": [
            {"name": "Best", "x": labels, "y": best, "color": COLORS["success"]},
            {"name": "Latest", "x": labels, "y": latest, "color": COLORS["primary"]},
        ],
    }


def chart_eddington_consistency(
    eddington_result: Dict[str, Any],
    *,
    activity_values: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Histogram-style consistency chart for Eddington analysis."""
    values = activity_values or []
    unit = eddington_result.get("unit", "duration_h")
    eddington = int(eddington_result.get("eddington_number") or 0)

    bins = sorted(values, reverse=True) if values else []
    labels = [str(i + 1) for i in range(len(bins))]

    return {
        "schema_version": CHART_CONFIG_SCHEMA_VERSION,
        "type": "bar",
        "title": "Eddington consistency",
        "description": f"Eddington number = {eddington} ({eddington_result.get('consistency_band', 'n/a')})",
        "measurement_tier": "FIELD_MEASURED",
        "x_axis": {"label": "Activity rank", "categories": labels or ["—"]},
        "y_axis": {"label": unit},
        "series": [
            {"name": "Activity value", "x": labels, "y": bins or [0], "color": COLORS["primary"]},
        ],
        "reference_lines": [
            {"y": eddington, "label": f"Eddington = {eddington}", "color": COLORS["warning"], "dash": "dash"},
        ],
        "summary": {
            "eddington_number": eddington,
            "consistency_band": eddington_result.get("consistency_band"),
            "n_activities": eddington_result.get("n_activities"),
        },
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

if __name__ == "__main__":  # pragma: no cover
    import json
    
    # Example: Power Duration Curve
    mmp = {30: 850, 60: 720, 180: 520, 300: 420, 600: 340, 1200: 290}
    cp_model = {'cp': 275, 'w_prime': 18000}
    
    chart = chart_power_duration_curve(mmp, cp_model, ftp=290)
    
    print("=" * 80)
    print("POWER DURATION CURVE — Chart Config")
    print("=" * 80)
    print(json.dumps(chart, indent=2, default=str))
