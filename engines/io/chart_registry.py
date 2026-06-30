"""Central registry for /meta/chart-config — all chart builders and required payload keys."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ChartBuilderFn = Callable[..., Dict[str, Any]]


@dataclass
class ChartBuildError(Exception):
    message: str
    code: str = "CHART_BUILD_ERROR"
    status_code: int = 422
    details: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class ChartSpec:
    chart_type: str
    builder: ChartBuilderFn
    required_keys: Tuple[str, ...]
    category: str
    description: str
    payload_dict: bool = False


def _missing_keys(payload: Dict[str, Any], required: Sequence[str]) -> List[str]:
    return [key for key in required if key not in payload]


def _preprocess_mmp(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload)
    payload["mmp"] = {int(k): float(v) for k, v in payload["mmp"].items()}
    return payload


def _preprocess_training_load(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload)
    payload["dates"] = [
        date.fromisoformat(str(item).split("T")[0]) if not isinstance(item, date) else item
        for item in payload["dates"]
    ]
    return payload


def _build_vo2_demand(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_from_metabolic_curve
    from engines.metabolic.metabolic_coach_curves import build_vo2_demand_curve

    if payload.get("curve"):
        return chart_from_metabolic_curve(payload["curve"])
    curve = build_vo2_demand_curve(
        payload["metabolic_snapshot"],
        weight_kg=payload.get("weight_kg"),
        eta=payload.get("eta"),
        power_points=payload.get("power_points"),
    )
    return chart_from_metabolic_curve(curve)


def _build_lactate(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_from_metabolic_curve
    from engines.metabolic.metabolic_coach_curves import build_lactate_curve

    if payload.get("curve"):
        return chart_from_metabolic_curve(payload["curve"])
    curve = build_lactate_curve(payload.get("lactate_steps"))
    return chart_from_metabolic_curve(curve)


def _build_substrate_oxidation(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_from_metabolic_curve
    from engines.metabolic.metabolic_coach_curves import build_substrate_curve

    if payload.get("curve"):
        return chart_from_metabolic_curve(payload["curve"])
    curve = build_substrate_curve(
        payload["metabolic_snapshot"],
        weight_kg=payload.get("weight_kg"),
        gender=payload.get("gender"),
        training_years=payload.get("training_years"),
        discipline=payload.get("discipline"),
    )
    return chart_from_metabolic_curve(curve)


def _build_session_fuel_demand(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_from_metabolic_curve
    from engines.metabolic.metabolic_coach_curves import build_session_fuel_demand_curve

    if payload.get("curve"):
        return chart_from_metabolic_curve(payload["curve"])
    curve = build_session_fuel_demand_curve(
        payload["metabolic_snapshot"],
        power_stream=payload["power"],
        weight_kg=payload.get("weight_kg"),
        gender=payload.get("gender"),
        training_years=payload.get("training_years"),
        discipline=payload.get("discipline"),
        dt_s=float(payload.get("dt_s", 1.0)),
    )
    return chart_from_metabolic_curve(curve)


def _build_session_fuel_partitioning(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_session_fuel_partitioning
    from engines.metabolic.metabolic_coach_curves import build_session_fuel_demand_curve

    if payload.get("points"):
        return chart_session_fuel_partitioning(payload["points"], summary=payload.get("summary"))
    curve = build_session_fuel_demand_curve(
        payload["metabolic_snapshot"],
        power_stream=payload["power"],
        weight_kg=payload.get("weight_kg"),
        dt_s=float(payload.get("dt_s", 1.0)),
    )
    return chart_session_fuel_partitioning(curve.get("points") or [], summary=curve.get("summary"))


def _build_w_prime_balance(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_w_prime_balance
    from engines.performance.performance_coach_curves import build_w_prime_balance_curve

    if payload.get("time_s") and payload.get("w_prime_balance_pct"):
        return chart_w_prime_balance(
            payload["time_s"],
            payload["w_prime_balance_pct"],
            w_prime_balance_j=payload.get("w_prime_balance_j"),
            cp_w=payload.get("cp_w"),
        )
    curve = build_w_prime_balance_curve(
        power_stream=payload["power"],
        cp_w=payload["cp_w"],
        w_prime_j=payload["w_prime_j"],
        dt_s=float(payload.get("dt_s", 1.0)),
    )
    points = curve.get("points") or []
    return chart_w_prime_balance(
        [p.get("time_s", i) for i, p in enumerate(points)],
        [p.get("w_prime_balance_pct", 0) for p in points],
        w_prime_balance_j=[p.get("w_prime_balance_j", 0) for p in points],
        cp_w=payload.get("cp_w"),
    )


def _activity_builder(fn: Callable[..., Dict[str, Any]], *, needs_zones: bool = False, needs_hrv: bool = False):
    def _wrapped(payload: Dict[str, Any]) -> Dict[str, Any]:
        from engines.io.chart_stream import stream_from_chart_payload

        stream = stream_from_chart_payload(payload)
        if needs_zones:
            return fn(stream, payload.get("zones") or [])
        if needs_hrv:
            return fn(stream, payload.get("hrv_durability"))
        return fn(stream)

    return _wrapped


def _chart_registry() -> Dict[str, ChartSpec]:
    from engines.io import activity_charts, chart_builder

    specs: List[ChartSpec] = [
        ChartSpec("mmp", chart_builder.chart_power_duration_curve, ("mmp",), "profile", "Mean maximal power curve"),
        ChartSpec("power_duration", chart_builder.chart_power_duration_curve, ("mmp",), "profile", "Alias for mmp"),
        ChartSpec("zones", chart_builder.chart_zones_distribution, ("zones_data",), "profile", "Time-in-zone distribution"),
        ChartSpec("hrv", chart_builder.chart_hrv_timeline, ("time_seconds", "dfa_alpha1"), "session", "DFA-alpha1 timeline"),
        ChartSpec("training_load", chart_builder.chart_training_load, ("dates", "ctl_values", "atl_values", "tsb_values"), "load", "PMC chart"),
        ChartSpec("detraining", chart_builder.chart_detraining_decay, ("parameters", "baseline_values", "current_values", "units"), "profile", "Detraining decay bars"),
        ChartSpec("metabolic_combustion", chart_builder.chart_metabolic_combustion, ("power_points", "fat_contribution", "carb_contribution", "anaerobic_contribution"), "metabolic", "Substrate contribution stacked area"),
        ChartSpec("cardiac_drift", chart_builder.chart_cardiac_drift, ("segments",), "session", "Cardiac drift by segment"),
        ChartSpec("efforts_radar", chart_builder.chart_efforts_radar, ("durations", "pct_ftp", "pct_cp", "pct_mlss", "pct_map"), "profile", "Peak efforts radar"),
        ChartSpec("phenotype_spider", chart_builder.chart_phenotype_spider, ("percentiles",), "profile", "Coggan phenotype spider"),
        ChartSpec("cross_validation_matrix", chart_builder.chart_cross_validation_matrix, ("methods", "vt1_powers", "vt2_powers"), "session", "VT method comparison table"),
        ChartSpec("hr_kinetics", chart_builder.chart_hr_kinetics, ("time_seconds", "hr_values"), "session", "HR rise kinetics"),
        ChartSpec("power_hr_scatter", chart_builder.chart_power_hr_scatter, ("power_values", "hr_values"), "session", "Power-HR scatter + CEI"),
        ChartSpec("hr_recovery", chart_builder.chart_hr_recovery, ("recovery_segments",), "session", "HRR60/120 bars"),
        ChartSpec("vo2_demand", _build_vo2_demand, ("metabolic_snapshot", "weight_kg"), "metabolic", "VO2 demand vs power (or pass curve)", payload_dict=True),
        ChartSpec("lactate", _build_lactate, ("lactate_steps",), "metabolic", "Measured lactate curve (or pass curve)", payload_dict=True),
        ChartSpec("substrate_oxidation", _build_substrate_oxidation, ("metabolic_snapshot", "weight_kg"), "metabolic", "Fat/CHO oxidation vs power", payload_dict=True),
        ChartSpec("session_fuel_demand", _build_session_fuel_demand, ("metabolic_snapshot", "power", "weight_kg"), "session", "Cumulative CHO/fat session demand", payload_dict=True),
        ChartSpec("session_fuel_partitioning", _build_session_fuel_partitioning, ("metabolic_snapshot", "power"), "session", "CHO vs fat rate + cumulative demand", payload_dict=True),
        ChartSpec("w_prime_balance", _build_w_prime_balance, ("power", "cp_w", "w_prime_j"), "session", "W′ balance over time", payload_dict=True),
    ]

    activity_map = {
        "activity_elevation": (activity_charts.chart_elevation, "Ride elevation profile"),
        "activity_speed": (activity_charts.chart_speed, "Ride speed"),
        "activity_power": (activity_charts.chart_power, "Ride power"),
        "activity_heart_rate": (activity_charts.chart_heart_rate, "Ride heart rate"),
        "activity_cadence": (activity_charts.chart_cadence, "Ride cadence"),
        "activity_respiration": (activity_charts.chart_respiration, "Respiration rate"),
        "activity_ambient_temp": (activity_charts.chart_ambient_temp, "Ambient temperature"),
        "activity_lr_balance": (activity_charts.chart_lr_balance, "L/R balance"),
        "activity_position": (activity_charts.chart_position, "Standing/seated"),
        "activity_power_phase": (activity_charts.chart_power_phase, "Power phase"),
        "activity_platform_offset": (activity_charts.chart_platform_offset, "Platform center offset"),
        "activity_time_in_power_zone": (activity_charts.chart_time_in_power_zone, "Time in power zones", True, False),
        "activity_time_in_intensity": (activity_charts.chart_time_in_intensity, "Time in intensity", False, True),
        "activity_thermal": (activity_charts.chart_thermal, "Thermal profile"),
    }

    for chart_type, meta in activity_map.items():
        if len(meta) == 2:
            fn, desc = meta
            needs_zones = needs_hrv = False
        else:
            fn, desc, needs_zones, needs_hrv = meta
        specs.append(
            ChartSpec(
                chart_type,
                _activity_builder(fn, needs_zones=needs_zones, needs_hrv=needs_hrv),
                ("power",),
                "activity",
                desc,
                payload_dict=True,
            )
        )

    return {spec.chart_type: spec for spec in specs}


_REGISTRY: Optional[Dict[str, ChartSpec]] = None


def get_chart_registry() -> Dict[str, ChartSpec]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _chart_registry()
    return _REGISTRY


def list_chart_types() -> Dict[str, Any]:
    registry = get_chart_registry()
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for spec in registry.values():
        by_category.setdefault(spec.category, []).append({
            "chart_type": spec.chart_type,
            "required_keys": list(spec.required_keys),
            "description": spec.description,
        })
    return {
        "status": "success",
        "schema_version": "chart_type_catalog.v1",
        "total": len(registry),
        "chart_types": sorted(registry.keys()),
        "by_category": by_category,
    }


def build_chart_config(chart_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    registry = get_chart_registry()
    spec = registry.get(chart_type)
    if spec is None:
        raise ChartBuildError(
            message=f"Unknown chart_type: {chart_type}",
            code="UNKNOWN_CHART_TYPE",
            details={"chart_type": chart_type, "available": sorted(registry.keys())},
        )

    # Allow pre-built curve to satisfy metabolic snapshot requirements
    effective_required = spec.required_keys
    if chart_type in {"vo2_demand", "substrate_oxidation", "session_fuel_demand"} and payload.get("curve"):
        effective_required = ()
    if chart_type == "lactate" and payload.get("curve"):
        effective_required = ()
    if chart_type == "session_fuel_partitioning" and payload.get("points"):
        effective_required = ("points",)
    if chart_type == "w_prime_balance" and payload.get("time_s"):
        effective_required = ("time_s", "w_prime_balance_pct")

    missing = _missing_keys(payload, effective_required)
    if missing:
        raise ChartBuildError(
            message=f"chart payload missing required keys: {', '.join(missing)}",
            code="MISSING_CHART_PAYLOAD",
            details={"chart_type": chart_type, "missing": missing, "required_keys": list(effective_required)},
        )

    processed = dict(payload)
    if chart_type in {"mmp", "power_duration"}:
        processed = _preprocess_mmp(processed)
    elif chart_type == "training_load":
        processed = _preprocess_training_load(processed)

    if spec.payload_dict:
        config = spec.builder(processed)
    else:
        config = spec.builder(**processed)
    return {
        "status": "success",
        "chart_type": chart_type,
        "category": spec.category,
        "config": config,
    }
