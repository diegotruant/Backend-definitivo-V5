"""MRC structured workout exporter."""

from __future__ import annotations

from typing import Any, Dict, List


def export_mrc(workout: Dict[str, Any]) -> Dict[str, Any]:
    name = str(workout.get("name") or "Structured Workout")
    ftp = float(workout.get("ftp_w") or workout.get("ftp") or 300)
    steps: List[Dict[str, Any]] = workout.get("steps") or []
    elapsed_min = 0.0
    rows = ["[COURSE HEADER]", "VERSION = 2", "UNITS = ENGLISH", f"DESCRIPTION = {name}", "[END COURSE HEADER]", "[COURSE DATA]"]
    for step in steps:
        watts = float(step.get("target_w") or step.get("power_w") or ftp * float(step.get("target_pct") or 0.6))
        pct = max(0.0, watts / ftp * 100.0)
        dur_min = float(step.get("duration_s") or step.get("duration") or 60) / 60.0
        rows.append(f"{elapsed_min:.2f}\t{pct:.1f}")
        elapsed_min += dur_min
        rows.append(f"{elapsed_min:.2f}\t{pct:.1f}")
    rows.append("[END COURSE DATA]")
    return {"status": "success", "format": "mrc", "filename": _safe_name(name) + ".mrc", "content": "\n".join(rows)}


def _safe_name(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_") or "workout"
