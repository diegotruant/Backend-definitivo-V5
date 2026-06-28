"""Coach-facing metabolic curves.

Backend-owned curve generation for DB/frontend rendering.  The frontend should
not recalculate physiology; it should render the stable curve contract emitted
here: points, anchors, units, measurement tier, confidence and limitations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from engines.metabolic.fatmax_engine import build_model_fatmax_report
from engines.metabolic.lactate_validation_engine import LactateStep, compute_lactate_thresholds

MODEL_ESTIMATE = "MODEL_ESTIMATE"
LAB_MEASURED = "LAB_MEASURED"
HEURISTIC = "HEURISTIC"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

O2_ENERGY_EQUIVALENT_J_PER_L = 20_900.0
DEFAULT_GROSS_EFFICIENCY = 0.22


def _finite_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _round_or_none(value: Optional[float], digits: int = 1) -> Optional[float]:
    return round(value, digits) if value is not None and np.isfinite(value) else None


def _curve(
    *,
    curve_id: str,
    title: str,
    x_key: str,
    x_unit: str,
    y_keys: Sequence[Dict[str, str]],
    measurement_tier: str,
    points: List[Dict[str, Any]],
    anchors: Optional[List[Dict[str, Any]]] = None,
    confidence_score: float = 0.5,
    limitations: Optional[List[str]] = None,
    frontend_hint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "curve_id": curve_id,
        "title": title,
        "x_axis": {"key": x_key, "unit": x_unit},
        "y_axis": list(y_keys),
        "measurement_tier": measurement_tier,
        "points": points,
        "anchors": anchors or [],
        "confidence_score": round(max(0.0, min(0.95, confidence_score)), 3),
        "limitations": limitations or [],
        "frontend_hint": frontend_hint or {"chart_type": "line", "show_anchors": True},
    }


def _snapshot_value(snapshot: Dict[str, Any], *names: str) -> Optional[float]:
    for name in names:
        value = _finite_float(snapshot.get(name))
        if value is not None:
            return value
    return None


def _default_power_points(snapshot: Dict[str, Any], explicit: Optional[Sequence[float]] = None) -> List[float]:
    if explicit:
        values = sorted({_finite_float(v) for v in explicit})
        return [float(v) for v in values if v is not None and v > 0]

    fatmax = _snapshot_value(snapshot, "fatmax_power_watts", "fatmax_power_w")
    mlss = _snapshot_value(snapshot, "mlss_power_watts", "mlss_power_w")
    map_power = _snapshot_value(snapshot, "map_aerobic_watts", "map_power_w")
    anchors = [v for v in (fatmax, mlss, map_power) if v is not None and v > 0]
    if mlss is not None and mlss > 0:
        low = max(40.0, mlss * 0.35)
        high = max(map_power or mlss * 1.35, mlss * 1.35)
    elif fatmax is not None and fatmax > 0:
        low = max(40.0, fatmax * 0.45)
        high = fatmax * 1.9
    else:
        low, high = 80.0, 360.0
    generated = list(np.linspace(low, high, 15))
    return sorted({round(float(v), 1) for v in generated + anchors if v and v > 0})


def _vo2_domain(pct_vo2max: Optional[float]) -> str:
    if pct_vo2max is None:
        return "unknown"
    if pct_vo2max < 40:
        return "recovery_low_aerobic"
    if pct_vo2max < 58:
        return "fatmax_low_aerobic_domain"
    if pct_vo2max < 75:
        return "moderate_aerobic_domain"
    if pct_vo2max < 90:
        return "threshold_domain"
    return "severe_vo2_domain"


def _vo2_demand_at_power(
    power_w: float,
    *,
    weight_kg: float,
    vo2max_ml_kg_min: float,
    eta: float,
) -> Dict[str, Any]:
    metabolic_power_w = power_w / max(eta, 0.05)
    vo2_l_min = metabolic_power_w * 60.0 / O2_ENERGY_EQUIVALENT_J_PER_L
    vo2_ml_kg_min = vo2_l_min * 1000.0 / max(weight_kg, 1.0)
    pct = vo2_ml_kg_min / max(vo2max_ml_kg_min, 1.0) * 100.0
    return {
        "power_w": round(power_w, 1),
        "vo2_l_min": round(vo2_l_min, 3),
        "vo2_ml_kg_min": round(vo2_ml_kg_min, 1),
        "pct_vo2max": round(pct, 1),
        "domain": _vo2_domain(pct),
    }


def build_vo2_demand_curve(
    metabolic_snapshot: Dict[str, Any],
    *,
    weight_kg: Optional[float],
    vo2max_ml_kg_min: Optional[float] = None,
    eta: Optional[float] = None,
    power_points: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Build %VO2max-vs-watt demand curve.

    This is a demand estimate from mechanical power and gross efficiency unless
    true gas-exchange points are supplied elsewhere.
    """
    snapshot = metabolic_snapshot or {}
    weight = weight_kg if weight_kg and weight_kg > 0 else None
    vo2max = vo2max_ml_kg_min or _snapshot_value(snapshot, "estimated_vo2max", "vo2max_ml_kg_min")
    if weight is None or vo2max is None or vo2max <= 0:
        return _curve(
            curve_id="vo2_demand",
            title="VO2 demand",
            x_key="power_w",
            x_unit="W",
            y_keys=[{"key": "pct_vo2max", "unit": "%", "label": "%VO2max"}],
            measurement_tier=INSUFFICIENT_DATA,
            points=[],
            confidence_score=0.0,
            limitations=["Requires body weight and VO2max estimate or measurement."],
        )

    eta_used = eta or _finite_float(snapshot.get("gross_efficiency")) or DEFAULT_GROSS_EFFICIENCY
    powers = _default_power_points(snapshot, power_points)
    points = [
        _vo2_demand_at_power(power, weight_kg=weight, vo2max_ml_kg_min=vo2max, eta=eta_used)
        for power in powers
    ]

    anchors = []
    for label, key_a, key_b in (
        ("FATmax", "fatmax_power_watts", "fatmax_power_w"),
        ("MLSS", "mlss_power_watts", "mlss_power_w"),
        ("MAP", "map_aerobic_watts", "map_power_w"),
    ):
        power = _snapshot_value(snapshot, key_a, key_b)
        if power is not None and power > 0:
            demand = _vo2_demand_at_power(power, weight_kg=weight, vo2max_ml_kg_min=vo2max, eta=eta_used)
            anchors.append({"label": label, "power_w": round(power, 1), "pct_vo2max": demand["pct_vo2max"]})

    confidence = 0.62
    confidence += 0.08 if snapshot.get("status") == "success" else 0.0
    confidence += 0.06 if _snapshot_value(snapshot, "mlss_power_watts", "mlss_power_w") else 0.0
    confidence += 0.04 if _snapshot_value(snapshot, "map_aerobic_watts", "map_power_w") else 0.0
    confidence += 0.04 if eta is not None or snapshot.get("gross_efficiency") else 0.0

    return _curve(
        curve_id="vo2_demand",
        title="VO2 demand (%VO2max vs watt)",
        x_key="power_w",
        x_unit="W",
        y_keys=[
            {"key": "pct_vo2max", "unit": "%", "label": "%VO2max"},
            {"key": "vo2_ml_kg_min", "unit": "ml/kg/min", "label": "VO2 demand"},
        ],
        measurement_tier=MODEL_ESTIMATE,
        points=points,
        anchors=anchors,
        confidence_score=confidence,
        limitations=[
            "Estimated from mechanical power and gross efficiency, not measured by gas exchange.",
            "Gross efficiency strongly affects VO2 demand estimates.",
        ],
        frontend_hint={"chart_type": "line", "show_anchors": True, "preferred_y": "pct_vo2max"},
    ) | {"model_parameters": {"eta_used": round(eta_used, 3), "weight_kg": round(weight, 1), "vo2max_ml_kg_min": round(vo2max, 1)}}


def build_substrate_curve(
    metabolic_snapshot: Dict[str, Any],
    *,
    weight_kg: Optional[float],
    gender: Optional[str] = None,
    training_years: Optional[float] = None,
    discipline: Optional[str] = None,
    threshold_fraction: float = 0.80,
) -> Dict[str, Any]:
    """Build FAT/CHO model curve from the FATmax report model."""
    report = build_model_fatmax_report(
        metabolic_snapshot,
        athlete_weight_kg=weight_kg,
        gender=gender,
        training_years=training_years,
        discipline=discipline,
        threshold_fraction=threshold_fraction,
    )
    if report.get("status") != "success":
        return _curve(
            curve_id="substrate_oxidation",
            title="FAT/CHO oxidation",
            x_key="power_w",
            x_unit="W",
            y_keys=[{"key": "fat_oxidation_proxy", "unit": "proxy", "label": "Fat"}],
            measurement_tier=INSUFFICIENT_DATA,
            points=[],
            confidence_score=0.0,
            limitations=["Requires a usable metabolic snapshot with FATmax/MLSS anchors."],
        )
    curve = report.get("curve") or {}
    points = list(curve.get("points") or [])
    anchors = []
    summary = report.get("summary") or {}
    fatmax = _finite_float(summary.get("fatmax_power_w"))
    if fatmax is not None:
        anchors.append({"label": "FATmax", "power_w": round(fatmax, 1), "mfo_g_min": summary.get("mfo_g_min")})
    crossover = _finite_float(curve.get("carbohydrate_crossover_w"))
    if crossover is not None:
        anchors.append({"label": "Carbohydrate crossover", "power_w": round(crossover, 1)})
    return _curve(
        curve_id="substrate_oxidation",
        title="FAT/CHO oxidation curve",
        x_key="power_w",
        x_unit="W",
        y_keys=[
            {"key": "fat_oxidation_g_min_est", "unit": "g/min", "label": "Fat oxidation est."},
            {"key": "carbohydrate_oxidation_g_min_est", "unit": "g/min", "label": "CHO oxidation est."},
        ],
        measurement_tier=report.get("measurement_tier", MODEL_ESTIMATE),
        points=points,
        anchors=anchors,
        confidence_score=float(report.get("confidence_score", 0.55)),
        limitations=list(report.get("limitations") or []),
        frontend_hint={"chart_type": "line", "show_anchors": True, "multi_series": True},
    ) | {"fatmax_base": curve.get("fatmax_base"), "source_report_summary": summary}


def _lactate_steps_from_payload(rows: Optional[Sequence[Dict[str, Any]]]) -> List[LactateStep]:
    steps: List[LactateStep] = []
    for row in rows or []:
        power = _finite_float(row.get("power_w"))
        lactate = _finite_float(row.get("lactate_mmol") or row.get("lactate_mmol_l"))
        if power is None or lactate is None or power <= 0 or lactate <= 0:
            continue
        steps.append(
            LactateStep(
                power_w=power,
                lactate_mmol=lactate,
                hr_mean=_finite_float(row.get("hr_mean") or row.get("heart_rate_bpm")),
                cadence_mean=_finite_float(row.get("cadence_mean")),
                duration_s=_finite_float(row.get("duration_s")),
            )
        )
    return steps


def build_lactate_curve(lactate_steps: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    """Serialize measured lactate steps and threshold anchors."""
    steps = _lactate_steps_from_payload(lactate_steps)
    if len(steps) < 3:
        return _curve(
            curve_id="lactate",
            title="Lactate curve",
            x_key="power_w",
            x_unit="W",
            y_keys=[{"key": "lactate_mmol", "unit": "mmol/L", "label": "Lactate"}],
            measurement_tier=INSUFFICIENT_DATA,
            points=[],
            confidence_score=0.0,
            limitations=["Requires at least three measured lactate steps; five are recommended for D-max."],
        )
    thresholds = compute_lactate_thresholds(steps).to_dict()
    points = [
        {
            "power_w": round(step.power_w, 1),
            "lactate_mmol": round(step.lactate_mmol, 2),
            "heart_rate_bpm": _round_or_none(step.hr_mean, 0),
            "cadence_rpm": _round_or_none(step.cadence_mean, 0),
        }
        for step in sorted(steps, key=lambda item: item.power_w)
    ]
    anchors = []
    for label, key in (
        ("LT1 approx 2 mmol", "aerobic_2mmol_watts"),
        ("MLSS D-max", "mlss_dmax_watts"),
        ("OBLA 4 mmol", "obla_4mmol_watts"),
    ):
        power = _finite_float(thresholds.get(key))
        if power is not None:
            anchors.append({"label": label, "power_w": round(power, 1)})
    confidence = 0.72 if len(steps) >= 5 else 0.52
    return _curve(
        curve_id="lactate",
        title="Measured lactate curve",
        x_key="power_w",
        x_unit="W",
        y_keys=[{"key": "lactate_mmol", "unit": "mmol/L", "label": "Lactate"}],
        measurement_tier=LAB_MEASURED,
        points=points,
        anchors=anchors,
        confidence_score=confidence,
        limitations=["Lactate interpretation depends on protocol, step duration and sampling timing."],
    ) | {"thresholds": thresholds}


def _energy_contribution(duration_s: float, vlamax: Optional[float]) -> Dict[str, float]:
    d = max(float(duration_s), 1.0)
    vla = vlamax if vlamax is not None else 0.45
    pcr = 100.0 * np.exp(-d / 7.0)
    glycolytic_peak = 100.0 * (d / 35.0) * np.exp(1.0 - d / 35.0)
    glycolytic = glycolytic_peak * max(0.65, min(1.35, vla / 0.45))
    oxidative = max(0.0, (d / (d + 65.0)) * 100.0)
    total = max(pcr + glycolytic + oxidative, 1e-9)
    return {
        "pcr_pct": round(pcr / total * 100.0, 1),
        "glycolytic_pct": round(glycolytic / total * 100.0, 1),
        "oxidative_pct": round(oxidative / total * 100.0, 1),
    }


def build_energy_contribution_curve(metabolic_snapshot: Dict[str, Any], durations_s: Optional[Sequence[float]] = None) -> Dict[str, Any]:
    """Return estimated PCR/glycolytic/oxidative contribution by duration."""
    durations = list(durations_s or [5, 10, 15, 30, 60, 180, 300, 600, 1200, 3600])
    vlamax = _snapshot_value(metabolic_snapshot or {}, "estimated_vlamax_mmol_L_s", "vlamax_mmol_L_s")
    points = []
    for duration in durations:
        if duration <= 0:
            continue
        contrib = _energy_contribution(float(duration), vlamax)
        points.append({"duration_s": round(float(duration), 1), **contrib})
    return _curve(
        curve_id="energy_contribution_by_duration",
        title="Energy contribution by duration",
        x_key="duration_s",
        x_unit="s",
        y_keys=[
            {"key": "pcr_pct", "unit": "%", "label": "PCR"},
            {"key": "glycolytic_pct", "unit": "%", "label": "Glycolytic"},
            {"key": "oxidative_pct", "unit": "%", "label": "Oxidative"},
        ],
        measurement_tier=HEURISTIC,
        points=points,
        anchors=[],
        confidence_score=0.58 if vlamax is not None else 0.46,
        limitations=[
            "Estimated contribution split for coach interpretation; not a direct metabolic measurement.",
            "PCR/glycolytic/oxidative percentages depend on protocol, recruitment and athlete phenotype.",
        ],
        frontend_hint={"chart_type": "line", "multi_series": True, "show_anchors": False},
    )


def build_metabolic_curves_report(
    metabolic_snapshot: Dict[str, Any],
    *,
    weight_kg: Optional[float],
    gender: Optional[str] = None,
    training_years: Optional[float] = None,
    discipline: Optional[str] = None,
    eta: Optional[float] = None,
    power_points: Optional[Sequence[float]] = None,
    lactate_steps: Optional[Sequence[Dict[str, Any]]] = None,
    durations_s: Optional[Sequence[float]] = None,
    include_curves: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Build all coach-critical metabolic curves with a stable frontend contract."""
    include = set(include_curves or ["vo2_demand", "substrate_oxidation", "lactate", "energy_contribution_by_duration"])
    curves: Dict[str, Dict[str, Any]] = {}
    if "vo2_demand" in include:
        curves["vo2_demand"] = build_vo2_demand_curve(
            metabolic_snapshot,
            weight_kg=weight_kg,
            eta=eta,
            power_points=power_points,
        )
    if "substrate_oxidation" in include:
        curves["substrate_oxidation"] = build_substrate_curve(
            metabolic_snapshot,
            weight_kg=weight_kg,
            gender=gender,
            training_years=training_years,
            discipline=discipline,
        )
    if "lactate" in include:
        curves["lactate"] = build_lactate_curve(lactate_steps)
    if "energy_contribution_by_duration" in include:
        curves["energy_contribution_by_duration"] = build_energy_contribution_curve(metabolic_snapshot, durations_s=durations_s)

    available = [name for name, curve in curves.items() if curve.get("measurement_tier") != INSUFFICIENT_DATA and curve.get("points")]
    missing = [
        {"curve": name, "reason": "; ".join(curve.get("limitations") or ["insufficient_data"])}
        for name, curve in curves.items()
        if name not in available
    ]
    confidences = [float(curve.get("confidence_score", 0.0)) for curve in curves.values() if curve.get("measurement_tier") != INSUFFICIENT_DATA]
    confidence = float(np.mean(confidences)) if confidences else 0.0
    return {
        "status": "success" if available else "insufficient_data",
        "schema_version": "metabolic_curves.v1",
        "measurement_tier": "MIXED" if available else INSUFFICIENT_DATA,
        "curves": curves,
        "available_curves": available,
        "missing_curves": missing,
        "confidence_score": round(confidence, 3),
        "db_contract": {
            "store_points": True,
            "store_model_parameters": True,
            "store_measurement_tier": True,
            "store_confidence_and_limitations": True,
        },
    }
