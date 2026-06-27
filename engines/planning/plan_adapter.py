"""Week-level plan adaptation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload
from engines.workouts.adaptive_planner import adapt_plan


def adapt_week(week_plan: List[Dict[str, Any]], *, readiness: Optional[Dict[str, Any]] = None, compliance: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    result = adapt_plan(week_plan, readiness=readiness, last_compliance=compliance)
    payload = {
        "status": "success",
        "schema_version": "1.0.0",
        "week": result.get("adapted_plan", []),
        "intensity_factor": result.get("intensity_factor"),
        "volume_factor": result.get("volume_factor"),
        "adjustment_factor": result.get("adjustment_factor"),
        "reason": result.get("reason"),
    }
    return annotate_payload(payload, module_name="plan_adapter", method="week_adaptation", confidence=0.65)
