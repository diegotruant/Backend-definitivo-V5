"""Workout feasibility engine.

V1 answers the pre-assignment question: can this athlete plausibly complete the
planned workout based on CP and W′?  It is intentionally stateless and returns a
JSON-serialisable report for DB persistence and frontend display.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from engines.core.science_contracts import TauModel, resolve_w_prime_tau
from .models import WorkoutDefinition, normalize_workout


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _recovery_tau_s(cp_w: float, power_w: float) -> float:
    """Heuristic W′ recovery time constant.

    Easier recoveries refill W′ faster; recoveries close to CP refill it slowly.
    The clamp keeps the V1 stable across odd inputs without claiming lab-level
    precision.
    """
    reserve = max(0.0, cp_w - power_w)
    if cp_w <= 0:
        return 600.0
    tau = 120.0 + 780.0 * math.exp(-4.0 * reserve / cp_w)
    return max(120.0, min(900.0, tau))


def _step_power(step, athlete_profile: Dict[str, Any]) -> Optional[float]:
    return step.resolved_target_power_w(athlete_profile)


def analyze_workout_feasibility(
    workout_payload: Dict[str, Any],
    athlete_profile: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    *,
    tau_model: Optional[TauModel] = None,
) -> Dict[str, Any]:
    """Simulate planned workout against athlete CP/W′ and return feasibility."""
    workout: WorkoutDefinition = normalize_workout(workout_payload)
    context = context or {}

    resolved_tau_s: Optional[float] = None
    resolved_tau_model: Optional[TauModel] = None
    if tau_model:
        resolved_tau_s, resolved_tau_model = resolve_w_prime_tau(
            tau_model,
            athlete_profile=athlete_profile,
            athlete_level=athlete_profile.get("level") or athlete_profile.get("athlete_level"),
        )

    cp_w = _num(athlete_profile.get("cp_w") or athlete_profile.get("critical_power_w"))
    w_prime_j = _num(athlete_profile.get("w_prime_j") or athlete_profile.get("wprime_j") or athlete_profile.get("w_prime"))
    ftp_w = _num(athlete_profile.get("ftp_w") or athlete_profile.get("ftp"))
    weight_kg = _num(athlete_profile.get("weight_kg"))

    warnings: List[Dict[str, Any]] = []
    recommendations: List[Dict[str, Any]] = []

    if cp_w is None and ftp_w is not None:
        # Conservative fallback so the UI can still provide feedback while making
        # the lower confidence explicit.
        cp_w = ftp_w * 1.03
        warnings.append({
            "severity": "medium",
            "type": "cp_estimated_from_ftp",
            "message": "CP not provided; estimated as FTP × 1.03. Feasibility confidence reduced.",
        })
    if w_prime_j is None:
        warnings.append({
            "severity": "high",
            "type": "missing_w_prime",
            "message": "W′ not provided; cannot simulate anaerobic capacity depletion.",
        })
        return {
            "status": "insufficient_data",
            "feasibility_score": None,
            "confidence_score": 0.25 if cp_w else 0.1,
            "classification": "unknown",
            "limiting_factor": "missing_w_prime",
            "summary": {
                "cp_w": cp_w,
                "w_prime_j": None,
                "planned_duration_s": workout.duration_s,
                "weight_kg": weight_kg,
            },
            "warnings": warnings,
            "recommendations": [{
                "type": "provide_profile",
                "message": "An athlete profile with CP and W′ is required to assess workout feasibility.",
            }],
            "step_analysis": [],
        }
    if cp_w is None or cp_w <= 0:
        warnings.append({
            "severity": "high",
            "type": "missing_cp",
            "message": "CP not provided; cannot decide which parts are above critical power.",
        })
        return {
            "status": "insufficient_data",
            "feasibility_score": None,
            "confidence_score": 0.15,
            "classification": "unknown",
            "limiting_factor": "missing_cp",
            "summary": {"cp_w": None, "w_prime_j": w_prime_j, "planned_duration_s": workout.duration_s},
            "warnings": warnings,
            "recommendations": [{"type": "provide_profile", "message": "CP is required to simulate W′bal."}],
            "step_analysis": [],
        }

    wbal = float(w_prime_j)
    min_wbal = wbal
    total_above_cp_j = 0.0
    seconds_below_10pct = 0
    seconds_depleted = 0
    hardest_step_id: Optional[str] = None
    step_analysis: List[Dict[str, Any]] = []
    elapsed = 0

    for step in workout.steps:
        p = _step_power(step, athlete_profile)
        start_wbal = wbal
        step_cost = 0.0
        step_min = wbal
        if p is None:
            step_analysis.append({
                "step_id": step.step_id,
                "type": step.type,
                "duration_s": step.duration_s,
                "target_power_w": None,
                "status": "not_simulated",
                "reason": "NO_POWER_TARGET",
            })
            elapsed += step.duration_s
            continue

        # One-second simulation is simple and robust for structured workout sizes.
        for _ in range(step.duration_s):
            if p > cp_w:
                drain = p - cp_w
                wbal -= drain
                step_cost += drain
                total_above_cp_j += drain
            else:
                if resolved_tau_s is not None:
                    tau = resolved_tau_s
                else:
                    tau = _recovery_tau_s(cp_w, p)
                wbal += (float(w_prime_j) - wbal) * (1.0 - math.exp(-1.0 / tau))
            wbal = max(0.0, min(float(w_prime_j), wbal))
            step_min = min(step_min, wbal)
            min_wbal = min(min_wbal, wbal)
            if wbal <= 0.10 * float(w_prime_j):
                seconds_below_10pct += 1
            if wbal <= 0.0:
                seconds_depleted += 1

        if hardest_step_id is None or step_min < min(s.get("min_w_prime_balance_j", float(w_prime_j)) for s in step_analysis if isinstance(s.get("min_w_prime_balance_j"), (int, float)) or [float(w_prime_j)]):
            hardest_step_id = step.step_id
        end_pct = 100.0 * wbal / float(w_prime_j)
        min_pct = 100.0 * step_min / float(w_prime_j)
        if step_min <= 0.05 * float(w_prime_j):
            status = "not_feasible"
        elif step_min <= 0.20 * float(w_prime_j):
            status = "risky"
        elif step_min <= 0.35 * float(w_prime_j):
            status = "caution"
        else:
            status = "feasible"

        step_analysis.append({
            "step_id": step.step_id,
            "type": step.type,
            "start_s": elapsed,
            "duration_s": step.duration_s,
            "target_power_w": round(p, 1),
            "start_w_prime_balance_j": round(start_wbal, 1),
            "end_w_prime_balance_j": round(wbal, 1),
            "end_w_prime_balance_pct": round(end_pct, 1),
            "min_w_prime_balance_j": round(step_min, 1),
            "min_w_prime_balance_pct": round(min_pct, 1),
            "w_prime_cost_j": round(step_cost, 1),
            "status": status,
        })
        elapsed += step.duration_s

    min_pct_total = 100.0 * min_wbal / float(w_prime_j)
    if min_pct_total >= 35:
        wbal_score = 100.0
    elif min_pct_total >= 20:
        wbal_score = 75.0 + (min_pct_total - 20.0) * (25.0 / 15.0)
    elif min_pct_total >= 5:
        wbal_score = 35.0 + (min_pct_total - 5.0) * (40.0 / 15.0)
    else:
        wbal_score = max(0.0, min_pct_total * 7.0)

    # Penalise time spent near depletion because it is often the reason the
    # workout collapses late even if W′ never reaches exactly zero.
    near_depletion_penalty = min(25.0, seconds_below_10pct / max(1, workout.duration_s) * 100.0)
    feasibility_score = max(0.0, min(100.0, wbal_score - near_depletion_penalty))

    if feasibility_score >= 85:
        classification = "feasible"
        validity = "green"
    elif feasibility_score >= 65:
        classification = "feasible_with_caution"
        validity = "yellow"
    elif feasibility_score >= 40:
        classification = "risky"
        validity = "orange"
    else:
        classification = "not_feasible"
        validity = "red"

    limiting_factor = None
    if min_pct_total < 20:
        limiting_factor = "w_prime_depletion"
        warnings.append({
            "severity": "high" if min_pct_total < 10 else "medium",
            "type": "low_w_prime_balance",
            "message": f"Estimated W′bal drops to {min_pct_total:.1f}%: a very demanding workout for this athlete.",
        })
        recommendations.append({
            "type": "increase_recovery_or_reduce_power",
            "message": "Increase recovery periods or reduce targets for intervals above CP.",
        })
    elif min_pct_total < 35:
        limiting_factor = "limited_w_prime_margin"
        warnings.append({
            "severity": "medium",
            "type": "limited_w_prime_margin",
            "message": f"Limited W′ margin: estimated minimum {min_pct_total:.1f}%.",
        })

    confidence = 0.9
    if any(w.get("type") == "cp_estimated_from_ftp" for w in warnings):
        confidence -= 0.2
    if context.get("fatigue_state") in {"fatigued", "very_fatigued"}:
        confidence -= 0.05
        warnings.append({
            "severity": "medium",
            "type": "fatigue_context_not_modelled",
            "message": "Fatigue state is noted but V1 relies mainly on CP/W′; interpret with caution.",
        })

    return {
        "status": "success",
        "feasibility_score": round(feasibility_score, 1),
        "confidence_score": round(max(0.1, min(0.95, confidence)), 2),
        "classification": classification,
        "validity": validity,
        "limiting_factor": limiting_factor,
        "summary": {
            "cp_w": round(cp_w, 1),
            "w_prime_j": round(float(w_prime_j), 1),
            "weight_kg": weight_kg,
            "planned_duration_s": workout.duration_s,
            "min_w_prime_balance_j": round(min_wbal, 1),
            "min_w_prime_balance_pct": round(min_pct_total, 1),
            "total_work_above_cp_j": round(total_above_cp_j, 1),
            "seconds_below_10pct_w_prime": int(seconds_below_10pct),
            "seconds_depleted": int(seconds_depleted),
            "hardest_step_id": hardest_step_id,
            "w_prime_tau_s": round(resolved_tau_s, 1) if resolved_tau_s is not None else None,
            "tau_model": resolved_tau_model,
        },
        "warnings": warnings,
        "recommendations": recommendations,
        "step_analysis": step_analysis,
    }
