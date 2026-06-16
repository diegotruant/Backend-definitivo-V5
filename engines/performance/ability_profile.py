"""Ability profile from power curve, durability and workout compliance."""

from __future__ import annotations

from typing import Any, Dict, Optional

from engines.core.metric_contracts import annotate_payload


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
    curve = _get_curve(athlete_profile)
    weight = weight_kg or athlete_profile.get("weight_kg") or athlete_profile.get("mass_kg") or 75.0
    try:
        weight = float(weight)
    except Exception:
        weight = 75.0
    cp = athlete_profile.get("cp_w") or athlete_profile.get("critical_power_w") or _nearest(curve, 1200)
    ftp = athlete_profile.get("ftp_w") or athlete_profile.get("ftp") or cp
    sprint = (_nearest(curve, 5) or 0) / weight
    one_min = (_nearest(curve, 60) or 0) / weight
    five_min = (_nearest(curve, 300) or 0) / weight
    twenty_min = (_nearest(curve, 1200) or 0) / weight
    sixty_min = (_nearest(curve, 3600) or 0) / weight
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
            levels["execution_consistency"] = round(max(0.0, min(1.0, compliance_score)) * 10, 1)
    phenotype = max(levels, key=levels.get)
    payload = {
        "status": "success",
        "schema_version": "1.0.0",
        "levels": levels,
        "dominant_ability": phenotype,
        "inputs": {"weight_kg": weight, "cp_w": cp, "ftp_w": ftp, "curve_points": len(curve)},
        "derived_w_kg": {
            "5s": round(sprint, 2) if sprint else None,
            "60s": round(one_min, 2) if one_min else None,
            "300s": round(five_min, 2) if five_min else None,
            "1200s": round(twenty_min, 2) if twenty_min else None,
            "3600s": round(sixty_min, 2) if sixty_min else None,
        },
    }
    return annotate_payload(payload, module_name="ability_profile", method="power_curve_levels", confidence=0.85 if len(curve) >= 4 else 0.45)
