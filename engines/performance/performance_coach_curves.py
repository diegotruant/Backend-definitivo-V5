"""Coach-facing performance/session curves.

Session curves that are indispensable for coach reports but are not metabolic
snapshot curves: W' balance and durability decay.  The output follows the same
frontend contract used by metabolic coach curves.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from engines.performance.durability_engine import generate_hourly_decay_curve
from engines.performance.w_prime_balance_engine import analyze_w_prime_usage, calculate_w_prime_balance

MODEL_ESTIMATE = "MODEL_ESTIMATE"
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
    include = set(include_curves or ["w_prime_balance", "durability_decay"])
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
    return curves
