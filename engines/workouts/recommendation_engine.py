"""Workout recommendation based on ability, readiness and goals."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload
from engines.core.model_safety import finalize_model_metadata
from engines.workouts.progression_levels import compute_progression_levels


def recommend_workout(
    athlete_profile: Dict[str, Any],
    *,
    readiness: Optional[Dict[str, Any]] = None,
    goal: Optional[Dict[str, Any]] = None,
    recent_workouts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    assumptions: list[str] = []
    missing_inputs: list[str] = []
    readiness_score = int((readiness or {}).get("readiness_score") or 70)
    if readiness is None or "readiness_score" not in readiness:
        assumptions.append("readiness_score_defaulted_to_70")
        missing_inputs.append("readiness.readiness_score")
    goal_type = str((goal or {}).get("focus") or "balanced").lower()
    progress = compute_progression_levels(athlete_profile, recent_workouts or [])
    levels = progress.get("levels", {})
    if readiness_score < 45:
        focus = "recovery"
        intensity = "low"
    elif readiness_score < 65:
        focus = "endurance"
        intensity = "moderate_low"
    else:
        candidates = ["threshold", "vo2", "anaerobic", "endurance"] if goal_type == "balanced" else [goal_type]
        focus = min(candidates, key=lambda z: levels.get(z, 5.0)) if candidates else "endurance"
        intensity = "quality" if readiness_score >= 75 else "moderate"
    template = _template_for_focus(focus, athlete_profile, intensity)
    if template.get("status") != "success":
        payload = {
            "status": "insufficient_profile",
            "schema_version": "1.0.0",
            "recommendation": {
                "focus": focus,
                "intensity": intensity,
                "readiness_score": readiness_score,
                "rationale": _rationale(focus, readiness_score, levels),
                "workout": None,
                "next_step": "provide_cp_or_ftp",
            },
            "progression_levels": progress,
            "model_metadata": finalize_model_metadata(
                assumptions=assumptions,
                missing_inputs=missing_inputs + ["athlete_profile.cp_or_ftp"],
                quality_flags=["prescription_blocked_without_power_anchor"],
                confidence=0.4,
            ),
        }
        return annotate_payload(payload, module_name="recommendation_engine", method="readiness_progression", confidence=0.4)

    workout = template["workout"]
    payload = {
        "status": "success",
        "schema_version": "1.0.0",
        "recommendation": {
            "focus": focus,
            "intensity": intensity,
            "readiness_score": readiness_score,
            "rationale": _rationale(focus, readiness_score, levels),
            "workout": workout,
        },
        "progression_levels": progress,
        "model_metadata": finalize_model_metadata(
            assumptions=assumptions,
            missing_inputs=missing_inputs,
            confidence=0.74,
        ),
    }
    return annotate_payload(payload, module_name="recommendation_engine", method="readiness_progression", confidence=0.74)


def _template_for_focus(focus: str, profile: Dict[str, Any], intensity: str) -> Dict[str, Any]:
    cp = profile.get("cp_w") or profile.get("critical_power_w") or profile.get("ftp_w") or profile.get("ftp")
    if cp is None:
        return {"status": "insufficient_profile", "reason": "missing_cp_or_ftp"}
    try:
        cp = float(cp)
    except Exception:
        return {"status": "insufficient_profile", "reason": "invalid_cp_or_ftp"}
    if cp <= 0:
        return {"status": "insufficient_profile", "reason": "non_positive_cp_or_ftp"}
    if focus == "recovery":
        steps = [{"type": "warmup", "duration_s": 600, "target_w": int(cp * 0.5)}, {"type": "endurance", "duration_s": 1800, "target_w": int(cp * 0.55)}]
    elif focus == "threshold":
        steps = [{"type": "warmup", "duration_s": 900, "target_w": int(cp * 0.6)}] + [{"type": "work", "duration_s": 600, "target_w": int(cp * 0.98)}, {"type": "recovery", "duration_s": 300, "target_w": int(cp * 0.5)}] * 3
    elif focus == "vo2":
        steps = [{"type": "warmup", "duration_s": 900, "target_w": int(cp * 0.6)}] + [{"type": "work", "duration_s": 180, "target_w": int(cp * 1.15)}, {"type": "recovery", "duration_s": 180, "target_w": int(cp * 0.5)}] * 5
    elif focus == "anaerobic":
        steps = [{"type": "warmup", "duration_s": 900, "target_w": int(cp * 0.6)}] + [{"type": "work", "duration_s": 45, "target_w": int(cp * 1.45)}, {"type": "recovery", "duration_s": 180, "target_w": int(cp * 0.45)}] * 8
    else:
        steps = [{"type": "warmup", "duration_s": 600, "target_w": int(cp * 0.55)}, {"type": "endurance", "duration_s": 3600 if intensity != "moderate_low" else 2400, "target_w": int(cp * 0.68)}]
    return {
        "status": "success",
        "workout": {"name": f"{focus.title()} session", "steps": steps, "estimated_duration_s": sum(int(s.get("duration_s", 0)) for s in steps)},
    }


def _rationale(focus: str, readiness_score: int, levels: Dict[str, Any]) -> List[str]:
    notes = [f"readiness_{readiness_score}", f"selected_focus_{focus}"]
    if focus in levels:
        notes.append(f"progression_level_{focus}_{levels[focus]}")
    return notes
