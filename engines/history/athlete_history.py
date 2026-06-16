"""Athlete history summaries from persisted activity lists."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload
from engines.history.load_trends import compute_load_trends
from engines.history.power_curve_history import build_power_curve_history


def compute_personal_records(activities: List[Dict[str, Any]], *, weight_kg: Optional[float] = None) -> Dict[str, Any]:
    records: Dict[str, Dict[str, Any]] = {}
    for activity in activities:
        activity_id = activity.get("activity_id") or activity.get("id")
        activity_date = activity.get("date") or activity.get("start_date") or activity.get("activity_date")
        raw = activity.get("mmp") or activity.get("power_curve") or activity.get("best_efforts") or {}
        items = []
        if isinstance(raw, dict):
            items = [{"duration_s": int(float(k)), "value": float(v)} for k, v in raw.items()]
        elif isinstance(raw, list):
            for it in raw:
                if isinstance(it, dict) and (it.get("duration_s") or it.get("duration")) and (it.get("value") or it.get("power_w") or it.get("avg_power_w")):
                    items.append({"duration_s": int(float(it.get("duration_s") or it.get("duration"))), "value": float(it.get("value") or it.get("power_w") or it.get("avg_power_w"))})
        for item in items:
            key = str(item["duration_s"])
            value = float(item["value"])
            if key not in records or value > records[key]["value"]:
                records[key] = {
                    "duration_s": item["duration_s"],
                    "value": round(value, 1),
                    "value_per_kg": round(value / weight_kg, 2) if weight_kg and weight_kg > 0 else None,
                    "activity_id": activity_id,
                    "date": activity_date,
                }
    return {"status": "success", "records": [records[k] for k in sorted(records, key=lambda x: int(x))]}


def build_history_summary(
    activities: List[Dict[str, Any]],
    *,
    as_of: Optional[str] = None,
    weight_kg: Optional[float] = None,
) -> Dict[str, Any]:
    power_curves = build_power_curve_history(activities, as_of=as_of, weight_kg=weight_kg)
    load = compute_load_trends(activities, as_of=as_of)
    records = compute_personal_records(activities, weight_kg=weight_kg)
    payload = {
        "status": "success",
        "schema_version": "1.0.0",
        "activity_count": len(activities),
        "power_curve_history": power_curves,
        "load_trends": load,
        "personal_records": records,
    }
    return annotate_payload(payload, module_name="athlete_history", method="summary", confidence=0.8 if len(activities) >= 5 else 0.4)
