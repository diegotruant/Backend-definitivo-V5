"""Decision rules for adaptive load recommendations."""

from __future__ import annotations

from typing import Any, Dict


def generate_recommendation(
    *,
    session_load: Dict[str, Any],
    trend: Dict[str, Any],
    readiness: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a transparent green/yellow/red/blue recommendation."""
    risk_points = 0
    opportunity_points = 0
    reasons: list[str] = []

    session_score = session_load.get("score")
    load_ratio = trend.get("load_ratio")
    tsb = trend.get("tsb")
    readiness_score = readiness.get("score")
    thermal = ((session_load.get("thermal_load") or {}).get("score"))
    autonomic = ((session_load.get("autonomic_load") or {}).get("autonomic_strain_score"))

    if session_score is not None and session_score >= 90:
        risk_points += 2
        reasons.append("session_load_very_high")
    elif session_score is not None and session_score >= 75:
        risk_points += 1
        reasons.append("session_load_high")

    if load_ratio is not None and load_ratio > 1.50:
        risk_points += 3
        reasons.append("load_ratio_above_1_50")
    elif load_ratio is not None and load_ratio > 1.30:
        risk_points += 1
        reasons.append("load_ratio_above_1_30")

    if tsb is not None and tsb < -25:
        risk_points += 2
        reasons.append("tsb_very_negative")
    elif tsb is not None and tsb < -15:
        risk_points += 1
        reasons.append("tsb_negative")

    if readiness_score is not None and readiness_score < 50:
        risk_points += 3
        reasons.append("readiness_low")
    elif readiness_score is not None and readiness_score < 65:
        risk_points += 1
        reasons.append("readiness_reduced")

    if thermal is not None and thermal >= 70:
        risk_points += 2
        reasons.append("thermal_strain_high")
    elif thermal is not None and thermal >= 50:
        risk_points += 1
        reasons.append("thermal_strain_moderate")

    if autonomic is not None and autonomic >= 70:
        risk_points += 1
        reasons.append("autonomic_strain_high")

    if readiness_score is not None and readiness_score >= 82:
        opportunity_points += 2
    if session_score is not None and session_score < 55:
        opportunity_points += 1
    if load_ratio is not None and 0.80 <= load_ratio <= 1.20:
        opportunity_points += 1
    if tsb is not None and -5 <= tsb <= 15:
        opportunity_points += 1

    if risk_points >= 5:
        status = "red"
        message = "Converging fatigue/stress signals: favor recovery or rest."
        modifier = {
            "volume_multiplier": 0.40,
            "intensity_cap": "Z1/Z2",
            "avoid": ["threshold", "VO2max", "anaerobic", "long_ride"],
        }
    elif risk_points >= 2:
        status = "yellow"
        message = "Load or recovery suboptimal: reduce volume or intensity."
        modifier = {
            "volume_multiplier": 0.70,
            "intensity_cap": "Z2/Z3",
            "avoid": ["VO2max", "anaerobic"],
        }
    elif opportunity_points >= 4:
        status = "blue"
        message = "Good readiness window: a key session is viable if planned."
        modifier = {
            "volume_multiplier": 1.0,
            "intensity_cap": None,
            "avoid": [],
        }
    else:
        status = "green"
        message = "Planned training is sustainable."
        modifier = {
            "volume_multiplier": 1.0,
            "intensity_cap": None,
            "avoid": [],
        }

    return {
        "status": status,
        "risk_points": risk_points,
        "opportunity_points": opportunity_points,
        "message": message,
        "reasons": reasons,
        "next_session_modifier": modifier,
    }
