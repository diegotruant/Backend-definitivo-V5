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


def _preprocess_dates(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload)
    if "dates" in payload:
        payload["dates"] = [
            date.fromisoformat(str(item).split("T")[0]) if not isinstance(item, date) else item
            for item in payload["dates"]
        ]
    return payload


def _build_acwr_trend(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_acwr_trend
    from engines.performance.training_variability_engine import calculate_acwr

    if payload.get("acwr_values"):
        processed = _preprocess_dates(payload)
        return chart_acwr_trend(processed["dates"], processed["acwr_values"], risk_zones=payload.get("risk_zones"))
    dates = payload.get("dates") or []
    atl = payload.get("atl_values") or []
    ctl = payload.get("ctl_values") or []
    acwr_values = []
    for a, c in zip(atl, ctl):
        out = calculate_acwr(float(a), float(c))
        acwr_values.append(out.get("acwr") if out.get("status") == "success" else None)
    processed = _preprocess_dates({**payload, "dates": dates, "acwr_values": acwr_values})
    return chart_acwr_trend(processed["dates"], acwr_values, risk_zones=payload.get("risk_zones"))


def _build_monotony_strain(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_monotony_strain
    from engines.performance.training_variability_engine import calculate_monotony_strain

    if payload.get("week_labels"):
        return chart_monotony_strain(
            payload["week_labels"],
            payload.get("monotony_values") or [],
            payload.get("strain_values") or [],
        )
    daily = payload.get("daily_tss") or []
    out = calculate_monotony_strain(daily)
    label = payload.get("week_label") or "Current week"
    return chart_monotony_strain(
        [label],
        [out.get("monotony")],
        [out.get("strain")],
    )


def _build_readiness_trend(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_readiness_trend

    processed = _preprocess_dates(payload)
    return chart_readiness_trend(
        processed["dates"],
        processed["readiness_scores"],
        load_component=payload.get("load_component"),
        hrv_component=payload.get("hrv_component"),
        sleep_component=payload.get("sleep_component"),
        subjective_component=payload.get("subjective_component"),
    )


def _build_durability_fingerprint(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_durability_fingerprint
    from engines.performance.durability_engine import (
        calculate_durability_index,
        calculate_np_drift,
        calculate_tte_sustainability,
        generate_hourly_decay_curve,
    )

    metrics = dict(payload.get("metrics") or {})
    if payload.get("power") and not metrics:
        power = payload["power"]
        duration_s = int(payload.get("duration_s") or len(power))
        threshold = float(payload.get("threshold_power") or payload.get("ftp_w") or 250)
        di = calculate_durability_index(power, duration_s)
        if di.get("status") == "success":
            metrics.update(di)
        np_drift = calculate_np_drift(power, duration_s)
        if np_drift.get("status") == "success":
            metrics.update(np_drift)
        tte = calculate_tte_sustainability(power, threshold)
        if tte.get("status") == "success":
            metrics.update(tte)
        hourly = generate_hourly_decay_curve(power, duration_s)
        if hourly.get("status") == "success":
            metrics["decay_rate_watts_per_hour"] = hourly.get("decay_rate_watts_per_hour")
    return chart_durability_fingerprint(metrics)


def _build_race_simulation_overlay(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_race_simulation_overlay
    from engines.performance.race_prediction_engine import parse_gpx_course, simulate_gpx_race

    if payload.get("simulation"):
        sim = payload["simulation"]
        plan = sim.get("pacing_plan") or []
        distance_km = payload.get("distance_km") or []
        elevation_m = payload.get("elevation_m") or []
        if not distance_km and plan:
            distance_km = [seg.get("start_km", 0) for seg in plan] + [plan[-1].get("end_km", 0)]
            elevation_m = [0.0] * len(distance_km)
        return chart_race_simulation_overlay(distance_km, elevation_m, plan)
    if payload.get("gpx"):
        points = parse_gpx_course(payload["gpx"])
        sim = simulate_gpx_race(
            payload["gpx"],
            weight_kg=float(payload["weight_kg"]),
            ftp_w=float(payload["ftp_w"]),
            metabolic_snapshot=payload.get("metabolic_snapshot"),
        )
        plan = sim.get("pacing_plan") or []
        distance_km = [p.distance_m / 1000.0 for p in points]
        elevation_m = [p.ele_m for p in points]
        return chart_race_simulation_overlay(distance_km, elevation_m, plan)
    return chart_race_simulation_overlay(
        payload["distance_km"],
        payload["elevation_m"],
        payload["pacing_plan"],
    )


def _build_kalman_trajectory(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_kalman_trajectory

    states = payload.get("states") or (payload.get("trajectory") or {}).get("states") or []
    return chart_kalman_trajectory(states, metric=payload.get("metric", "vo2max"))


def _build_pmc_forecast(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_pmc_forecast
    from engines.projection.season_projection_engine import project_season_from_plan

    if payload.get("projection"):
        series = payload["projection"].get("time_series") or []
        dates = [date.fromisoformat(row["date"]) for row in series]
        ctl = [row.get("ctl", 0) for row in series]
        atl = [row.get("atl", 0) for row in series]
        tsb = [row.get("form", row.get("ctl", 0) - row.get("atl", 0)) for row in series]
        split = int(payload.get("forecast_start_index") or payload.get("history_days") or 0)
        return chart_pmc_forecast(dates, ctl, atl, tsb, forecast_start_index=split)
    if payload.get("twin_state") and payload.get("calendar_plan"):
        proj = project_season_from_plan(payload["twin_state"], payload["calendar_plan"])
        series = proj.get("time_series") or []
        dates = [date.fromisoformat(row["date"]) for row in series]
        ctl = [row.get("ctl", 0) for row in series]
        atl = [row.get("atl", 0) for row in series]
        tsb = [row.get("form", 0) for row in series]
        split = int(payload.get("history_days") or max(0, len(series) // 4))
        return chart_pmc_forecast(dates, ctl, atl, tsb, forecast_start_index=split)
    processed = _preprocess_training_load(payload)
    return chart_pmc_forecast(
        processed["dates"],
        processed["ctl_values"],
        processed["atl_values"],
        processed["tsb_values"],
        forecast_start_index=payload.get("forecast_start_index"),
    )


def _build_segment_history(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_segment_history
    from engines.performance.consistency_engine import build_segment_history

    metric_key = payload.get("metric_key", "elapsed_s")
    if payload.get("segments"):
        return chart_segment_history(payload["segments"], metric_key=metric_key)
    built = build_segment_history(payload.get("segment_history") or [], metric_key=metric_key)
    return chart_segment_history(built.get("segments") or [], metric_key=metric_key)


def _build_eddington_consistency(payload: Dict[str, Any]) -> Dict[str, Any]:
    from engines.io.chart_builder import chart_eddington_consistency
    from engines.performance.consistency_engine import calculate_eddington_number

    values = payload.get("activity_values") or payload.get("values") or []
    if payload.get("eddington_result"):
        result = payload["eddington_result"]
    else:
        result = calculate_eddington_number(values, threshold=payload.get("threshold"), unit=payload.get("unit", "duration_h"))
    return chart_eddington_consistency(result, activity_values=values or None)


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
        ChartSpec("acwr_trend", _build_acwr_trend, ("dates", "atl_values", "ctl_values"), "load", "ACWR trend with risk bands", payload_dict=True),
        ChartSpec("monotony_strain", _build_monotony_strain, ("daily_tss",), "load", "Weekly monotony and strain", payload_dict=True),
        ChartSpec("readiness_trend", _build_readiness_trend, ("dates", "readiness_scores"), "readiness", "Readiness score and components over time", payload_dict=True),
        ChartSpec("durability_fingerprint", _build_durability_fingerprint, ("metrics",), "profile", "Durability radar fingerprint", payload_dict=True),
        ChartSpec("race_simulation_overlay", _build_race_simulation_overlay, ("distance_km", "elevation_m", "pacing_plan"), "race", "Elevation + target power overlay", payload_dict=True),
        ChartSpec("kalman_trajectory", _build_kalman_trajectory, ("states",), "profile", "Kalman VO2max/VLa trajectory with CI", payload_dict=True),
        ChartSpec("pmc_forecast", _build_pmc_forecast, ("dates", "ctl_values", "atl_values", "tsb_values"), "load", "PMC with forecast segment", payload_dict=True),
        ChartSpec("segment_history", _build_segment_history, ("segment_history",), "session", "Recurring segment best vs latest", payload_dict=True),
        ChartSpec("eddington_consistency", _build_eddington_consistency, ("activity_values",), "profile", "Eddington consistency histogram", payload_dict=True),
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
    if chart_type == "acwr_trend" and (payload.get("acwr_values") or payload.get("atl_values")):
        effective_required = ("dates",) if payload.get("acwr_values") else ("dates", "atl_values", "ctl_values")
    if chart_type == "monotony_strain" and payload.get("week_labels"):
        effective_required = ("week_labels", "monotony_values", "strain_values")
    if chart_type == "durability_fingerprint" and payload.get("power"):
        effective_required = ("power",)
    if chart_type == "race_simulation_overlay" and (payload.get("gpx") or payload.get("simulation")):
        effective_required = ("gpx", "weight_kg", "ftp_w") if payload.get("gpx") else ()
    if chart_type == "kalman_trajectory" and payload.get("trajectory"):
        effective_required = ()
    if chart_type == "pmc_forecast" and (payload.get("projection") or payload.get("twin_state")):
        effective_required = ()
    if chart_type == "segment_history" and payload.get("segments"):
        effective_required = ("segments",)
    if chart_type == "eddington_consistency" and payload.get("eddington_result"):
        effective_required = ()

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
