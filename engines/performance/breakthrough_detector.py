"""Detect activity results that exceed the current performance model."""

from __future__ import annotations

from typing import Any, Dict, List

from engines.core.metric_contracts import annotate_payload


def _curve(raw: Any) -> Dict[int, float]:
    if isinstance(raw, dict) and "curve" in raw:
        raw = raw.get("curve")
    out: Dict[int, float] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                out[int(float(k))] = float(v)
            except Exception:
                pass
    return out


def detect_breakthroughs(
    baseline_curve: Dict[str, Any],
    activity_curve: Dict[str, Any],
    *,
    min_gain_pct: float = 1.5,
) -> Dict[str, Any]:
    base = _curve(baseline_curve)
    ride = _curve(activity_curve)
    events: List[Dict[str, Any]] = []
    for duration_s, value in ride.items():
        old = base.get(duration_s)
        if old is None or old <= 0:
            continue
        gain_pct = (float(value) - old) / old * 100.0
        if gain_pct >= min_gain_pct:
            events.append({"duration_s": duration_s, "previous_w": round(old, 1), "new_w": round(float(value), 1), "gain_pct": round(gain_pct, 2)})
    severity = "none"
    if any(e["gain_pct"] >= 5 for e in events):
        severity = "major"
    elif events:
        severity = "minor"
    payload = {"status": "success", "schema_version": "1.0.0", "breakthrough": bool(events), "severity": severity, "events": sorted(events, key=lambda e: e["duration_s"])}
    return annotate_payload(payload, module_name="breakthrough_detector", method="curve_exceedance", confidence=0.9 if base and ride else 0.3)
