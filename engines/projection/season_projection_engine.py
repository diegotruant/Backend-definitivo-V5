"""Seasonal forward projection / what-if engine.

V1 is deliberately conservative: it does not pretend to know exact biological
adaptation, but it does make the coach-facing bridge between a current TwinState
and a planned calendar.  It projects CP/W′/VO2max/VLaMax/load/readiness day by
day using bounded, auditable heuristics.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from engines.twin_state.models import build_twin_state, validate_twin_state
from engines.workouts.models import WorkoutValidationError, normalize_workout


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(out) or np.isinf(out):
        return None
    return out


def _date(value: Any) -> Optional[date]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def _metrics_from_state(state: Dict[str, Any]) -> Dict[str, float]:
    metabolic = state.get("metabolic_metrics") or {}
    athlete = state.get("athlete_profile") or {}
    snap = state.get("metabolic_snapshot") or {}
    merged = {**snap, **metabolic, **athlete}
    cp = _num(merged.get("cp_w") or merged.get("critical_power_w") or merged.get("mlss_w") or merged.get("mlss_watts"))
    ftp = _num(merged.get("ftp_w") or merged.get("ftp"))
    if cp is None and ftp is not None:
        cp = ftp * 1.03
    wprime = _num(merged.get("w_prime_j") or merged.get("wprime_j") or merged.get("w_prime"))
    vo2 = _num(merged.get("vo2max_ml_kg_min") or merged.get("vo2max"))
    vlamax = _num(merged.get("vlamax_mmol_l_s") or merged.get("vlamax"))
    return {
        "cp_w": float(cp if cp is not None else 250.0),
        "w_prime_j": float(wprime if wprime is not None else 18000.0),
        "vo2max_ml_kg_min": float(vo2 if vo2 is not None else 50.0),
        "vlamax_mmol_l_s": float(vlamax if vlamax is not None else 0.45),
    }


def _iter_events(calendar_plan: Iterable[Dict[str, Any]]) -> List[Tuple[date, Dict[str, Any]]]:
    events: List[Tuple[date, Dict[str, Any]]] = []
    for raw in calendar_plan or []:
        if not isinstance(raw, dict):
            continue
        when = _date(raw.get("date") or raw.get("scheduled_date") or raw.get("planned_date") or raw.get("start_date"))
        if when is None:
            continue
        events.append((when, raw))
    events.sort(key=lambda x: x[0])
    return events


def _workout_stimulus(event: Dict[str, Any], cp_w: float) -> Dict[str, float]:
    """Return bounded daily stimuli from a workout/calendar event."""
    workout_payload = event.get("workout") or event.get("workout_definition") or event
    manual_load = _num(event.get("training_load") or event.get("load") or event.get("tss"))
    modality = str(event.get("modality") or event.get("discipline") or "cycling").lower()
    if manual_load is not None and not (workout_payload.get("steps") or workout_payload.get("structure")):
        load = max(0.0, min(300.0, manual_load))
        return {
            "load": load,
            "aerobic": load * 0.75,
            "anaerobic": load * 0.15,
            "neuromuscular": load * (0.15 if "strength" in modality or "gym" in modality else 0.05),
            "duration_s": float(event.get("duration_s") or event.get("duration_min", 0) or 0) * (60.0 if event.get("duration_min") else 1.0),
        }
    try:
        workout = normalize_workout(workout_payload)
    except WorkoutValidationError:
        # Unknown event: keep a small recovery/load footprint if duration exists.
        duration_s = _num(event.get("duration_s")) or (_num(event.get("duration_min")) or 0.0) * 60.0
        load = min(120.0, max(0.0, duration_s / 60.0 * 0.6))
        return {"load": load, "aerobic": load * 0.5, "anaerobic": load * 0.1, "neuromuscular": 0.0, "duration_s": duration_s}

    load = aerobic = anaerobic = neuromuscular = 0.0
    for step in workout.steps:
        p = step.resolved_target_power_w({"cp_w": cp_w})
        duration_h = step.duration_s / 3600.0
        if p is None:
            intensity = 0.45 if step.type.lower() in {"rest", "recovery"} else 0.65
        else:
            intensity = max(0.2, min(2.2, p / max(cp_w, 1.0)))
        step_load = 100.0 * duration_h * intensity * intensity
        load += step_load
        aerobic += step_load * max(0.0, min(1.0, 1.2 - abs(intensity - 0.85)))
        if intensity > 1.0:
            anaerobic += step_load * (intensity - 1.0) * 2.0
        if step.duration_s <= 45 and intensity >= 1.25:
            neuromuscular += step_load * intensity
    return {
        "load": max(0.0, min(350.0, load)),
        "aerobic": max(0.0, min(350.0, aerobic)),
        "anaerobic": max(0.0, min(250.0, anaerobic)),
        "neuromuscular": max(0.0, min(120.0, neuromuscular)),
        "duration_s": float(workout.duration_s),
    }


def project_season_from_plan(
    twin_state_payload: Dict[str, Any],
    calendar_plan: List[Dict[str, Any]],
    *,
    start_date: Optional[str] = None,
    target_date: Optional[str] = None,
    max_days: int = 365,
) -> Dict[str, Any]:
    """Project TwinState metrics forward over a planned calendar."""
    state = build_twin_state(twin_state_payload) if twin_state_payload.get("schema_version") is None else validate_twin_state(twin_state_payload)
    events = _iter_events(calendar_plan)
    today = _date(start_date) or _date(state.get("updated_at")) or date.today()
    end = _date(target_date) or (events[-1][0] if events else today + timedelta(days=28))
    if end < today:
        raise ValueError("target_date must be on or after start_date")
    if (end - today).days > max_days:
        end = today + timedelta(days=max_days)

    metrics = _metrics_from_state(state)
    cp0 = metrics["cp_w"]
    wprime0 = metrics["w_prime_j"]
    vo20 = metrics["vo2max_ml_kg_min"]
    vla0 = metrics["vlamax_mmol_l_s"]
    cp = cp0
    wprime = wprime0
    vo2 = vo20
    vla = vla0
    ctl = _num((state.get("load_state") or {}).get("ctl")) or 40.0
    atl = _num((state.get("load_state") or {}).get("atl")) or ctl

    event_by_day: Dict[date, List[Dict[str, Any]]] = {}
    for d, raw in events:
        if today <= d <= end:
            event_by_day.setdefault(d, []).append(raw)

    series: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    day = today
    while day <= end:
        daily = {"load": 0.0, "aerobic": 0.0, "anaerobic": 0.0, "neuromuscular": 0.0, "duration_s": 0.0}
        for event in event_by_day.get(day, []):
            stim = _workout_stimulus(event, cp)
            for key in daily:
                daily[key] += stim.get(key, 0.0)

        # Load model: classic CTL/ATL style exponential response.
        ctl += (daily["load"] - ctl) / 42.0
        atl += (daily["load"] - atl) / 7.0
        form = ctl - atl

        # Conservative adaptations with saturation and detraining.
        aerobic_signal = daily["aerobic"] / 100.0
        anaerobic_signal = daily["anaerobic"] / 100.0
        neuro_signal = daily["neuromuscular"] / 50.0
        rest_decay = 1.0 if daily["load"] < 10 else 0.0
        cp += cp0 * (0.00055 * aerobic_signal - 0.00018 * rest_decay)
        vo2 += vo20 * (0.00045 * aerobic_signal - 0.00012 * rest_decay)
        vla += 0.0040 * anaerobic_signal + 0.0015 * neuro_signal - 0.0022 * aerobic_signal
        wprime += wprime0 * (0.00045 * anaerobic_signal + 0.00018 * neuro_signal - 0.00008 * aerobic_signal)

        # Hard clamps: V1 projection should not create biologically wild outputs.
        cp = max(cp0 * 0.88, min(cp0 * 1.16, cp))
        vo2 = max(vo20 * 0.90, min(vo20 * 1.15, vo2))
        vla = max(0.12, min(1.35, vla))
        wprime = max(wprime0 * 0.80, min(wprime0 * 1.25, wprime))

        readiness = max(0.0, min(100.0, 72.0 + form * 0.55 - max(0.0, atl - ctl) * 0.15))
        if daily["load"] > 220:
            warnings.append({"date": day.isoformat(), "severity": "medium", "type": "large_daily_load", "message": "Planned daily load is unusually high; projection confidence reduced."})
        series.append({
            "date": day.isoformat(),
            "planned_load": round(daily["load"], 1),
            "ctl": round(ctl, 1),
            "atl": round(atl, 1),
            "form": round(form, 1),
            "readiness_score": round(readiness, 1),
            "cp_w": round(cp, 1),
            "w_prime_j": round(wprime, 1),
            "vo2max_ml_kg_min": round(vo2, 2),
            "vlamax_mmol_l_s": round(vla, 4),
        })
        day += timedelta(days=1)

    horizon_days = max(1, len(series) - 1)
    confidence = 0.72 - min(0.28, horizon_days / 365.0 * 0.28)
    if not events:
        confidence *= 0.55
        warnings.append({"severity": "high", "type": "empty_calendar", "message": "No planned events supplied; projection is mostly detraining/default load."})
    final = series[-1] if series else {}
    return {
        "status": "success",
        "schema_version": "season_projection.v1",
        "start_date": today.isoformat(),
        "target_date": end.isoformat(),
        "horizon_days": horizon_days,
        "confidence_score": round(max(0.15, min(0.85, confidence)), 2),
        "baseline": {"cp_w": round(cp0, 1), "w_prime_j": round(wprime0, 1), "vo2max_ml_kg_min": round(vo20, 2), "vlamax_mmol_l_s": round(vla0, 4)},
        "final_projection": final,
        "delta": {
            "cp_w": round((final.get("cp_w") or cp0) - cp0, 1),
            "w_prime_j": round((final.get("w_prime_j") or wprime0) - wprime0, 1),
            "vo2max_ml_kg_min": round((final.get("vo2max_ml_kg_min") or vo20) - vo20, 2),
            "vlamax_mmol_l_s": round((final.get("vlamax_mmol_l_s") or vla0) - vla0, 4),
        },
        "time_series": series,
        "assumptions": {
            "model": "bounded heuristic adaptation v1",
            "not_lab_grade": True,
            "ctl_tau_days": 42,
            "atl_tau_days": 7,
            "max_horizon_days": max_days,
        },
        "warnings": warnings[-50:],
    }
