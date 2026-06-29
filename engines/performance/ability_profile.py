"""Ability profile from power curve, durability and workout compliance."""

from __future__ import annotations

from typing import Any, Dict, Optional

from engines.core.metric_contracts import annotate_payload, normalize_compliance_score
from engines.core.model_safety import finalize_model_metadata


def _get_curve(profile: Dict[str, Any]) -> Dict[int, float]:
    raw = profile.get("mmp") or profile.get("power_curve") or profile.get("rolling_power_curve") or {}
    if isinstance(raw, dict) and "curve" in raw:
        raw = raw.get("curve") or {}
    out: Dict[int, float] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                out[int(float(k))] = float(v)
            except Exception:
                continue
    return out


def _score(value: Optional[float], low: float, high: float) -> float:
    if value is None:
        return 0.35
    return max(0.0, min(1.0, (value - low) / max(high - low, 1e-6)))


def _nearest(curve: Dict[int, float], duration: int) -> Optional[float]:
    if duration in curve:
        return curve[duration]
    if not curve:
        return None
    k = min(curve, key=lambda d: abs(d - duration))
    return curve[k] if abs(k - duration) <= max(5, duration * 0.2) else None


def build_ability_profile(
    athlete_profile: Dict[str, Any],
    *,
    weight_kg: Optional[float] = None,
    durability: Optional[Dict[str, Any]] = None,
    compliance_history: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    assumptions: list[str] = []
    missing_inputs: list[str] = []
    quality_flags: list[str] = []
    curve = _get_curve(athlete_profile)
    weight = weight_kg or athlete_profile.get("weight_kg") or athlete_profile.get("mass_kg")
    try:
        weight = float(weight) if weight is not None else None
    except Exception:
        weight = None
    if weight is None:
        missing_inputs.append("weight_kg")
        assumptions.append("wkg_metrics_hidden_without_body_mass")
    elif weight < 35.0 or weight > 160.0:
        quality_flags.append("weight_out_of_plausible_range")
    cp = athlete_profile.get("cp_w") or athlete_profile.get("critical_power_w") or _nearest(curve, 1200)
    ftp = athlete_profile.get("ftp_w") or athlete_profile.get("ftp") or cp
    if cp is None:
        missing_inputs.append("cp_w_or_power_curve_1200s")
    wkg_den = weight if weight and weight > 0 else None
    sprint = ((_nearest(curve, 5) or 0) / wkg_den) if wkg_den else None
    one_min = ((_nearest(curve, 60) or 0) / wkg_den) if wkg_den else None
    five_min = ((_nearest(curve, 300) or 0) / wkg_den) if wkg_den else None
    twenty_min = ((_nearest(curve, 1200) or 0) / wkg_den) if wkg_den else None
    sixty_min = ((_nearest(curve, 3600) or 0) / wkg_den) if wkg_den else None
    durability_score = None
    if durability:
        durability_score = durability.get("durability_score") or durability.get("score")
    levels = {
        "sprint": round(_score(sprint, 8.0, 20.0) * 10, 1),
        "anaerobic": round(_score(one_min, 4.5, 10.0) * 10, 1),
        "vo2": round(_score(five_min, 3.5, 7.0) * 10, 1),
        "threshold": round(_score(twenty_min, 2.5, 5.8) * 10, 1),
        "endurance": round(_score(sixty_min, 2.0, 5.0) * 10, 1),
        "durability": round(_score(float(durability_score) if durability_score is not None else None, 0.4, 0.9) * 10, 1),
    }
    completed = [c for c in (compliance_history or []) if isinstance(c, dict)]
    compliance_score = None
    if completed:
        vals = []
        for c in completed[-12:]:
            val = c.get("compliance_score") or c.get("score")
            try:
                vals.append(float(val))
            except Exception:
                pass
        if vals:
            compliance_score = sum(vals) / len(vals)
            mean_norm = normalize_compliance_score(compliance_score) or 0.0
            levels["execution_consistency"] = round(mean_norm * 10, 1)
    phenotype = max(levels, key=levels.get)
    wkg_payload = {
        "5s": round(sprint, 2) if sprint else None,
        "60s": round(one_min, 2) if one_min else None,
        "300s": round(five_min, 2) if five_min else None,
        "1200s": round(twenty_min, 2) if twenty_min else None,
        "3600s": round(sixty_min, 2) if sixty_min else None,
    }
    payload = {
        "status": "success",
        "schema_version": "1.0.0",
        "levels": levels,
        "dominant_ability": phenotype,
        "inputs": {"weight_kg": weight, "cp_w": cp, "ftp_w": ftp, "curve_points": len(curve)},
        "derived_w_kg": wkg_payload,
        "raw_wkg": wkg_payload,
        "model_metadata": finalize_model_metadata(
            assumptions=assumptions,
            missing_inputs=missing_inputs,
            quality_flags=quality_flags,
            confidence=0.85 if len(curve) >= 4 and wkg_den else 0.52,
        ),
    }
    return annotate_payload(
        payload,
        module_name="ability_profile",
        method="power_curve_levels",
        confidence=payload["model_metadata"]["confidence_score"],
    )
