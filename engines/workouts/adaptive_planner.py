"""Adapt planned workouts from readiness and compliance."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from engines.core.metric_contracts import annotate_payload, normalize_compliance_score

_VERY_HIGH_INTENSITY_TYPES = frozenset({"vo2", "vo2max", "anaerobic", "hiit"})


def _normalize_session_type(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _compute_factors(score: int, compliance: float) -> Tuple[float, float, str]:
    """Return intensity_factor, volume_factor, and reason."""
    if score < 45 or compliance < 0.5:
        return 0.85, 0.65, "reduce_load"
    if score < 65 or compliance < 0.7:
        return 0.92, 0.84, "slightly_reduce_load"
    if score > 85 and compliance > 0.9:
        return 1.05, 1.05, "small_progression"
    return 1.0, 1.0, "keep_plan"


def _adapt_session_type(session_type: str, reason: str) -> Tuple[str, Optional[str]]:
    """Downgrade high-intensity session types when readiness/compliance is low."""
    if not session_type:
        return session_type, None
    if reason == "reduce_load":
        if session_type in _VERY_HIGH_INTENSITY_TYPES or session_type in {"threshold", "interval", "race", "quality"}:
            return "endurance", session_type
        if session_type == "long_endurance":
            return "endurance", session_type
    elif reason == "slightly_reduce_load":
        if session_type in _VERY_HIGH_INTENSITY_TYPES:
            return "threshold", session_type
    return session_type, None


def _resolve_compliance(last_compliance: Optional[Dict[str, Any]]) -> float:
    if not last_compliance:
        return 0.8
    raw = last_compliance.get("compliance_score")
    if raw is None:
        raw = last_compliance.get("score")
    if raw is None:
        return 0.8
    normalized = normalize_compliance_score(raw)
    return 0.8 if normalized is None else normalized


def adapt_plan(
    plan: List[Dict[str, Any]],
    *,
    readiness: Optional[Dict[str, Any]] = None,
    last_compliance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    score = int((readiness or {}).get("readiness_score") or 70)
    compliance = _resolve_compliance(last_compliance)
    intensity_factor, volume_factor, reason = _compute_factors(score, compliance)
    load_factor = round((intensity_factor + volume_factor) / 2.0, 4)

    adapted: List[Dict[str, Any]] = []
    for item in plan:
        new = dict(item)
        session_type = _normalize_session_type(new.get("type") or new.get("session_type"))
        if session_type:
            adapted_type, previous_type = _adapt_session_type(session_type, reason)
            if previous_type is not None:
                new["type"] = adapted_type
                new["session_type_adapted_from"] = previous_type

        if "target_w" in new:
            new["target_w"] = int(round(float(new["target_w"]) * intensity_factor))
        for duration_key in ("duration_min", "duration_s"):
            if duration_key in new:
                new[duration_key] = max(1, int(round(float(new[duration_key]) * volume_factor)))
        if "load" in new:
            new["load"] = round(float(new["load"]) * load_factor, 1)
        adapted.append(new)

    payload = {
        "status": "success",
        "schema_version": "1.0.0",
        "intensity_factor": round(intensity_factor, 2),
        "volume_factor": round(volume_factor, 2),
        # Legacy combined scalar kept for callers that still read adjustment_factor.
        "adjustment_factor": round(load_factor, 2),
        "reason": reason,
        "adapted_plan": adapted,
    }
    return annotate_payload(
        payload,
        module_name="adaptive_planner",
        method="readiness_compliance_adjustment",
        confidence=0.65,
    )
