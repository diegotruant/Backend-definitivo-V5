"""Progression levels for workout prescription."""

from __future__ import annotations

from typing import Any, Dict, List

from engines.core.metric_contracts import annotate_payload
from engines.performance.ability_profile import build_ability_profile

_ZONE_MAP = {
    "endurance": "endurance",
    "tempo": "endurance",
    "threshold": "threshold",
    "vo2": "vo2",
    "vo2max": "vo2",
    "anaerobic": "anaerobic",
    "sprint": "sprint",
}


def compute_progression_levels(athlete_profile: Dict[str, Any], workout_history: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    ability = build_ability_profile(athlete_profile, compliance_history=workout_history or [])
    levels = ability.get("levels", {})
    completed = workout_history or []
    zone_success: Dict[str, list[float]] = {k: [] for k in _ZONE_MAP.values()}
    for item in completed[-30:]:
        if not isinstance(item, dict):
            continue
        zone = _ZONE_MAP.get(str(item.get("target_zone") or item.get("zone") or "").lower())
        if not zone:
            continue
        try:
            zone_success[zone].append(float(item.get("compliance_score") or item.get("score") or 0))
        except Exception:
            pass
    adjusted = dict(levels)
    for zone, vals in zone_success.items():
        if vals:
            mean = sum(vals) / len(vals)
            mean_norm = mean / 100.0 if mean > 1.0 else mean
            adjusted[zone] = round(max(0.0, min(10.0, adjusted.get(zone, 5.0) + (mean_norm - 0.75) * 2.0)), 1)
    payload = {"status": "success", "schema_version": "1.0.0", "levels": adjusted, "ability_profile": ability}
    return annotate_payload(payload, module_name="progression_levels", method="ability_plus_compliance", confidence=0.75)
