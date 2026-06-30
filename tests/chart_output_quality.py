"""Shared fixtures and invariants for chart output quality gates."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from api.chart_schemas import validate_chart_envelope

METABOLIC_SNAPSHOT: Dict[str, Any] = {
    "status": "success",
    "fatmax_power_watts": 185.0,
    "mlss_power_watts": 282.0,
    "map_aerobic_watts": 392.0,
    "estimated_vo2max": 58.0,
    "estimated_vlamax_mmol_L_s": 0.42,
    "combustion_curve": [
        {"watt": 120, "fat_oxidation_g_min_est": 0.4, "carbohydrate_oxidation_g_min_est": 0.2},
        {"watt": 280, "fat_oxidation_g_min_est": 0.2, "carbohydrate_oxidation_g_min_est": 1.0},
    ],
}

_POWER = [180.0] * 120 + [260.0] * 60
_DATES = [(date.today() - timedelta(days=i)).isoformat() for i in range(3, 0, -1)]


def minimal_chart_payloads() -> Dict[str, Dict[str, Any]]:
    """Required-only payloads for every registered chart type."""
    lactate_steps = [
        {"power_w": 160, "lactate_mmol": 1.5},
        {"power_w": 220, "lactate_mmol": 2.4},
        {"power_w": 280, "lactate_mmol": 4.1},
    ]
    kalman_states = [
        {"date": _DATES[0], "vo2max": 55.0, "vo2max_std": 2.0, "vo2max_ci95": [51.1, 58.9]},
        {"date": _DATES[1], "vo2max": 55.8, "vo2max_std": 1.8, "vo2max_ci95": [52.3, 59.3]},
        {"date": _DATES[2], "vo2max": 56.2, "vo2max_std": 1.6, "vo2max_ci95": [53.1, 59.3]},
    ]
    return {
        "mmp": {"mmp": {60: 400, 300: 320, 1200: 280}},
        "power_duration": {"mmp": {60: 400, 300: 320, 1200: 280}},
        "zones": {"zones_data": {"coggan": {"Z1": 20.0, "Z2": 50.0, "Z3": 30.0}}},
        "hrv": {
            "time_seconds": [float(i * 60) for i in range(10)],
            "dfa_alpha1": [0.9 - i * 0.02 for i in range(10)],
        },
        "training_load": {
            "dates": _DATES,
            "ctl_values": [50.0, 51.0, 52.0],
            "atl_values": [48.0, 49.0, 50.0],
            "tsb_values": [2.0, 2.0, 2.0],
        },
        "detraining": {
            "parameters": ["VO2max", "CP"],
            "baseline_values": [58.0, 280.0],
            "current_values": [54.0, 275.0],
            "units": ["ml/kg/min", "W"],
        },
        "metabolic_combustion": {
            "power_points": [100, 200, 300],
            "fat_contribution": [80, 50, 20],
            "carb_contribution": [15, 35, 60],
            "anaerobic_contribution": [5, 15, 20],
        },
        "cardiac_drift": {
            "segments": [
                {"segment": "First half", "drift_pct": 2.3, "fitness": "EXCELLENT"},
                {"segment": "Second half", "drift_pct": 5.1, "fitness": "GOOD"},
            ],
        },
        "efforts_radar": {
            "durations": ["5s", "1m", "5m", "20m"],
            "pct_ftp": [180, 120, 105, 95],
            "pct_cp": [175, 118, 103, 93],
            "pct_mlss": [170, 115, 100, 90],
            "pct_map": [200, 130, 110, 98],
        },
        "phenotype_spider": {
            "percentiles": {
                "sprint": 6,
                "anaerobic": 5,
                "vo2max": 7,
                "threshold": 6,
                "endurance": 5,
            },
        },
        "cross_validation_matrix": {
            "methods": ["Mader", "Dmax"],
            "vt1_powers": [180, 175],
            "vt2_powers": [275, 270],
        },
        "hr_kinetics": {
            "time_seconds": [0, 30, 60, 90, 120],
            "hr_values": [120, 140, 155, 165, 170],
        },
        "power_hr_scatter": {
            "power_values": [150, 200, 250, 280],
            "hr_values": [130, 145, 160, 172],
        },
        "hr_recovery": {
            "recovery_segments": [
                {"name": "Effort 1", "hrr_60s": 22, "hrr_120s": 38},
            ],
        },
        "vo2_demand": {"metabolic_snapshot": METABOLIC_SNAPSHOT, "weight_kg": 72.0},
        "lactate": {"lactate_steps": lactate_steps},
        "substrate_oxidation": {"metabolic_snapshot": METABOLIC_SNAPSHOT, "weight_kg": 72.0},
        "session_fuel_demand": {
            "metabolic_snapshot": METABOLIC_SNAPSHOT,
            "power": _POWER,
            "weight_kg": 72.0,
        },
        "session_fuel_partitioning": {
            "metabolic_snapshot": METABOLIC_SNAPSHOT,
            "power": _POWER,
        },
        "w_prime_balance": {"power": _POWER, "cp_w": 280.0, "w_prime_j": 20000.0},
        "acwr_trend": {
            "dates": _DATES,
            "atl_values": [70.0, 65.0, 60.0],
            "ctl_values": [55.0, 56.0, 57.0],
        },
        "monotony_strain": {"daily_tss": [80, 65, 90, 75, 100, 60, 85]},
        "readiness_trend": {
            "dates": _DATES,
            "readiness_scores": [72, 68, 75],
        },
        "durability_fingerprint": {
            "metrics": {
                "durability_index": 92.0,
                "np_drift_pct": -2.0,
                "tte_minutes": 45.0,
                "decay_rate_watts_per_hour": 5.0,
            },
        },
        "race_simulation_overlay": {
            "distance_km": [0.0, 5.0, 10.0],
            "elevation_m": [100.0, 150.0, 120.0],
            "pacing_plan": [{"start_km": 0.0, "end_km": 10.0, "target_power_w": 250}],
        },
        "kalman_trajectory": {"states": kalman_states},
        "pmc_forecast": {
            "dates": _DATES,
            "ctl_values": [50.0, 51.0, 52.0],
            "atl_values": [48.0, 49.0, 50.0],
            "tsb_values": [2.0, 2.0, 2.0],
        },
        "segment_history": {
            "segment_history": [
                {"segment_id": "climb_a", "elapsed_s": 420, "avg_power_w": 280},
                {"segment_id": "climb_a", "elapsed_s": 405, "avg_power_w": 290},
            ],
        },
        "eddington_consistency": {"activity_values": [2.5, 3.0, 4.0, 5.0, 3.5, 4.5, 5.5]},
        "activity_elevation": {"power": _POWER},
        "activity_speed": {"power": _POWER},
        "activity_power": {"power": _POWER},
        "activity_heart_rate": {"power": _POWER},
        "activity_cadence": {"power": _POWER},
        "activity_respiration": {"power": _POWER},
        "activity_ambient_temp": {"power": _POWER},
        "activity_lr_balance": {"power": _POWER},
        "activity_position": {"power": _POWER},
        "activity_power_phase": {"power": _POWER},
        "activity_platform_offset": {"power": _POWER},
        "activity_time_in_power_zone": {"power": _POWER},
        "activity_time_in_intensity": {"power": _POWER},
        "activity_thermal": {"power": _POWER},
    }


_PLOTTABLE_KEYS = ("y", "x", "data", "values", "r")


def _series_has_plottable_data(item: Dict[str, Any]) -> bool:
    for key in _PLOTTABLE_KEYS:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            if not value:
                continue
            return None not in value
        return True
    return False


def assert_series_list_quality(series: Any, *, chart_type: str) -> None:
    """Frontend-safe invariants for chart series arrays."""
    assert isinstance(series, list), f"{chart_type}: series must be a list, got {type(series)}"
    assert None not in series, f"{chart_type}: series must not contain null entries"
    for index, item in enumerate(series):
        assert isinstance(item, dict), f"{chart_type}: series[{index}] must be an object"
        name = item.get("name")
        assert isinstance(name, str) and name.strip(), f"{chart_type}: series[{index}] missing name"
        assert _series_has_plottable_data(item), f"{chart_type}: series '{name}' has no plottable data"


def assert_chart_config_quality(config: Dict[str, Any], *, chart_type: str) -> None:
    """Validate a built chart config is consumable by frontends."""
    assert isinstance(config, dict), f"{chart_type}: config must be a dict"
    assert config.get("type"), f"{chart_type}: config.type is required"

    if config.get("available") is False or config.get("type") == "unavailable":
        return

    if "series" in config and config["series"] is not None:
        assert_series_list_quality(config["series"], chart_type=chart_type)


def build_and_validate_chart(chart_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_registry import build_chart_config

    envelope = build_chart_config(chart_type, payload)
    assert envelope["status"] == "success"
    validated = validate_chart_envelope(envelope)
    assert_chart_config_quality(validated["config"], chart_type=chart_type)
    return validated
