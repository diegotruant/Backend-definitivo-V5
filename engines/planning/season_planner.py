"""Rule-based season plan generation and load-risk checks."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload

EWMA_CHRONIC_TRUST_DAYS = 42
EWMA_ACUTE_TRUST_DAYS = 14


def _parse_date(value: Optional[str], default: date) -> date:
    try:
        return date.fromisoformat(str(value)[:10]) if value else default
    except Exception:
        return default


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _profile_context(
    athlete_profile: Optional[Dict[str, Any]],
    goal: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Derive planning hints from athlete profile, metabolic snapshot and goal."""
    profile = athlete_profile or {}
    goal_focus = str((goal or {}).get("focus") or "balanced").strip().lower()

    snap = profile.get("metabolic_snapshot") if isinstance(profile.get("metabolic_snapshot"), dict) else {}
    phenotype_raw = (
        profile.get("dominant_ability")
        or profile.get("ability_phenotype")
        or profile.get("metabolic_phenotype")
        or (snap.get("metabolic_phenotype") or {}).get("label")
        if isinstance(snap.get("metabolic_phenotype"), dict)
        else snap.get("metabolic_phenotype")
    )
    if isinstance(phenotype_raw, dict):
        phenotype_raw = phenotype_raw.get("label") or phenotype_raw.get("type")
    phenotype = str(phenotype_raw or "").strip().lower()

    cp = _num(
        profile.get("cp_w")
        or profile.get("critical_power_w")
        or snap.get("mlss_power_watts")
        or snap.get("critical_power_w")
    )
    vlamax = _num(
        profile.get("vlamax")
        or profile.get("estimated_vlamax_mmol_L_s")
        or snap.get("estimated_vlamax_mmol_L_s")
    )

    mmp = profile.get("mmp") or profile.get("power_curve") or {}
    if isinstance(mmp, dict) and "curve" in mmp:
        mmp = mmp.get("curve") or {}
    sprint_w = _num(mmp.get("15") or mmp.get(15) or mmp.get("5") or mmp.get(5)) if isinstance(mmp, dict) else None

    if not phenotype or phenotype == "balanced":
        if vlamax is not None and vlamax >= 0.55:
            phenotype = "anaerobic"
        elif vlamax is not None and vlamax <= 0.35:
            phenotype = "endurance"
        elif cp and sprint_w and sprint_w / cp >= 2.8:
            phenotype = "sprint"
        elif goal_focus not in {"", "balanced"}:
            phenotype = goal_focus

    intensity_bias = "balanced"
    if phenotype in {"sprint", "anaerobic", "sprinter", "glycolytic"} or goal_focus in {"sprint", "anaerobic"}:
        intensity_bias = "anaerobic"
    elif phenotype in {"endurance", "diesel", "oxidative"} or goal_focus == "endurance":
        intensity_bias = "endurance"
    elif phenotype in {"threshold", "all_rounder", "allrounder"} or goal_focus == "threshold":
        intensity_bias = "threshold"

    return {
        "phenotype": phenotype or goal_focus or "balanced",
        "intensity_bias": intensity_bias,
        "cp_w": cp,
        "vlamax": vlamax,
        "goal_focus": goal_focus,
        "sprint_to_cp_ratio": round(sprint_w / cp, 2) if cp and sprint_w and cp > 0 else None,
    }


def create_season_plan(
    *,
    start_date: Optional[str],
    target_date: Optional[str],
    weekly_hours: float = 8.0,
    goal: Optional[Dict[str, Any]] = None,
    athlete_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if weekly_hours <= 0:
        payload = {
            "status": "invalid_input",
            "schema_version": "1.0.0",
            "error": "weekly_hours_must_be_positive",
            "weeks": [],
        }
        return annotate_payload(
            payload,
            module_name="season_planner",
            method="rule_based_periodization",
            confidence=0.2,
        )
    start = _parse_date(start_date, date.today())
    target = _parse_date(target_date, start + timedelta(days=84))
    total_days = max(7, (target - start).days)
    weeks = max(1, total_days // 7)
    profile_ctx = _profile_context(athlete_profile, goal)
    focus = profile_ctx["goal_focus"] if profile_ctx["goal_focus"] != "balanced" else profile_ctx["intensity_bias"]

    plan: List[Dict[str, Any]] = []
    for w in range(weeks):
        phase = _phase(w, weeks)
        recovery_week = (w + 1) % 4 == 0
        volume = weekly_hours * (0.65 if recovery_week else 1.0 + min(w, weeks // 2) * 0.02)
        workouts = _week_workouts(
            start + timedelta(days=w * 7),
            phase,
            volume,
            focus,
            recovery_week,
            profile_ctx,
        )
        plan.append({
            "week_index": w + 1,
            "phase": phase,
            "recovery_week": recovery_week,
            "target_hours": round(volume, 1),
            "workouts": workouts,
        })

    confidence = 0.55
    if athlete_profile and (profile_ctx.get("cp_w") or profile_ctx.get("vlamax") or profile_ctx.get("phenotype") != "balanced"):
        confidence = 0.62

    payload = {
        "status": "success",
        "schema_version": "1.0.0",
        "start_date": start.isoformat(),
        "target_date": target.isoformat(),
        "planning_context": profile_ctx,
        "weeks": plan,
    }
    return annotate_payload(payload, module_name="season_planner", method="rule_based_periodization", confidence=confidence)


def _phase(w: int, weeks: int) -> str:
    pct = (w + 1) / max(weeks, 1)
    if pct < 0.35:
        return "base"
    if pct < 0.72:
        return "build"
    if pct < 0.92:
        return "peak"
    return "taper"


def _quality_type(phase: str, focus: str, intensity_bias: str) -> str:
    if phase == "base":
        return "endurance"
    if intensity_bias == "anaerobic" and phase in {"build", "peak"}:
        return "anaerobic" if focus in {"anaerobic", "sprint", "vo2"} else "vo2"
    if intensity_bias == "threshold" and phase in {"build", "peak"}:
        return "threshold"
    if phase in {"build", "peak"}:
        return focus if focus in {"vo2", "anaerobic", "threshold"} else "threshold"
    return "endurance"


def _week_workouts(
    start: date,
    phase: str,
    hours: float,
    focus: str,
    recovery: bool,
    profile_ctx: Dict[str, Any],
) -> List[Dict[str, Any]]:
    intensity_bias = profile_ctx.get("intensity_bias") or "balanced"
    quality = _quality_type(phase, focus, intensity_bias)

    if intensity_bias == "anaerobic" and phase in {"build", "peak"} and not recovery:
        quality_share = 0.32
        endurance_share = 0.28
        long_share = 0.25
        return [
            {
                "date": (start + timedelta(days=1)).isoformat(),
                "type": quality,
                "duration_min": int(hours * 60 * quality_share),
                "load": round(hours * 14, 1),
                "note": "primary_quality",
            },
            {
                "date": (start + timedelta(days=3)).isoformat(),
                "type": "vo2" if quality == "anaerobic" else "anaerobic",
                "duration_min": int(hours * 60 * 0.18),
                "load": round(hours * 11, 1),
                "note": "secondary_quality",
            },
            {
                "date": (start + timedelta(days=4)).isoformat(),
                "type": "endurance",
                "duration_min": int(hours * 60 * endurance_share),
                "load": round(hours * 9, 1),
            },
            {
                "date": (start + timedelta(days=6)).isoformat(),
                "type": "skills_neuromuscular" if phase == "peak" else "long_endurance",
                "duration_min": int(hours * 60 * long_share),
                "load": round(hours * (10 if phase == "peak" else 14), 1),
            },
        ]

    if intensity_bias == "endurance" and phase in {"build", "peak"}:
        return [
            {
                "date": (start + timedelta(days=1)).isoformat(),
                "type": "endurance",
                "duration_min": int(hours * 60 * 0.3),
                "load": round(hours * 10, 1),
            },
            {
                "date": (start + timedelta(days=3)).isoformat(),
                "type": quality,
                "duration_min": int(hours * 60 * (0.2 if not recovery else 0.18)),
                "load": round(hours * 12, 1),
            },
            {
                "date": (start + timedelta(days=5)).isoformat(),
                "type": "long_endurance",
                "duration_min": int(hours * 60 * 0.5),
                "load": round(hours * 18, 1),
            },
        ]

    return [
        {
            "date": (start + timedelta(days=1)).isoformat(),
            "type": quality,
            "duration_min": int(hours * 60 * (0.25 if not recovery else 0.2)),
            "load": round(hours * 12, 1),
        },
        {
            "date": (start + timedelta(days=3)).isoformat(),
            "type": "endurance",
            "duration_min": int(hours * 60 * 0.3),
            "load": round(hours * 10, 1),
        },
        {
            "date": (start + timedelta(days=5)).isoformat(),
            "type": "long_endurance",
            "duration_min": int(hours * 60 * 0.45),
            "load": round(hours * 16, 1),
        },
    ]


def check_load_risk(plan: List[Dict[str, Any]], *, chronic_load: float = 50.0) -> Dict[str, Any]:
    weekly = []
    for week in plan:
        load = float(week.get("target_load", 0.0) or 0.0)
        if not load:
            load = sum(float(w.get("load", 0.0) or 0.0) for w in week.get("workouts", []) if isinstance(w, dict))
        weekly.append(load)
    warnings = []
    for i in range(1, len(weekly)):
        if weekly[i - 1] > 0 and (weekly[i] - weekly[i - 1]) / weekly[i - 1] > 0.25:
            warnings.append({"week_index": i + 1, "warning": "large_weekly_load_jump"})
    peak = max(weekly) if weekly else 0.0
    risk = "high" if peak > chronic_load * 2.0 else "moderate" if peak > chronic_load * 1.5 else "low"
    payload = {"status": "success", "risk": risk, "weekly_loads": [round(x, 1) for x in weekly], "warnings": warnings}
    return annotate_payload(payload, module_name="season_planner", method="load_risk_check", confidence=0.7)
