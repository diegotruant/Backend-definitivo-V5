"""Template and prescription helpers for workout library flows."""

from __future__ import annotations

from typing import Any, Dict

from .models import materialize_workout, validate_workout_payload


def validate_template(payload: Dict[str, Any]) -> Dict[str, Any]:
    return validate_workout_payload(payload)


def prescribe_for_athlete(workout: Dict[str, Any], athlete_profile: Dict[str, Any]) -> Dict[str, Any]:
    resolved = materialize_workout(workout, athlete_profile)
    return {
        "status": "success",
        "prescription": resolved,
        "athlete_profile_used": {
            "cp_w": athlete_profile.get("cp_w") or athlete_profile.get("critical_power_w"),
            "ftp_w": athlete_profile.get("ftp_w") or athlete_profile.get("ftp"),
            "weight_kg": athlete_profile.get("weight_kg"),
        },
    }
