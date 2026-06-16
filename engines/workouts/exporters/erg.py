"""ERG structured workout exporter."""

from __future__ import annotations

from typing import Any, Dict, List


def export_erg(workout: Dict[str, Any]) -> Dict[str, Any]:
    name = str(workout.get("name") or "Structured Workout")
    steps: List[Dict[str, Any]] = workout.get("steps") or []
    elapsed_min = 0.0
    rows = ["[COURSE HEADER]", f"VERSION = 2", f"UNITS = ENGLISH", f"DESCRIPTION = {name}", "[END COURSE HEADER]", "[COURSE DATA]"]
    last_w = None
    for step in steps:
        watts = int(float(step.get("target_w") or step.get("power_w") or last_w or 150))
        dur_min = float(step.get("duration_s") or step.get("duration") or 60) / 60.0
        rows.append(f"{elapsed_min:.2f}\t{watts}")
        elapsed_min += dur_min
        rows.append(f"{elapsed_min:.2f}\t{watts}")
        last_w = watts
    rows.append("[END COURSE DATA]")
    return {"status": "success", "format": "erg", "filename": _safe_name(name) + ".erg", "content": "\n".join(rows)}


def _safe_name(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_") or "workout"
