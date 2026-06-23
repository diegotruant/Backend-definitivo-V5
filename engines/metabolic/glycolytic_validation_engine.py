"""
Glycolytic validation — vLaPeak (observed) vs VLamax (modelled).

Wackerhage et al. (2025) distinguish:
  - vLamax_muscle: latent Mader model parameter (estimated from MMP)
  - vLaPeak: observed blood lactate accumulation rate after a brief all-out test

This module keeps that epistemological split explicit and uses vLaPeak as an
external benchmark when capillary lactate is available (e.g. post-Wingate).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

import numpy as np

from engines.core.metric_contracts import annotate_payload

if TYPE_CHECKING:
    from engines.metabolic.metabolic_profiler import MetabolicProfiler

VLAPPEAK_VALIDATION_TOLERANCE_PCT = 25.0
_VLAMAX_INDEX_FLOOR = 0.10
_VLAMAX_INDEX_CEILING = 1.20


def compute_vlapeak_observed(
    lactate_pre_mmol: float,
    lactate_post_mmol: float,
    duration_s: float,
) -> Dict[str, Any]:
    """Wackerhage vLaPeak: Δlactate / duration (mmol·L⁻¹·s⁻¹)."""
    try:
        pre = float(lactate_pre_mmol)
        post = float(lactate_post_mmol)
        dur = float(duration_s)
    except (TypeError, ValueError):
        return {
            "status": "error",
            "reason": "invalid_lactate_inputs",
            "message": "lactate_pre_mmol, lactate_post_mmol and duration_s must be numeric.",
        }
    if dur <= 0:
        return {
            "status": "error",
            "reason": "invalid_duration",
            "message": "duration_s must be positive.",
        }
    delta = post - pre
    if delta <= 0:
        return {
            "status": "error",
            "reason": "non_positive_lactate_delta",
            "message": "Post-sprint lactate must exceed pre-test lactate for vLaPeak.",
        }
    vlapeak = delta / dur
    return {
        "status": "success",
        "vlapeak_observed_mmol_l_s": round(vlapeak, 4),
        "lactate_pre_mmol_l": round(pre, 2),
        "lactate_post_mmol_l": round(post, 2),
        "lactate_delta_mmol_l": round(delta, 2),
        "duration_s": round(dur, 1),
        "method": "wackerhage_vlapeak",
        "interpretation": (
            "Observable peak blood lactate accumulation rate; not equivalent to "
            "model VLamax (vLamax_muscle)."
        ),
    }


def glycolytic_flux_index(
    vlamax_mmol_l_s: float,
    *,
    endurance_max: float = 0.35,
    allrounder_max: float = 0.55,
) -> float:
    """0–100 scale: low = aerobic-dominant, high = glycolytic-dominant."""
    vla = float(vlamax_mmol_l_s)
    if vla <= endurance_max:
        return round(33.0 * max(0.0, (vla - _VLAMAX_INDEX_FLOOR) / max(endurance_max - _VLAMAX_INDEX_FLOOR, 1e-9)), 1)
    if vla <= allrounder_max:
        span = max(allrounder_max - endurance_max, 1e-9)
        return round(33.0 + 34.0 * (vla - endurance_max) / span, 1)
    span = max(_VLAMAX_INDEX_CEILING - allrounder_max, 1e-9)
    return round(67.0 + 33.0 * min(1.0, (vla - allrounder_max) / span), 1)


def _interpolate_carb_oxidation_g_per_h(
    combustion_curve: List[Dict[str, Any]],
    power_w: float,
) -> Optional[float]:
    if not combustion_curve or power_w <= 0:
        return None
    points = sorted(
        (
            (float(row.get("watt") or 0), float(row.get("carbOxidation") or 0))
            for row in combustion_curve
            if row.get("watt") is not None
        ),
        key=lambda x: x[0],
    )
    if not points:
        return None
    watts = np.array([p[0] for p in points], dtype=float)
    carbs = np.array([p[1] for p in points], dtype=float)
    return float(np.interp(float(power_w), watts, carbs))


def predict_vlapeak_from_snapshot(
    snapshot: Dict[str, Any],
    *,
    profiler: Optional["MetabolicProfiler"] = None,
    mmp: Optional[Dict[int, float]] = None,
) -> Dict[str, Any]:
    """Model-side vLaPeak predictions from Mader profile (not blood measurement)."""
    vlamax = snapshot.get("estimated_vlamax_mmol_L_s")
    if vlamax is None:
        unmasked = snapshot.get("unmasked_estimates") or {}
        vlamax = unmasked.get("estimated_vlamax_mmol_L_s")
    if vlamax is None:
        return {
            "status": "unavailable",
            "reason": "vlamax_not_in_snapshot",
        }

    out: Dict[str, Any] = {
        "status": "success",
        "predicted_vlapeak_mmol_l_s": round(float(vlamax), 4),
        "prediction_source": "mader_vlamax_muscle_parameter",
        "interpretation": (
            "Model glycolytic flux ceiling at ADP saturation; compare to blood "
            "vLaPeak only as a validation benchmark."
        ),
    }

    if profiler is not None and mmp:
        p_peak = float(mmp.get(1) or mmp.get(5) or 0)
        dur = 15 if mmp.get(15) else (10 if mmp.get(10) else None)
        p_mean = float(mmp.get(dur) or 0) if dur else 0.0
        if p_peak > 0 and p_mean > 0 and dur:
            map_w = snapshot.get("map_aerobic_watts")
            sprint_pred = profiler.vlamax_from_sprint(
                p_peak,
                p_mean,
                float(dur),
                vo2max_power_w=float(map_w) if map_w else None,
            )
            if sprint_pred.get("status") == "success":
                out["predicted_vlapeak_sprint_mmol_l_s"] = sprint_pred["vlamax_mmol_l_s"]
                out["predicted_vlapeak_sprint_range"] = sprint_pred.get("vlamax_range")
                out["sprint_prediction_method"] = sprint_pred.get("method")

    mlss = snapshot.get("mlss_power_watts")
    combustion = snapshot.get("combustion_curve") or []
    if mlss and combustion:
        cho = _interpolate_carb_oxidation_g_per_h(combustion, float(mlss))
        if cho is not None:
            out["predicted_glycogen_cost_g_per_h_at_mlss"] = round(cho, 1)

    return out


def build_glycolytic_profile(
    snapshot: Dict[str, Any],
    *,
    profiler: Optional["MetabolicProfiler"] = None,
    mmp: Optional[Dict[int, float]] = None,
    endurance_max: float = 0.35,
    allrounder_max: float = 0.55,
) -> Dict[str, Any]:
    """Coach-facing glycolytic contract block for metabolic snapshots."""
    if snapshot.get("status") != "success":
        return {"status": "unavailable", "reason": "snapshot_not_successful"}

    vlamax = snapshot.get("estimated_vlamax_mmol_L_s")
    if vlamax is None:
        return {"status": "unavailable", "reason": "vlamax_masked_or_missing"}

    vla = float(vlamax)
    prediction = predict_vlapeak_from_snapshot(snapshot, profiler=profiler, mmp=mmp)
    profile: Dict[str, Any] = {
        "status": "success",
        "glycolytic_flux_index": glycolytic_flux_index(
            vla,
            endurance_max=endurance_max,
            allrounder_max=allrounder_max,
        ),
        "estimated_vlamax_mmol_l_s": round(vla, 4),
        "vlamax_semantics": "model_parameter_not_direct_measurement",
        "predicted_vlapeak": prediction,
        "limitations": [
            "VLamax is a Mader model parameter (vLamax_muscle), not a direct blood measurement.",
            "Use capillary vLaPeak from a structured sprint test as an external validation anchor.",
        ],
    }
    if prediction.get("predicted_glycogen_cost_g_per_h_at_mlss") is not None:
        profile["predicted_glycogen_cost"] = {
            "at_power_w": snapshot.get("mlss_power_watts"),
            "carbohydrate_g_per_h": prediction["predicted_glycogen_cost_g_per_h_at_mlss"],
            "interpretation": (
                "Modelled carbohydrate oxidation at MLSS; higher VLamax profiles "
                "typically shift combustion toward CHO at sub-maximal powers."
            ),
        }
    return profile


def validate_vlapeak_against_model(
    *,
    vlapeak_observed_mmol_l_s: float,
    predicted_vlapeak_mmol_l_s: float,
    model_vlamax_mmol_l_s: Optional[float] = None,
    tolerance_pct: float = VLAPPEAK_VALIDATION_TOLERANCE_PCT,
) -> Dict[str, Any]:
    """Compare observed blood vLaPeak with model-predicted peak glycolytic rate."""
    observed = float(vlapeak_observed_mmol_l_s)
    predicted = float(predicted_vlapeak_mmol_l_s)
    if observed <= 0 or predicted <= 0:
        return {
            "status": "error",
            "reason": "non_positive_rates",
            "message": "Observed and predicted vLaPeak must be positive.",
        }

    error = predicted - observed
    error_pct = 100.0 * error / observed
    abs_error_pct = abs(error_pct)
    validated = abs_error_pct <= tolerance_pct

    if validated:
        verdict = (
            f"Glycolytic model VALIDATED. Predicted peak rate ({predicted:.3f}) "
            f"matches observed vLaPeak ({observed:.3f} mmol·L⁻¹·s⁻¹) within "
            f"{tolerance_pct:.0f}% (error {error_pct:+.1f}%)."
        )
        severity = "none"
        action = "Model VLamax is consistent with the sprint lactate response."
    elif abs_error_pct <= 2 * tolerance_pct:
        verdict = (
            f"Glycolytic model NOT fully validated. Predicted ({predicted:.3f}) "
            f"vs observed vLaPeak ({observed:.3f}) differs by {error_pct:+.1f}%."
        )
        severity = "moderate"
        action = "Review sprint quality, lactate sampling timing, and MMP sprint anchors."
    else:
        verdict = (
            f"Glycolytic model MISMATCH. Predicted ({predicted:.3f}) vs observed "
            f"vLaPeak ({observed:.3f}) differs by {error_pct:+.1f}% — exceeds "
            f"{tolerance_pct:.0f}% tolerance."
        )
        severity = "high"
        action = (
            "Repeat structured sprint with standardized lactate sampling; "
            "consider re-fitting metabolic profile or updating measured anchor."
        )

    return {
        "status": "success",
        "validated": validated,
        "severity": severity,
        "verdict": verdict,
        "recommended_action": action,
        "vlapeak_observed_mmol_l_s": round(observed, 4),
        "predicted_vlapeak_mmol_l_s": round(predicted, 4),
        "model_vlamax_mmol_l_s": round(float(model_vlamax_mmol_l_s), 4) if model_vlamax_mmol_l_s else None,
        "error_mmol_l_s": round(error, 4),
        "error_pct": round(error_pct, 1),
        "tolerance_pct": tolerance_pct,
        "epistemology": {
            "observed": "vLaPeak (blood, Wackerhage 2025)",
            "predicted": "Mader model peak glycolytic rate (vLamax_muscle parameter or sprint decomposition)",
        },
    }


def validate_wingate_glycolytic(
    *,
    lactate_pre_mmol: float,
    lactate_post_mmol: float,
    duration_s: float,
    peak_power_w: float,
    mean_power_w: float,
    profiler: "MetabolicProfiler",
    mmp: Optional[Dict[int, float]] = None,
    snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full Wingate + lactate validation envelope."""
    observed_block = compute_vlapeak_observed(lactate_pre_mmol, lactate_post_mmol, duration_s)
    if observed_block.get("status") != "success":
        return annotate_payload(
            observed_block,
            module_name="glycolytic_validation_engine",
            method="validate_wingate_glycolytic",
            confidence=0.0,
        )

    observed = float(observed_block["vlapeak_observed_mmol_l_s"])

    sprint_pred: Dict[str, Any] = {}
    if snapshot is None and mmp:
        snapshot = profiler.generate_metabolic_snapshot(mmp)
    elif snapshot is None:
        snapshot = {"status": "skipped", "reason": "no_mmp_for_model_snapshot"}

    predicted = None
    model_vlamax = None
    if snapshot.get("status") == "success":
        model_vlamax = snapshot.get("estimated_vlamax_mmol_L_s")
        sprint_pred = profiler.vlamax_from_sprint(
            float(peak_power_w),
            float(mean_power_w),
            float(duration_s),
            vo2max_power_w=snapshot.get("map_aerobic_watts"),
        )
        if sprint_pred.get("status") == "success":
            predicted = float(sprint_pred["vlamax_mmol_l_s"])
        elif model_vlamax is not None:
            predicted = float(model_vlamax)
    else:
        sprint_pred = profiler.vlamax_from_sprint(
            float(peak_power_w),
            float(mean_power_w),
            float(duration_s),
        )
        if sprint_pred.get("status") == "success":
            predicted = float(sprint_pred["vlamax_mmol_l_s"])

    if predicted is None:
        return annotate_payload(
            {
                "status": "insufficient_data",
                "reason": "prediction_unavailable",
                "message": "Could not derive a model vLaPeak prediction from sprint power or MMP.",
                "vlapeak_observed": observed_block,
                "sprint_decomposition": sprint_pred or None,
            },
            module_name="glycolytic_validation_engine",
            method="validate_wingate_glycolytic",
            confidence=0.2,
        )

    comparison = validate_vlapeak_against_model(
        vlapeak_observed_mmol_l_s=observed,
        predicted_vlapeak_mmol_l_s=predicted,
        model_vlamax_mmol_l_s=model_vlamax,
    )

    payload = {
        "status": "success",
        "vlapeak_observed": observed_block,
        "model_prediction": {
            "predicted_vlapeak_mmol_l_s": round(predicted, 4),
            "model_vlamax_mmol_l_s": round(float(model_vlamax), 4) if model_vlamax else None,
            "sprint_decomposition": sprint_pred if sprint_pred.get("status") == "success" else None,
        },
        "validation": comparison,
        "glycolytic_profile": (
            build_glycolytic_profile(snapshot, profiler=profiler, mmp=mmp)
            if snapshot.get("status") == "success"
            else None
        ),
    }
    conf = 0.85 if comparison.get("validated") else 0.55
    return annotate_payload(
        payload,
        module_name="glycolytic_validation_engine",
        method="validate_wingate_glycolytic",
        confidence=conf,
    )
