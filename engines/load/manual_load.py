"""Manual load injection for non-cycling fatigue.

This is a declared scope bridge, not a full strength/running physiology model:
RPE × duration is converted into a training-load equivalent with modality and
muscle-damage modifiers so the twin is not blind to gym, running or life stress.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if np.isnan(out) or np.isinf(out):
        return default
    return out


def calculate_manual_load(
    *,
    duration_min: float,
    rpe: float,
    modality: str = "other",
    muscle_damage_factor: Optional[float] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    duration_min = max(0.0, float(duration_min))
    rpe = max(0.0, min(10.0, float(rpe)))
    modality_l = (modality or "other").lower()
    modality_factor = {
        "cycling": 1.00,
        "bike": 1.00,
        "running": 1.25,
        "run": 1.25,
        "strength": 0.80,
        "gym": 0.80,
        "mobility": 0.35,
        "other": 0.75,
    }.get(modality_l, 0.75)
    default_damage = 1.25 if modality_l in {"running", "run", "strength", "gym"} else 1.0
    damage = max(0.2, min(2.5, _num(muscle_damage_factor, default_damage) or default_damage))
    session_rpe_load = duration_min * rpe
    trimp_equivalent = session_rpe_load * modality_factor / 10.0
    recovery_cost = trimp_equivalent * damage
    readiness_modifier = -min(35.0, recovery_cost / 8.0)
    return {
        "status": "success",
        "schema_version": "manual_load.v1",
        "input": {
            "duration_min": round(duration_min, 1),
            "rpe": round(rpe, 1),
            "modality": modality_l,
            "muscle_damage_factor": round(damage, 2),
            "notes": notes,
        },
        "load": {
            "session_rpe_load": round(session_rpe_load, 1),
            "training_load_equivalent": round(trimp_equivalent, 1),
            "recovery_cost": round(recovery_cost, 1),
            "readiness_modifier": round(readiness_modifier, 1),
        },
        "scope_note": "Manual load is a declared approximation for non-cycling fatigue; it should not be interpreted as a cycling power-derived load.",
    }
