"""Simple XML workout exporter."""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List


def export_zwo(workout: Dict[str, Any]) -> Dict[str, Any]:
    name = str(workout.get("name") or "Structured Workout")
    steps: List[Dict[str, Any]] = workout.get("steps") or []
    parts = ["<workout_file>", f"  <name>{escape(name)}</name>", "  <workout>"]
    for step in steps:
        dur = int(float(step.get("duration_s") or step.get("duration") or 60))
        watts = step.get("target_w") or step.get("power_w")
        pct = step.get("target_pct") or step.get("power_pct")
        power = float(pct) if pct is not None else (float(watts) / 300.0 if watts else 0.55)
        tag = "SteadyState" if str(step.get("type", "work")).lower() not in {"warmup", "cooldown"} else str(step.get("type")).title()
        parts.append(f"    <{tag} Duration=\"{dur}\" Power=\"{power:.3f}\" />")
    parts += ["  </workout>", "</workout_file>"]
    return {"status": "success", "format": "xml_workout", "filename": _safe_name(name) + ".zwo", "content": "\n".join(parts)}


def _safe_name(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_") or "workout"
