"""Coach-facing performance/session curves.

Session curves that are indispensable for coach reports but are not metabolic
snapshot curves: W' balance, durability decay and post-effort recovery estimate.
The output follows the same frontend contract used by metabolic coach curves.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from engines.performance.durability_engine import generate_hourly_decay_curve
from engines.performance.w_prime_balance_engine import analyze_w_prime_usage, calculate_w_prime_balance

MODEL_ESTIMATE = "MODEL_ESTIMATE"
HEURISTIC = "HEURISTIC"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def _finite_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _curve(
    *,
    curve_id: str,
    title: str,
    x_key: str,
    x_unit: str,
    y_keys: Sequence[Dict[str, str]],
    measurement_tier: str,
    points: List[Dict[str, Any]],
    anchors: Optional[List[Dict[str, Any]]] = None,
    confidence_score: float = 0.5,
    limitations: Optional[List[str]] = None,
    frontend_hint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "curve_id": curve_id,
        "title": title,
        "x_axis": {"key": x_key, "unit": x_unit},
        "y_axis": list(y_keys),
        "measurement_tier": measurement_tier,
        "points": points,
        "anchors": anchors or [],
        "confidence_score": round(max(0.0, min(0.95, confidence_score)), 3),
        "limitations": limitations or [],
        "frontend_hint": frontend_hint or {"chart_type": "line", "show_anchors": True},
    }


def _clean_power(power_stream: Optional[Sequence[float]]) -> List[float]:
    out: List[float] = []
    for value in power_stream or []:
        p = _finite_float(value)
        if p is not None:
            out.append(max(0.0, p))
    return out


def _downsample_indices(n: int, max_points: int = 500) -> List[int]:
    if n <= max_points:
        return list(range(n))
    step = max(1, int(np.ceil(n / max_points)))
    return list(range(0, n, step))


def _session_load(power: Sequence[float], *, dt_s: float, anchor_w: Optional[float]) -> Dict[str, Any]:
    if not power:
        return {"duration_s": 0.0, "avg_power_w": None, "intensity_factor": None, "estimated_tss": None}
    duration_s = len(power) * max(dt_s, 0.1)
    avg_power = float(np.mean(power))
    anchor = anchor_w if anchor_w and anchor_w > 0 else None
    intensity = avg_power / anchor if anchor else None
    estimated_tss = duration_s / 3600.0 * (intensity or 0.0) ** 2 * 100.0 if intensity is not None else None
    return {
        "duration_s": round(duration_s, 1),
        "avg_power_w": round(avg_power, 1),
        "intensity_factor": round(intensity, 3) if intensity is not None else None,
        "estimated_tss": round(estimated_tss, 1) if estimated_tss is not None else None,
    }


def build_w_prime_balance_curve(
    power_stream: Optional[Sequence[float]],
    *,
    cp_w: Optional[float],
    w_prime_j: Optional[float],
    dt_s: float = 1.0,
) -> Dict[str, Any]:
    """Build W' balance curve for interval/session feasibility visualization."""
    power = _clean_power(power_stream)
    cp = _finite_float(cp_w)
    w_prime = _finite_float(w_prime_j)
    if len(power) < 2 or cp is None or cp <= 0 or w_prime is None or w_prime <= 0:
        return _curve(
            curve_id="w_prime_balance",
            title="W' balance",
            x_key="time_s",
            x_unit="s",
            y_keys=[{"key": "w_prime_balance_pct", "unit": "%", "label": "W' balance"}],
            measurement_tier=INSUFFICIENT_DATA,
            points=[],
            confidence_score=0.0,
            limitations=["Requires power stream, CP and W' to compute W' balance."],
        )
    wbal = calculate_w_prime_balance(power, cp=cp, w_prime=w_prime, dt_s=max(dt_s, 0.1))
    usage = analyze_w_prime_usage(power, wbal, w_prime)
    points = []
    for idx in _downsample_indices(len(wbal)):
        points.append({
            "time_s": round(idx * max(dt_s, 0.1), 1),
            "power_w": round(power[idx], 1),
            "w_prime_balance_j": round(wbal[idx], 0),
            "w_prime_balance_pct": round(wbal[idx] / w_prime * 100.0, 1),
        })
    anchors = [
        {
            "label": "Min W' balance",
            "min_balance_j": usage.get("min_balance_j"),
            "min_balance_pct": usage.get("min_balance_pct"),
            "critical_depletions_count": usage.get("critical_depletions_count"),
            "fully_depleted": usage.get("fully_depleted"),
        }
    ]
    return _curve(
        curve_id="w_prime_balance",
        title="W' balance curve",
        x_key="time_s",
        x_unit="s",
        y_keys=[
            {"key": "w_prime_balance_pct", "unit": "%", "label": "W' balance"},
            {"key": "power_w", "unit": "W", "label": "Power"},
        ],
        measurement_tier=MODEL_ESTIMATE,
        points=points,
        anchors=anchors,
        confidence_score=0.74,
        limitations=["W' balance depends on CP, W' and reconstitution tau assumptions."],
        frontend_hint={"chart_type": "line", "show_anchors": True, "multi_series": True},
    ) | {"summary": usage}


def build_durability_decay_curve(
    power_stream: Optional[Sequence[float]],
    *,
    duration_s: Optional[float] = None,
    ftp_w: Optional[float] = None,
) -> Dict[str, Any]:
    """Build hour-by-hour durability/decay curve from long ride power."""
    power = _clean_power(power_stream)
    duration = int(duration_s or len(power))
    if len(power) < 3600 or duration < 3600:
        return _curve(
            curve_id="durability_decay",
            title="Durability decay",
            x_key="hour",
            x_unit="h",
            y_keys=[{"key": "average_power_w", "unit": "W", "label": "Hourly avg power"}],
            measurement_tier=INSUFFICIENT_DATA,
            points=[],
            confidence_score=0.0,
            limitations=["Requires at least one hour of power data; two hours are preferable for durability."],
        )
    raw = generate_hourly_decay_curve(power, duration)
    if raw.get("status") != "success":
        return _curve(
            curve_id="durability_decay",
            title="Durability decay",
            x_key="hour",
            x_unit="h",
            y_keys=[{"key": "average_power_w", "unit": "W", "label": "Hourly avg power"}],
            measurement_tier=INSUFFICIENT_DATA,
            points=[],
            confidence_score=0.0,
            limitations=["Durability curve could not be generated from the supplied power stream."],
        )
    ftp = _finite_float(ftp_w)
    points = []
    for row in raw.get("hourly_data", []):
        avg = _finite_float(row.get("average_power")) or 0.0
        item = {"hour": int(row.get("hour", len(points) + 1)), "average_power_w": round(avg, 1)}
        if ftp and ftp > 0:
            item["pct_ftp"] = round(avg / ftp * 100.0, 1)
        points.append(item)
    confidence = 0.62 + min(0.2, max(0, len(points) - 1) * 0.06)
    return _curve(
        curve_id="durability_decay",
        title="Durability decay curve",
        x_key="hour",
        x_unit="h",
        y_keys=[{"key": "average_power_w", "unit": "W", "label": "Hourly avg power"}],
        measurement_tier=MODEL_ESTIMATE,
        points=points,
        anchors=[{"label": "Decay rate", "decay_rate_w_per_h": raw.get("decay_rate_watts_per_hour")}],
        confidence_score=confidence,
        limitations=["Hourly decay depends on ride structure, terrain, fueling and pacing."],
    ) | {"summary": raw}


def build_post_effort_recovery_curve(
    power_stream: Optional[Sequence[float]],
    *,
    cp_w: Optional[float] = None,
    w_prime_j: Optional[float] = None,
    ftp_w: Optional[float] = None,
    dt_s: float = 1.0,
) -> Dict[str, Any]:
    """Estimate recovery trajectory after a session.

    This is a conservative coach-facing model estimate. It is not a biomarker
    measurement and should be combined with readiness/HRV/soreness when available.
    """
    power = _clean_power(power_stream)
    if len(power) < 2:
        return _curve(
            curve_id="post_effort_recovery",
            title="Post-effort recovery",
            x_key="hours_after_session",
            x_unit="h",
            y_keys=[{"key": "recovery_pct", "unit": "%", "label": "Estimated recovery"}],
            measurement_tier=INSUFFICIENT_DATA,
            points=[],
            confidence_score=0.0,
            limitations=["Requires a power stream to estimate post-effort recovery."],
        )

    anchor = _finite_float(ftp_w) or _finite_float(cp_w)
    load = _session_load(power, dt_s=dt_s, anchor_w=anchor)
    duration_h = float(load["duration_s"]) / 3600.0
    intensity = float(load.get("intensity_factor") or 0.0)
    estimated_tss = float(load.get("estimated_tss") or 0.0)

    depletion_penalty_h = 0.0
    w_prime = _finite_float(w_prime_j)
    cp = _finite_float(cp_w)
    if cp and w_prime and cp > 0 and w_prime > 0:
        wbal = calculate_w_prime_balance(power, cp=cp, w_prime=w_prime, dt_s=max(dt_s, 0.1))
        min_pct = min(wbal) / w_prime * 100.0 if len(wbal) else 100.0
        if min_pct < 20:
            depletion_penalty_h += 12.0
        elif min_pct < 40:
            depletion_penalty_h += 6.0
    else:
        min_pct = None

    recovery_hours = 6.0 + duration_h * 8.0 + max(0.0, intensity - 0.55) * 26.0 + estimated_tss * 0.10 + depletion_penalty_h
    recovery_hours = max(6.0, min(72.0, recovery_hours))
    if recovery_hours < 18:
        severity = "low"
        next_session = "Endurance or skills work usually acceptable if subjective readiness is normal."
    elif recovery_hours < 36:
        severity = "moderate"
        next_session = "Prefer endurance or recovery before another high-intensity session."
    else:
        severity = "high"
        next_session = "Avoid high-intensity work until readiness and sensations recover."

    points = []
    for hour in [0, 6, 12, 18, 24, 36, 48, 72]:
        recovery = 100.0 * (1.0 - np.exp(-float(hour) / max(recovery_hours / 2.2, 1.0)))
        points.append({
            "hours_after_session": hour,
            "recovery_pct": round(min(100.0, recovery), 1),
            "fatigue_remaining_pct": round(max(0.0, 100.0 - recovery), 1),
        })

    confidence = 0.54
    confidence += 0.08 if anchor else 0.0
    confidence += 0.08 if cp and w_prime else 0.0
    return _curve(
        curve_id="post_effort_recovery",
        title="Post-effort recovery estimate",
        x_key="hours_after_session",
        x_unit="h",
        y_keys=[
            {"key": "recovery_pct", "unit": "%", "label": "Estimated recovery"},
            {"key": "fatigue_remaining_pct", "unit": "%", "label": "Fatigue remaining"},
        ],
        measurement_tier=HEURISTIC,
        points=points,
        anchors=[{"label": "Estimated recovery time", "hours": round(recovery_hours, 1), "severity": severity}],
        confidence_score=confidence,
        limitations=[
            "Estimated from power/load only; not a direct recovery measurement.",
            "Use HRV, sleep, soreness and athlete feedback before making return-to-intensity decisions.",
        ],
        frontend_hint={"chart_type": "line", "show_anchors": True, "multi_series": True},
    ) | {
        "summary": {
            "estimated_recovery_hours": round(recovery_hours, 1),
            "recovery_severity": severity,
            "recommended_next_session": next_session,
            "session_load": load,
            "min_w_prime_balance_pct": round(min_pct, 1) if min_pct is not None else None,
        }
    }


def build_session_performance_curves(
    *,
    power_stream: Optional[Sequence[float]],
    cp_w: Optional[float] = None,
    w_prime_j: Optional[float] = None,
    ftp_w: Optional[float] = None,
    dt_s: float = 1.0,
    duration_s: Optional[float] = None,
    include_curves: Optional[Sequence[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build optional session curves for the unified coach curve bundle."""
    include = set(include_curves or ["w_prime_balance", "durability_decay", "post_effort_recovery"])
    curves: Dict[str, Dict[str, Any]] = {}
    if "w_prime_balance" in include:
        curves["w_prime_balance"] = build_w_prime_balance_curve(
            power_stream,
            cp_w=cp_w,
            w_prime_j=w_prime_j,
            dt_s=dt_s,
        )
    if "durability_decay" in include:
        curves["durability_decay"] = build_durability_decay_curve(
            power_stream,
            duration_s=duration_s,
            ftp_w=ftp_w,
        )
    if "post_effort_recovery" in include:
        curves["post_effort_recovery"] = build_post_effort_recovery_curve(
            power_stream,
            cp_w=cp_w,
            w_prime_j=w_prime_j,
            ftp_w=ftp_w,
            dt_s=dt_s,
        )
    return curves
