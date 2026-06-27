"""FATmax report engine.

Produces coach-facing FATmax reports in two strictly separated modes:

- LAB_MEASURED: VO2/VCO2 data are available and substrate oxidation is computed
  with non-protein stoichiometric equations.
- MODEL_ESTIMATE: only a metabolic snapshot / field-derived profile is available;
  FATmax, MFO and substrate curves are labelled as estimates/proxies.

The engine never presents field estimates as indirect-calorimetry measurements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from engines.core.science_contracts import fatmax_contract_fields, fatmax_limitations

# Scientific constants — see docs/FATMAX_PROTOCOL.md and docs/SCIENTIFIC_REFERENCES.md
IC_FAT_VO2_COEF = 1.695
IC_FAT_VCO2_COEF = 1.701
IC_CHO_VCO2_COEF = 4.585
IC_CHO_VO2_COEF = 3.226

FATMAX_MLSS_RATIO = 0.68
MAP_MLSS_RATIO = 1.35

FATMAX_BASE_THRESHOLD_FRACTION_DEFAULT = 0.80

FATMAX_SHIFT_RIGHT_THRESHOLD_W = 8.0
FATMAX_SHIFT_LEFT_THRESHOLD_W = -8.0
FATMAX_BASE_WIDTH_INCREASE_THRESHOLD_W = 10.0
FATMAX_BASE_WIDTH_DECREASE_THRESHOLD_W = -10.0

FATMAX_COACH_WIDTH_WIDE_W = 45.0
FATMAX_COACH_WIDTH_MODERATE_W = 25.0
FATMAX_WIDTH_WIDE_RATIO_MLSS = 0.22
FATMAX_WIDTH_MODERATE_RATIO_MLSS = 0.12

_CROSSOVER_LAB_METHOD = "indirect_calorimetry_g_min"
_CROSSOVER_LAB_DESCRIPTION = (
    "Power where carbohydrate oxidation (g/min) equals or exceeds fat oxidation (g/min) "
    "from stepped VO2/VCO2 data."
)
_CROSSOVER_MODEL_METHOD = "model_proxy_fraction"
_CROSSOVER_MODEL_DESCRIPTION = (
    "Power where the model carbohydrate proxy equals or exceeds the fat proxy. "
    "Not indirect calorimetry — do not present as a measured crossover."
)

MeasurementTier = str
LAB_MEASURED: MeasurementTier = "LAB_MEASURED"
MODEL_ESTIMATE: MeasurementTier = "MODEL_ESTIMATE"
INSUFFICIENT_DATA: MeasurementTier = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class GasExchangePoint:
    """One indirect-calorimetry step."""

    power_w: float
    vo2_l_min: float
    vco2_l_min: float
    rer: Optional[float] = None
    heart_rate_bpm: Optional[float] = None


@dataclass(frozen=True)
class FatmaxShift:
    """Comparison between two FATmax reports."""

    delta_fatmax_w: Optional[float]
    delta_mfo_g_min: Optional[float]
    delta_base_width_w: Optional[float]
    direction: str
    interpretation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.delta_fatmax_w is not None,
            "delta_fatmax_w": _round_or_none(self.delta_fatmax_w, 1),
            "delta_mfo_g_min": _round_or_none(self.delta_mfo_g_min, 3),
            "delta_base_width_w": _round_or_none(self.delta_base_width_w, 1),
            "direction": self.direction,
            "interpretation": self.interpretation,
        }


def _finite_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _clamp(value: float, lo: float, hi: float) -> float:
    return float(min(hi, max(lo, value)))


def _round_or_none(value: Optional[float], digits: int = 1) -> Optional[float]:
    return round(value, digits) if value is not None and np.isfinite(value) else None


def substrate_oxidation_from_vo2_vco2(vo2_l_min: float, vco2_l_min: float) -> Dict[str, Any]:
    """Compute non-protein fat/CHO oxidation from VO2 and VCO2.

    Standard non-protein stoichiometric equations used in indirect calorimetry:
    fat_g_min = 1.695 * VO2 - 1.701 * VCO2
    carbohydrate_g_min = 4.585 * VCO2 - 3.226 * VO2
    """
    vo2 = float(vo2_l_min)
    vco2 = float(vco2_l_min)
    if vo2 <= 0 or vco2 <= 0 or not np.isfinite(vo2 + vco2):
        return {"status": "invalid_data", "fat_g_min": None, "carbohydrate_g_min": None, "rer": None}
    fat = max(0.0, IC_FAT_VO2_COEF * vo2 - IC_FAT_VCO2_COEF * vco2)
    cho = max(0.0, IC_CHO_VCO2_COEF * vco2 - IC_CHO_VO2_COEF * vo2)
    return {
        "status": "success",
        "fat_g_min": round(fat, 4),
        "carbohydrate_g_min": round(cho, 4),
        "rer": round(vco2 / vo2, 3),
    }


def _fatmax_base_from_curve(
    points: Sequence[Dict[str, Any]],
    *,
    fat_key: str,
    threshold_fraction: float = 0.80,
    mlss_power_w: Optional[float] = None,
) -> Dict[str, Any]:
    valid: List[Tuple[float, float]] = []
    for point in points:
        power = _finite_float(point.get("power_w"))
        fat = _finite_float(point.get(fat_key))
        if power is not None and fat is not None:
            valid.append((power, fat))
    valid.sort(key=lambda item: item[0])
    if len(valid) < 2:
        return {"available": False, "reason": "insufficient_curve_points"}

    peak = max(fat for _, fat in valid)
    if peak <= 0:
        return {"available": False, "reason": "non_positive_peak"}
    selected = [(p, f) for p, f in valid if f >= peak * threshold_fraction]
    if not selected:
        return {"available": False, "reason": "no_points_above_cutoff"}

    lower = min(p for p, _ in selected)
    upper = max(p for p, _ in selected)
    width = max(0.0, upper - lower)
    return {
        "available": True,
        "threshold_fraction_of_peak": round(threshold_fraction, 2),
        "lower_w": round(lower, 1),
        "upper_w": round(upper, 1),
        "width_w": round(width, 1),
        "width_pct_mlss": round(width / mlss_power_w, 3) if mlss_power_w and mlss_power_w > 0 else None,
        "interpretation": _interpret_base_width(width, mlss_power_w),
    }


def _interpret_base_width(width_w: float, mlss_power_w: Optional[float]) -> str:
    if not mlss_power_w or mlss_power_w <= 0:
        return "FATmax base width computed; compare longitudinally on the same protocol."
    ratio = width_w / mlss_power_w
    if ratio >= FATMAX_WIDTH_WIDE_RATIO_MLSS:
        return "Wide base: useful lipid zone is stable across a broad power range."
    if ratio >= FATMAX_WIDTH_MODERATE_RATIO_MLSS:
        return "Moderate base: lipid zone is usable but can still be widened."
    return "Narrow base: prioritize aerobic-base work and controlled validation."


def _carb_crossover(points: Sequence[Dict[str, Any]], *, fat_key: str, carb_key: str) -> Optional[float]:
    rows: List[Tuple[float, float, float]] = []
    for point in points:
        power = _finite_float(point.get("power_w"))
        fat = _finite_float(point.get(fat_key))
        carb = _finite_float(point.get(carb_key))
        if power is not None and fat is not None and carb is not None:
            rows.append((power, fat, carb))
    rows.sort(key=lambda item: item[0])
    for power, fat, carb in rows:
        if carb >= fat:
            return power
    return None


def _carbohydrate_crossover_block(
    power_w: Optional[float],
    *,
    method: str,
    description: str,
) -> Dict[str, Any]:
    rounded = _round_or_none(power_w, 1)
    return {"power_w": rounded, "method": method, "description": description}


def _finalize_fatmax_report(report: Dict[str, Any]) -> Dict[str, Any]:
    tier = str(report.get("measurement_tier") or INSUFFICIENT_DATA)
    report.update(fatmax_contract_fields(measurement_tier=tier))
    contract_limits = fatmax_limitations(measurement_tier=tier)
    existing = list(report.get("limitations") or [])
    report["limitations"] = list(dict.fromkeys(existing + contract_limits))
    return report


def build_lab_fatmax_report(
    points: Sequence[GasExchangePoint],
    *,
    athlete_weight_kg: Optional[float] = None,
    mlss_power_w: Optional[float] = None,
    map_power_w: Optional[float] = None,
    threshold_fraction: float = FATMAX_BASE_THRESHOLD_FRACTION_DEFAULT,
) -> Dict[str, Any]:
    """Build a measured FATmax report from VO2/VCO2 steps."""
    if len(points) < 3:
        return {
            "status": "insufficient_data",
            "schema_version": "fatmax_report.v1",
            "measurement_tier": INSUFFICIENT_DATA,
            "reason": "at_least_three_gas_exchange_points_required",
            "confidence_score": 0.0,
        }

    curve: List[Dict[str, Any]] = []
    warnings: List[Dict[str, str]] = []
    for item in sorted(points, key=lambda p: p.power_w):
        ox = substrate_oxidation_from_vo2_vco2(item.vo2_l_min, item.vco2_l_min)
        if ox["status"] != "success":
            warnings.append({"severity": "high", "type": "invalid_gas_point", "message": f"Invalid VO2/VCO2 at {item.power_w} W."})
            continue
        derived_rer = ox["rer"]
        provided_rer = _finite_float(item.rer)
        if provided_rer is not None and abs(provided_rer - float(derived_rer)) > 0.04:
            warnings.append({"severity": "medium", "type": "rer_mismatch", "message": f"Provided RER differs from VO2/VCO2-derived RER at {item.power_w} W."})
        curve.append({
            "power_w": round(float(item.power_w), 1),
            "fat_g_min": ox["fat_g_min"],
            "carbohydrate_g_min": ox["carbohydrate_g_min"],
            "rer": provided_rer if provided_rer is not None else derived_rer,
            "heart_rate_bpm": _round_or_none(item.heart_rate_bpm, 0),
        })

    if len(curve) < 3:
        return {
            "status": "insufficient_data",
            "schema_version": "fatmax_report.v1",
            "measurement_tier": INSUFFICIENT_DATA,
            "reason": "too_few_valid_gas_exchange_points",
            "warnings": warnings,
            "confidence_score": 0.0,
        }

    peak_point = max(curve, key=lambda row: float(row["fat_g_min"] or 0.0))
    fatmax_power = float(peak_point["power_w"])
    mfo = float(peak_point["fat_g_min"] or 0.0)
    base = _fatmax_base_from_curve(curve, fat_key="fat_g_min", threshold_fraction=threshold_fraction, mlss_power_w=mlss_power_w)
    crossover = _carb_crossover(curve, fat_key="fat_g_min", carb_key="carbohydrate_g_min")

    confidence = 0.90
    if len(curve) < 5:
        confidence -= 0.08
    if warnings:
        confidence -= min(0.12, 0.03 * len(warnings))
    if mfo <= 0:
        confidence = 0.35

    report = {
        "status": "success",
        "schema_version": "fatmax_report.v1",
        "measurement_tier": LAB_MEASURED,
        "summary": {
            "fatmax_power_w": round(fatmax_power, 1),
            "fatmax_power_wkg": round(fatmax_power / athlete_weight_kg, 2) if athlete_weight_kg and athlete_weight_kg > 0 else None,
            "fatmax_pct_mlss": round(fatmax_power / mlss_power_w, 3) if mlss_power_w and mlss_power_w > 0 else None,
            "mfo_g_min": round(mfo, 3),
            "mfo_tier": "measured_from_vo2_vco2",
            "mlss_power_w": _round_or_none(mlss_power_w, 1),
            "map_power_w": _round_or_none(map_power_w, 1),
        },
        "curve": {
            "points": curve,
            "fatmax_base": base,
            "carbohydrate_crossover_w": _round_or_none(crossover, 1),
            "carbohydrate_crossover": _carbohydrate_crossover_block(
                crossover,
                method=_CROSSOVER_LAB_METHOD,
                description=_CROSSOVER_LAB_DESCRIPTION,
            ),
        },
        "coach_interpretation": _coach_interpretation(fatmax_power, mfo, base, LAB_MEASURED),
        "confidence_score": round(_clamp(confidence, 0.0, 0.95), 3),
        "data_sources": ["VO2", "VCO2", "power_steps"],
        "warnings": warnings,
        "limitations": [
            "Protein oxidation is assumed negligible.",
            "Lab values depend on protocol, step duration, analyzer calibration and pre-test nutrition.",
        ],
    }
    return _finalize_fatmax_report(report)


def build_model_fatmax_report(
    metabolic_snapshot: Dict[str, Any],
    *,
    athlete_weight_kg: Optional[float] = None,
    gender: Optional[str] = None,
    training_years: Optional[float] = None,
    discipline: Optional[str] = None,
    recent_training_status: Optional[str] = None,
    environment_context: Optional[Dict[str, Any]] = None,
    nutrition_context: Optional[Dict[str, Any]] = None,
    previous_report: Optional[Dict[str, Any]] = None,
    threshold_fraction: float = FATMAX_BASE_THRESHOLD_FRACTION_DEFAULT,
) -> Dict[str, Any]:
    """Build a model-estimated FATmax report from a metabolic snapshot."""
    snapshot = metabolic_snapshot or {}
    fatmax = _finite_float(snapshot.get("fatmax_power_watts") or snapshot.get("fatmax_power_w"))
    mlss = _finite_float(snapshot.get("mlss_power_watts") or snapshot.get("mlss_power_w"))
    map_power = _finite_float(snapshot.get("map_aerobic_watts") or snapshot.get("map_power_w"))
    vo2max = _finite_float(snapshot.get("estimated_vo2max"))
    vlamax = _finite_float(snapshot.get("estimated_vlamax_mmol_L_s"))

    if fatmax is None and mlss is not None:
        fatmax = mlss * FATMAX_MLSS_RATIO
    if mlss is None and fatmax is not None:
        mlss = fatmax / FATMAX_MLSS_RATIO
    if map_power is None and mlss is not None:
        map_power = mlss * MAP_MLSS_RATIO
    if fatmax is None or mlss is None or map_power is None or fatmax <= 0 or mlss <= 0:
        return {
            "status": "insufficient_data",
            "schema_version": "fatmax_report.v1",
            "measurement_tier": INSUFFICIENT_DATA,
            "reason": "fatmax_or_mlss_unavailable",
            "confidence_score": 0.0,
            "limitations": ["Requires FATmax or MLSS-derived metabolic snapshot."],
        }

    estimated_mfo = _estimate_mfo_g_min(
        athlete_weight_kg=athlete_weight_kg,
        vo2max=vo2max,
        vlamax=vlamax,
        gender=gender,
        training_years=training_years,
        discipline=discipline,
    )
    curve = _model_curve(
        fatmax_power_w=fatmax,
        mfo_g_min=estimated_mfo,
        mlss_power_w=mlss,
        map_power_w=map_power,
        vlamax=vlamax,
    )
    base = _fatmax_base_from_curve(curve, fat_key="fat_oxidation_g_min_est", threshold_fraction=threshold_fraction, mlss_power_w=mlss)
    crossover = _carb_crossover(curve, fat_key="fat_oxidation_proxy", carb_key="carbohydrate_oxidation_proxy")
    current = {
        "summary": {"fatmax_power_w": round(fatmax, 1), "mfo_g_min": round(estimated_mfo, 3)},
        "curve": {"fatmax_base": base},
    }
    shift = compare_fatmax_reports(previous_report, current) if previous_report else _empty_shift()
    factors = _influencing_factors(
        gender=gender,
        training_years=training_years,
        discipline=discipline,
        recent_training_status=recent_training_status,
        environment_context=environment_context,
        nutrition_context=nutrition_context,
    )
    confidence = _model_confidence(snapshot, fatmax=fatmax, mlss=mlss, map_power=map_power, vlamax=vlamax)

    report = {
        "status": "success",
        "schema_version": "fatmax_report.v1",
        "measurement_tier": MODEL_ESTIMATE,
        "summary": {
            "fatmax_power_w": round(fatmax, 1),
            "fatmax_power_wkg": round(fatmax / athlete_weight_kg, 2) if athlete_weight_kg and athlete_weight_kg > 0 else None,
            "fatmax_pct_mlss": round(fatmax / mlss, 3) if mlss > 0 else None,
            "mfo_g_min": round(estimated_mfo, 3),
            "mfo_tier": "estimated_model_proxy_not_gas_exchange",
            "mlss_power_w": _round_or_none(mlss, 1),
            "map_power_w": _round_or_none(map_power, 1),
            "estimated_vo2max": _round_or_none(vo2max, 1),
            "estimated_vlamax_mmol_L_s": _round_or_none(vlamax, 3),
        },
        "curve": {
            "points": curve,
            "fatmax_base": base,
            "carbohydrate_crossover_w": _round_or_none(crossover, 1),
            "carbohydrate_crossover": _carbohydrate_crossover_block(
                crossover,
                method=_CROSSOVER_MODEL_METHOD,
                description=_CROSSOVER_MODEL_DESCRIPTION,
            ),
        },
        "shift": shift.to_dict(),
        "influencing_factors": factors,
        "coach_interpretation": _coach_interpretation(fatmax, estimated_mfo, base, MODEL_ESTIMATE),
        "confidence_score": round(confidence, 3),
        "data_sources": ["metabolic_snapshot", "MMP_or_field_model"],
        "limitations": [
            "MFO g/min is estimated, not measured by indirect calorimetry.",
            "Nutrition and glycogen status are not directly known unless supplied.",
            "Environmental effects are not applied unless supplied as context.",
        ],
    }
    return _finalize_fatmax_report(report)


def _estimate_mfo_g_min(
    *,
    athlete_weight_kg: Optional[float],
    vo2max: Optional[float],
    vlamax: Optional[float],
    gender: Optional[str],
    training_years: Optional[float],
    discipline: Optional[str],
) -> float:
    weight = athlete_weight_kg if athlete_weight_kg and athlete_weight_kg > 0 else 72.0
    mfo = 0.0080 * weight
    if vo2max is not None:
        mfo *= _clamp(0.86 + (vo2max - 45.0) * 0.012, 0.78, 1.22)
    if vlamax is not None:
        mfo *= _clamp(1.0 - (vlamax - 0.45) * 0.42, 0.72, 1.18)
    if training_years is not None:
        mfo *= _clamp(0.94 + min(max(training_years, 0.0), 15.0) * 0.009, 0.94, 1.08)
    if gender and gender.upper().startswith("F"):
        mfo *= 1.04
    if discipline and discipline.upper() in {"TT", "TT_CLIMBER", "ENDURANCE", "ROAD", "CLIMBER"}:
        mfo *= 1.04
    if discipline and discipline.upper() in {"SPRINT", "TRACK_SPRINT"}:
        mfo *= 0.92
    return round(_clamp(mfo, 0.18, 1.35), 3)


def _model_curve(
    *,
    fatmax_power_w: float,
    mfo_g_min: float,
    mlss_power_w: float,
    map_power_w: float,
    vlamax: Optional[float],
) -> List[Dict[str, Any]]:
    lower = max(40.0, fatmax_power_w * 0.45)
    upper = max(fatmax_power_w * 1.75, mlss_power_w * 1.15, min(map_power_w, fatmax_power_w * 2.25))
    powers = np.linspace(lower, upper, 15)
    vla = vlamax if vlamax is not None else 0.45
    left_sigma = fatmax_power_w * _clamp(0.55 - (vla - 0.45) * 0.10, 0.42, 0.66)
    right_sigma = fatmax_power_w * _clamp(0.34 - (vla - 0.45) * 0.12, 0.22, 0.44)
    crossover_anchor = fatmax_power_w + (mlss_power_w - fatmax_power_w) * _clamp(0.55 - (vla - 0.45) * 0.18, 0.35, 0.70)

    rows: List[Dict[str, Any]] = []
    for power in powers:
        sigma = left_sigma if power <= fatmax_power_w else right_sigma
        fat_fraction = float(np.exp(-0.5 * ((power - fatmax_power_w) / max(sigma, 1.0)) ** 2))
        fat_g_min = mfo_g_min * fat_fraction
        carb_norm = 1.0 / (1.0 + np.exp(-(power - crossover_anchor) / max(mlss_power_w * 0.12, 10.0)))
        carb_g_min = (0.22 + 2.4 * carb_norm) * _clamp(power / max(mlss_power_w, 1.0), 0.35, 1.45)
        rows.append({
            "power_w": round(float(power), 1),
            "fat_oxidation_proxy": round(fat_fraction, 4),
            "carbohydrate_oxidation_proxy": round(float(carb_norm), 4),
            "fat_oxidation_g_min_est": round(float(fat_g_min), 3),
            "carbohydrate_oxidation_g_min_est": round(float(carb_g_min), 3),
        })
    return rows


def _model_confidence(
    snapshot: Dict[str, Any],
    *,
    fatmax: Optional[float],
    mlss: Optional[float],
    map_power: Optional[float],
    vlamax: Optional[float],
) -> float:
    confidence = 0.50
    confidence += 0.12 if snapshot.get("status") == "success" else 0.0
    confidence += 0.09 if fatmax is not None else 0.0
    confidence += 0.08 if mlss is not None else 0.0
    confidence += 0.06 if map_power is not None else 0.0
    confidence += 0.05 if vlamax is not None else 0.0
    confidence += 0.04 if snapshot.get("confidence_score") else 0.0
    expressiveness = snapshot.get("expressiveness") or {}
    reliability = expressiveness.get("reliability") if isinstance(expressiveness, dict) else {}
    if isinstance(reliability, dict):
        confidence += 0.03 if reliability.get("mlss") else 0.0
        confidence += 0.02 if reliability.get("vo2max") else 0.0
    return _clamp(confidence, 0.35, 0.82)


def _influencing_factors(
    *,
    gender: Optional[str],
    training_years: Optional[float],
    discipline: Optional[str],
    recent_training_status: Optional[str],
    environment_context: Optional[Dict[str, Any]],
    nutrition_context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "sex": {"available": bool(gender), "value": gender, "effect": "used_in_model_prior" if gender else "not_applied"},
        "training_status": {
            "available": recent_training_status is not None or training_years is not None or discipline is not None,
            "training_years": training_years,
            "discipline": discipline,
            "recent_status": recent_training_status,
            "effect": "used_as_context" if (training_years is not None or discipline or recent_training_status) else "not_applied",
        },
        "exercise_duration_intensity": {
            "available": False,
            "effect": "not_applied_in_static_report",
            "note": "Use ride history / workout comparison endpoints for session-specific effects.",
        },
        "environment": {
            "available": bool(environment_context),
            "value": environment_context or {},
            "effect": "context_reported_not_directly_modeled" if environment_context else "not_applied",
        },
        "nutrition": {
            "available": bool(nutrition_context),
            "value": nutrition_context or {},
            "effect": "context_reported_not_directly_modeled" if nutrition_context else "not_applied",
            "limitation": "Glycogen/fed state is not inferred when not supplied.",
        },
    }


def _coach_interpretation(
    fatmax_power_w: float,
    mfo_g_min: float,
    base: Dict[str, Any],
    tier: MeasurementTier,
) -> Dict[str, Any]:
    width = _finite_float(base.get("width_w")) if base.get("available") else None
    if width is not None and width >= FATMAX_COACH_WIDTH_WIDE_W:
        goal = "maintain_or_right_shift"
        msg = "FATmax zone is relatively wide: shift it toward higher power without narrowing the base."
    elif width is not None and width >= FATMAX_COACH_WIDTH_MODERATE_W:
        goal = "increase_base_width"
        msg = "Priority is to widen the useful lipid zone, not only raise the peak."
    else:
        goal = "build_aerobic_base"
        msg = "Curve appears narrow or poorly defined: build aerobic base and validate with controlled data."
    if tier == MODEL_ESTIMATE:
        msg += " MFO and curve are model estimates, not metabolic-cart measurements."
    return {"primary_goal": goal, "message": msg, "fatmax_anchor_w": round(fatmax_power_w, 1), "mfo_g_min": round(mfo_g_min, 3)}


def _extract_summary_metric(report: Optional[Dict[str, Any]], name: str) -> Optional[float]:
    if not report:
        return None
    summary = report.get("summary") if isinstance(report, dict) else None
    if not isinstance(summary, dict):
        return None
    return _finite_float(summary.get(name))


def _extract_base_width(report: Optional[Dict[str, Any]]) -> Optional[float]:
    if not report:
        return None
    curve = report.get("curve") if isinstance(report, dict) else None
    if not isinstance(curve, dict):
        return None
    base = curve.get("fatmax_base")
    if not isinstance(base, dict):
        return None
    return _finite_float(base.get("width_w"))


def _empty_shift() -> FatmaxShift:
    return FatmaxShift(
        delta_fatmax_w=None,
        delta_mfo_g_min=None,
        delta_base_width_w=None,
        direction="not_available",
        interpretation="Previous FATmax report not supplied.",
    )


def compare_fatmax_reports(previous_report: Optional[Dict[str, Any]], current_report: Optional[Dict[str, Any]]) -> FatmaxShift:
    """Compare two FATmax reports and classify curve translation."""
    prev_fatmax = _extract_summary_metric(previous_report, "fatmax_power_w")
    curr_fatmax = _extract_summary_metric(current_report, "fatmax_power_w")
    prev_mfo = _extract_summary_metric(previous_report, "mfo_g_min")
    curr_mfo = _extract_summary_metric(current_report, "mfo_g_min")
    prev_width = _extract_base_width(previous_report)
    curr_width = _extract_base_width(current_report)

    if prev_fatmax is None or curr_fatmax is None:
        return _empty_shift()

    delta_fatmax = curr_fatmax - prev_fatmax
    delta_mfo = (curr_mfo - prev_mfo) if curr_mfo is not None and prev_mfo is not None else None
    delta_width = (curr_width - prev_width) if curr_width is not None and prev_width is not None else None
    if delta_fatmax >= FATMAX_SHIFT_RIGHT_THRESHOLD_W:
        direction = "right_shift"
        interpretation = "FATmax shifted toward higher power."
    elif delta_fatmax <= FATMAX_SHIFT_LEFT_THRESHOLD_W:
        direction = "left_shift"
        interpretation = "FATmax shifted toward lower power; check fatigue, nutrition, or aerobic-base loss."
    else:
        direction = "stable"
        interpretation = "FATmax is substantially stable; evaluate MFO and base width for adaptation."
    if delta_width is not None and delta_width > FATMAX_BASE_WIDTH_INCREASE_THRESHOLD_W:
        interpretation += " Base width increased."
    elif delta_width is not None and delta_width < FATMAX_BASE_WIDTH_DECREASE_THRESHOLD_W:
        interpretation += " Base width narrowed."

    return FatmaxShift(
        delta_fatmax_w=delta_fatmax,
        delta_mfo_g_min=delta_mfo,
        delta_base_width_w=delta_width,
        direction=direction,
        interpretation=interpretation,
    )
