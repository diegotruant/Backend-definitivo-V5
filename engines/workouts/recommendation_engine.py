"""Workout recommendation based on ability, readiness and goals."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload, readiness_score_from_state
from engines.core.model_safety import finalize_model_metadata
from engines.workouts.progression_levels import compute_progression_levels

PHENOTYPE_ZONE_PRIORITY: Dict[str, List[str]] = {
    "sprint": ["anaerobic", "vo2", "threshold"],
    "anaerobic": ["anaerobic", "vo2", "threshold"],
    "vo2": ["vo2", "anaerobic", "threshold"],
    "threshold": ["threshold", "vo2", "endurance"],
    "endurance": ["endurance", "threshold", "vo2"],
    "durability": ["endurance", "threshold"],
}


def _normalize_dominant(dominant: Optional[str]) -> str:
    value = str(dominant or "balanced").strip().lower()
    if value == "sprint":
        return "anaerobic"
    return value or "balanced"


def _select_focus_and_intensity(
    *,
    goal_type: str,
    levels: Dict[str, Any],
    dominant_ability: Optional[str],
    readiness_score: int,
) -> tuple[str, str, str]:
    """Pick session focus using phenotype band, goal and weakest progression level."""
    if readiness_score < 45:
        return "recovery", "low", "readiness_recovery"
    if readiness_score < 65:
        return "endurance", "moderate_low", "readiness_moderate"

    dominant = _normalize_dominant(dominant_ability)
    if goal_type != "balanced":
        pool = [goal_type]
        strategy = "goal_directed"
    else:
        pool = PHENOTYPE_ZONE_PRIORITY.get(dominant, ["threshold", "vo2", "anaerobic", "endurance"])
        strategy = "phenotype_aware_limiter"

    focus = min(pool, key=lambda zone: levels.get(zone, 5.0))
    if focus not in {"recovery", "threshold", "vo2", "anaerobic", "endurance"}:
        focus = "anaerobic" if dominant in {"sprint", "anaerobic"} else "endurance"

    intensity = "quality" if readiness_score >= 75 else "moderate"
    return focus, intensity, strategy


def recommend_workout(
    athlete_profile: Dict[str, Any],
    *,
    readiness: Optional[Dict[str, Any]] = None,
    goal: Optional[Dict[str, Any]] = None,
    recent_workouts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    assumptions: list[str] = []
    missing_inputs: list[str] = []
    readiness_score_raw = (readiness or {}).get("readiness_score")
    if readiness_score_raw is None:
        readiness_score_raw = (readiness or {}).get("score")
    normalized_readiness = readiness_score_from_state({"readiness_score": readiness_score_raw}) if readiness_score_raw is not None else None
    if normalized_readiness is None:
        missing_inputs.append("readiness.readiness_score")
        payload = {
            "status": "insufficient_profile",
            "schema_version": "1.0.0",
            "recommendation": {
                "focus": None,
                "intensity": None,
                "readiness_score": None,
                "rationale": "readiness_score required before workout prescription",
                "workout": None,
                "next_step": "provide_readiness_score",
            },
            "progression_levels": compute_progression_levels(athlete_profile, recent_workouts or []),
            "model_metadata": finalize_model_metadata(
                assumptions=assumptions,
                missing_inputs=missing_inputs,
                quality_flags=["prescription_blocked_without_readiness"],
                confidence=0.35,
            ),
        }
        return annotate_payload(payload, module_name="recommendation_engine", method="readiness_progression", confidence=0.35)
    readiness_score = int(round(normalized_readiness))
    goal_type = str((goal or {}).get("focus") or "balanced").lower()
    progress = compute_progression_levels(athlete_profile, recent_workouts or [])
    levels = progress.get("levels", {})
    ability = progress.get("ability_profile") or {}
    dominant = ability.get("dominant_ability") or athlete_profile.get("dominant_ability")
    focus, intensity, selection_strategy = _select_focus_and_intensity(
        goal_type=goal_type,
        levels=levels,
        dominant_ability=dominant,
        readiness_score=readiness_score,
    )
    template = _template_for_focus(focus, athlete_profile, intensity)
    if template.get("status") != "success":
        payload = {
            "status": "insufficient_profile",
            "schema_version": "1.0.0",
            "recommendation": {
                "focus": focus,
                "intensity": intensity,
                "readiness_score": readiness_score,
                "rationale": _rationale(focus, readiness_score, levels, dominant, selection_strategy),
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
            "rationale": _rationale(focus, readiness_score, levels, dominant, selection_strategy),
            "workout": workout,
            "ability_context": {
                "dominant_ability": dominant,
                "selection_strategy": selection_strategy,
            },
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


def _rationale(
    focus: str,
    readiness_score: int,
    levels: Dict[str, Any],
    dominant_ability: Optional[str] = None,
    selection_strategy: Optional[str] = None,
) -> List[str]:
    notes = [f"readiness_{readiness_score}", f"selected_focus_{focus}"]
    if dominant_ability:
        notes.append(f"phenotype_{_normalize_dominant(dominant_ability)}")
    if selection_strategy:
        notes.append(f"strategy_{selection_strategy}")
    if focus in levels:
        notes.append(f"progression_level_{focus}_{levels[focus]}")
    return notes
