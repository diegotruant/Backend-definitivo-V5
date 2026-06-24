"""Rule-based season plan generation and load-risk checks."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload


def _parse_date(value: Optional[str], default: date) -> date:
    try:
        return date.fromisoformat(str(value)[:10]) if value else default
    except Exception:
        return default


def create_season_plan(
    *,
    start_date: Optional[str],
    target_date: Optional[str],
    weekly_hours: float = 8.0,
    goal: Optional[Dict[str, Any]] = None,
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
    focus = str((goal or {}).get("focus") or "balanced")
    plan: List[Dict[str, Any]] = []
    for w in range(weeks):
        phase = _phase(w, weeks)
        recovery_week = (w + 1) % 4 == 0
        volume = weekly_hours * (0.65 if recovery_week else 1.0 + min(w, weeks // 2) * 0.02)
        workouts = _week_workouts(start + timedelta(days=w * 7), phase, volume, focus, recovery_week)
        plan.append({"week_index": w + 1, "phase": phase, "recovery_week": recovery_week, "target_hours": round(volume, 1), "workouts": workouts})
    payload = {"status": "success", "schema_version": "1.0.0", "start_date": start.isoformat(), "target_date": target.isoformat(), "weeks": plan}
    return annotate_payload(payload, module_name="season_planner", method="rule_based_periodization", confidence=0.55)


def _phase(w: int, weeks: int) -> str:
    pct = (w + 1) / max(weeks, 1)
    if pct < 0.35:
        return "base"
    if pct < 0.72:
        return "build"
    if pct < 0.92:
        return "peak"
    return "taper"


def _week_workouts(start: date, phase: str, hours: float, focus: str, recovery: bool) -> List[Dict[str, Any]]:
    quality = "threshold" if phase in {"build", "peak"} else "endurance"
    if focus in {"vo2", "anaerobic", "threshold"} and phase != "base":
        quality = focus
    return [
        {"date": (start + timedelta(days=1)).isoformat(), "type": quality, "duration_min": int(hours * 60 * (0.25 if not recovery else 0.2)), "load": round(hours * 12, 1)},
        {"date": (start + timedelta(days=3)).isoformat(), "type": "endurance", "duration_min": int(hours * 60 * 0.3), "load": round(hours * 10, 1)},
        {"date": (start + timedelta(days=5)).isoformat(), "type": "long_endurance", "duration_min": int(hours * 60 * 0.45), "load": round(hours * 16, 1)},
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
