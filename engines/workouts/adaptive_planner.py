"""Adapt planned workouts from readiness and compliance."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload


def adapt_plan(
    plan: List[Dict[str, Any]],
    *,
    readiness: Optional[Dict[str, Any]] = None,
    last_compliance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    score = int((readiness or {}).get("readiness_score") or 70)
    compliance = float((last_compliance or {}).get("compliance_score") or (last_compliance or {}).get("score") or 0.8)
    factor = 1.0
    reason = "keep_plan"
    if score < 45 or compliance < 0.5:
        factor = 0.75
        reason = "reduce_load"
    elif score < 65 or compliance < 0.7:
        factor = 0.88
        reason = "slightly_reduce_load"
    elif score > 85 and compliance > 0.9:
        factor = 1.05
        reason = "small_progression"
    adapted = []
    for item in plan:
        new = dict(item)
        if "target_w" in new:
            new["target_w"] = int(round(float(new["target_w"]) * factor))
        if "load" in new:
            new["load"] = round(float(new["load"]) * factor, 1)
        adapted.append(new)
    payload = {"status": "success", "schema_version": "1.0.0", "adjustment_factor": round(factor, 2), "reason": reason, "adapted_plan": adapted}
    return annotate_payload(payload, module_name="adaptive_planner", method="readiness_compliance_adjustment", confidence=0.65)
