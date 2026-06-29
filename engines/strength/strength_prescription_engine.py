"""Physiology-first strength prescription for cyclists.

Starts from TwinState context (metabolic profile, load, readiness) — not from
a generic gym template.  Outputs blocks, interference rules and expected
adaptations for coach review.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from engines.coach.prescription_safety import evaluate_prescription_safety
from engines.core.metric_contracts import annotate_payload

PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"
SCHEMA_VERSION = "strength_prescription.v1"

GOALS = frozenset({
    "climbing",
    "sprint",
    "time_trial",
    "granfondo",
    "general_performance",
})

PHASES = frozenset({"off_season", "base", "build", "race", "taper"})
EXPERIENCE = frozenset({"novice", "intermediate", "advanced"})
MASS_STRATEGY = frozenset({"maintain", "reduce", "increase"})

HIGH_INTERFERENCE_SESSIONS = frozenset({
    "vo2max",
    "vo2",
    "anaerobic",
    "sprint",
    "race",
    "race_day",
    "hiit",
    "intervals",
})


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize(value: Any, allowed: frozenset[str], default: str) -> str:
    text = str(value or default).strip().lower().replace(" ", "_")
    return text if text in allowed else default


def _mmp_peak(mmp: Dict[str, Any], seconds: int) -> Optional[float]:
    for key in (str(seconds), seconds):
        value = _num(mmp.get(key))
        if value is not None and value > 0:
            return value
    return None


def _classify_primary_need(
    *,
    goal: str,
    metabolic_snapshot: Dict[str, Any],
    season_phase: str,
    body_mass_strategy: str,
    mmp: Dict[str, Any],
) -> Tuple[str, str, List[str]]:
    """Return primary_need, primary_goal label, and rationale bullets."""
    vo2max = _num(metabolic_snapshot.get("estimated_vo2max") or metabolic_snapshot.get("vo2max_ml_kg_min"))
    vlamax = _num(
        metabolic_snapshot.get("estimated_vlamax_mmol_L_s")
        or metabolic_snapshot.get("vlamax_mmol_L_s")
    )
    fatmax_w = _num(metabolic_snapshot.get("fatmax_power_watts") or metabolic_snapshot.get("fatmax_power_w"))
    mlss_w = _num(metabolic_snapshot.get("mlss_power_watts") or metabolic_snapshot.get("mlss_power_w"))
    peak_5s = _mmp_peak(mmp, 5)
    peak_60 = _mmp_peak(mmp, 60)
    ftp_proxy = mlss_w or _mmp_peak(mmp, 3600)

    reasons: List[str] = []

    if season_phase in {"race", "taper"}:
        reasons.append("Race/taper phase: prioritize maintenance and neural retention.")
        return "maintenance", "strength_maintenance", reasons

    if goal == "sprint" or (vlamax is not None and vlamax >= 0.55 and peak_5s and ftp_proxy and peak_5s / ftp_proxy > 2.2):
        if vlamax is not None and vlamax >= 0.55:
            reasons.append("High VLamax — limit glycolytic gym volume; focus max strength and power.")
        else:
            reasons.append("Sprint goal — raise force ceiling and neuromuscular power.")
        return "neuromuscular_power", "max_strength_neural", reasons

    if goal == "climbing" or body_mass_strategy == "reduce":
        reasons.append("Climber/light athlete — neural strength, minimal hypertrophy volume.")
        return "max_strength", "max_strength_neural", reasons

    if goal == "granfondo":
        reasons.append("Gran fondo — muscular endurance and posterior-chain resilience for late-race torque.")
        return "muscular_endurance", "strength_endurance_controlled", reasons

    if goal == "time_trial":
        reasons.append("TT focus — force ceiling + postural stability without excess mass.")
        return "structural_stability", "max_strength_posture", reasons

    if peak_60 and ftp_proxy and peak_60 / ftp_proxy < 1.35:
        reasons.append("Short-duration power low vs threshold — prioritize max strength and low-cadence torque.")
        return "low_cadence_torque", "max_strength_torque", reasons

    if vo2max and vo2max >= 58 and fatmax_w and mlss_w and fatmax_w / mlss_w < 0.62:
        reasons.append("Strong aerobic base with torque headroom — controlled max-strength block.")
        return "max_strength", "max_strength_neural", reasons

    reasons.append("General performance — balanced structural strength and maintenance.")
    return "structural_stability", "general_strength_support", reasons


def _interference_risk(
    *,
    load_state: Dict[str, Any],
    readiness_state: Dict[str, Any],
    upcoming_bike_sessions: Sequence[Dict[str, Any]],
) -> str:
    tsb = _num(load_state.get("tsb") or load_state.get("training_stress_balance"))
    readiness = _num(readiness_state.get("readiness_score") or readiness_state.get("score"))
    key_sessions = [
        str(s.get("type") or s.get("session_type") or "").lower().replace(" ", "_")
        for s in upcoming_bike_sessions
    ]
    if any(t in HIGH_INTERFERENCE_SESSIONS for t in key_sessions):
        return "high"
    if (tsb is not None and tsb < -15) or (readiness is not None and readiness < 50):
        return "moderate"
    return "low"


def _exercise_block(
    *,
    block: str,
    purpose: str,
    name: str,
    sets: int,
    reps: str,
    intensity: str,
    rest_s: int,
    alternatives: Sequence[str],
) -> Dict[str, Any]:
    return {
        "block": block,
        "purpose": purpose,
        "exercises": [
            {
                "name": name,
                "sets": sets,
                "reps": reps,
                "intensity": intensity,
                "rest_s": rest_s,
                "alternatives": list(alternatives),
            }
        ],
    }


def _build_sessions(
    *,
    primary_need: str,
    gym_experience: str,
    equipment: Sequence[str],
    days_available: int,
    safety: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if safety.get("status") == "requires_professional_review":
        return [
            {
                "session_id": "safety_mobility",
                "focus": "mobility_and_activation",
                "blocks": [
                    _exercise_block(
                        block="mobility",
                        purpose="Maintain range of motion without aggravating flagged issues",
                        name="hip_hinge_mobility_circuit",
                        sets=2,
                        reps="8-10",
                        intensity="RPE 3-4",
                        rest_s=45,
                        alternatives=["cat_camel", "worlds_greatest_stretch"],
                    )
                ],
            }
        ]

    equip = {str(e).lower() for e in equipment}
    leg_main = "trap_bar_deadlift" if "barbell" in equip else "leg_press"
    if "machines" in equip and leg_main == "leg_press":
        leg_alt = ["hack_squat", "split_squat"]
    else:
        leg_alt = ["split_squat", "step_up"]

    if primary_need in {"maintenance"} or safety.get("level") == "coach_review_recommended":
        return [
            {
                "session_id": "maintenance_a",
                "focus": "neural_maintenance",
                "blocks": [
                    _exercise_block(
                        block="max_strength",
                        purpose="Maintain force ceiling with minimal fatigue",
                        name=leg_main,
                        sets=3,
                        reps="3-4",
                        intensity="RPE 6-7",
                        rest_s=150,
                        alternatives=leg_alt,
                    ),
                    _exercise_block(
                        block="core",
                        purpose="Trunk stiffness for bike position",
                        name="pallof_press",
                        sets=2,
                        reps="10",
                        intensity="RPE 6",
                        rest_s=60,
                        alternatives=["dead_bug", "side_plank"],
                    ),
                ],
            }
        ]

    sessions: List[Dict[str, Any]] = []
    if primary_need in {"max_strength", "low_cadence_torque", "neuromuscular_power", "structural_stability"}:
        sessions.append({
            "session_id": "strength_a",
            "focus": "max_strength_lower",
            "blocks": [
                _exercise_block(
                    block="max_strength",
                    purpose="Increase force ceiling without unnecessary hypertrophy",
                    name=leg_main,
                    sets=4 if gym_experience != "novice" else 3,
                    reps="4" if primary_need != "neuromuscular_power" else "3",
                    intensity="RPE 7-8",
                    rest_s=180,
                    alternatives=leg_alt,
                ),
                _exercise_block(
                    block="posterior_chain",
                    purpose="Hip extension capacity for low-cadence torque",
                    name="romanian_deadlift" if "barbell" in equip else "hip_hinge_machine",
                    sets=3,
                    reps="5-6",
                    intensity="RPE 7",
                    rest_s=120,
                    alternatives=["single_leg_rdl", "back_extension"],
                ),
            ],
        })
        if days_available >= 2:
            sessions.append({
                "session_id": "strength_b",
                "focus": "upper_posture_power",
                "blocks": [
                    _exercise_block(
                        block="upper_strength",
                        purpose="Scapular and trunk support for sustained riding positions",
                        name="pull_up_or_lat_pulldown",
                        sets=3,
                        reps="5-8",
                        intensity="RPE 7",
                        rest_s=120,
                        alternatives=["seated_row", "face_pull"],
                    ),
                    _exercise_block(
                        block="power",
                        purpose="Rate of force development without glycolytic fatigue",
                        name="box_step_up_explosive",
                        sets=3,
                        reps="4",
                        intensity="RPE 7",
                        rest_s=120,
                        alternatives=["jump_squat_light", "med_ball_throw"],
                    ),
                ],
            })
    elif primary_need == "muscular_endurance":
        sessions.append({
            "session_id": "endurance_strength_a",
            "focus": "strength_endurance",
            "blocks": [
                _exercise_block(
                    block="strength_endurance",
                    purpose="Resist muscular fade in late-ride torque demands",
                    name="split_squat",
                    sets=3,
                    reps="12-15",
                    intensity="RPE 6-7",
                    rest_s=75,
                    alternatives=["walking_lunge", "step_up"],
                ),
                _exercise_block(
                    block="posterior_chain",
                    purpose="Posterior chain resilience for gran fondo fatigue",
                    name="hip_thrust" if "barbell" in equip else "glute_bridge",
                    sets=3,
                    reps="10-12",
                    intensity="RPE 6-7",
                    rest_s=75,
                    alternatives=["single_leg_bridge", "cable_pull_through"],
                ),
            ],
        })
    else:
        sessions.append({
            "session_id": "general_a",
            "focus": "general_strength",
            "blocks": [
                _exercise_block(
                    block="general_strength",
                    purpose="Structural support for cycling performance",
                    name=leg_main,
                    sets=3,
                    reps="6",
                    intensity="RPE 7",
                    rest_s=120,
                    alternatives=leg_alt,
                )
            ],
        })
    return sessions[: max(1, min(days_available, 3))]


def _bike_conflict_rules(
    *,
    interference: str,
    upcoming_bike_sessions: Sequence[Dict[str, Any]],
    load_state: Dict[str, Any],
    readiness_state: Dict[str, Any],
) -> Dict[str, Any]:
    types = sorted({
        str(s.get("type") or s.get("session_type") or "").lower().replace(" ", "_")
        for s in upcoming_bike_sessions
        if s.get("type") or s.get("session_type")
    })
    avoid = [t for t in types if t in HIGH_INTERFERENCE_SESSIONS] or list(HIGH_INTERFERENCE_SESSIONS)
    gap_h = 48 if interference == "high" else 36 if interference == "moderate" else 24
    return {
        "avoid_heavy_lower_body_before": avoid,
        "minimum_gap_h_before_key_session": gap_h,
        "preferred_pairing": "same_day_after_easy_ride_or_separate_day",
        "reduce_volume_if": [
            "ATL_high",
            "TSB_negative",
            "readiness_low",
        ],
        "notes": [
            "Schedule heavy lower-body work only when the next 36-48 h do not include VO2max, sprints or race.",
            "Prefer easy endurance earlier in the day if pairing gym and bike on the same day.",
        ],
    }


def prescribe_strength(
    *,
    athlete: Optional[Dict[str, Any]] = None,
    twin_state: Optional[Dict[str, Any]] = None,
    metabolic_snapshot: Optional[Dict[str, Any]] = None,
    metabolic_curves: Optional[Dict[str, Any]] = None,
    load_state: Optional[Dict[str, Any]] = None,
    readiness_state: Optional[Dict[str, Any]] = None,
    goal: str = "general_performance",
    season_phase: str = "base",
    gym_experience: str = "intermediate",
    equipment: Optional[Sequence[str]] = None,
    days_available: int = 2,
    injury_flags: Optional[Sequence[str]] = None,
    body_mass_strategy: str = "maintain",
    upcoming_bike_sessions: Optional[Sequence[Dict[str, Any]]] = None,
    mmp: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a physiology-first strength prescription for coach review."""
    twin = twin_state or {}
    snapshot = metabolic_snapshot or twin.get("metabolic_snapshot") or {}
    load = load_state or twin.get("load_state") or {}
    readiness = readiness_state or twin.get("readiness_state") or {}
    curves = metabolic_curves or twin.get("metabolic_curves") or {}
    mmp_data = mmp or twin.get("rolling_power_curve") or {}
    athlete_data = athlete or twin.get("athlete_profile") or {}

    goal_n = _normalize(goal, GOALS, "general_performance")
    phase_n = _normalize(season_phase, PHASES, "base")
    exp_n = _normalize(gym_experience, EXPERIENCE, "intermediate")
    mass_n = _normalize(body_mass_strategy, MASS_STRATEGY, "maintain")
    equip = list(equipment or ["barbell", "dumbbells"])
    upcoming = list(upcoming_bike_sessions or [])

    safety = evaluate_prescription_safety(
        injury_flags=injury_flags,
        readiness_state=readiness,
        load_state=load,
    )

    primary_need, primary_goal, need_reasons = _classify_primary_need(
        goal=goal_n,
        metabolic_snapshot=snapshot,
        season_phase=phase_n,
        body_mass_strategy=mass_n,
        mmp=mmp_data if isinstance(mmp_data, dict) else {},
    )

    interference = _interference_risk(
        load_state=load,
        readiness_state=readiness,
        upcoming_bike_sessions=upcoming,
    )

    sessions = _build_sessions(
        primary_need=primary_need,
        gym_experience=exp_n,
        equipment=equip,
        days_available=max(1, min(int(days_available or 2), 4)),
        safety=safety,
    )

    hypertrophy_risk = "low"
    if mass_n == "increase" and primary_need not in {"maintenance"}:
        hypertrophy_risk = "moderate"
    if mass_n == "reduce" or goal_n == "climbing":
        hypertrophy_risk = "low"

    payload: Dict[str, Any] = {
        "status": "success" if safety.get("status") != "requires_professional_review" else "requires_professional_review",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "primary_need": primary_need,
        "primary_goal": primary_goal,
        "weekly_frequency": len(sessions),
        "interference_risk": interference,
        "sessions": sessions,
        "progression": {
            "model": "double_progression_or_load_when_all_sets_clean",
            "weeks_before_deload": 3 if phase_n in {"build", "base"} else 2,
            "stop_rule": "Do not add load if readiness < 55 or TSB < -20.",
        },
        "deload_rule": {
            "trigger": ["readiness_low_3d", "tsb_below_-25", "missed_key_bike_sessions"],
            "action": "Reduce sets by 30-40% and keep intensity submaximal (RPE 6).",
        },
        "bike_conflict_rules": _bike_conflict_rules(
            interference=interference,
            upcoming_bike_sessions=upcoming,
            load_state=load,
            readiness_state=readiness,
        ),
        "strength_target": {
            "goal": "raise_force_ceiling",
            "hypertrophy_risk": hypertrophy_risk,
            "fatigue_cost": "moderate" if primary_need in {"max_strength", "neuromuscular_power"} else "low",
            "body_mass_sensitivity": "high" if mass_n == "reduce" else "moderate",
            "recommended_phase": "base" if phase_n == "off_season" else phase_n,
            "maintenance_phase": "race",
        },
        "expected_adaptations": need_reasons
        + [
            "Improved force reserve at cycling-relevant joint angles.",
            "Better low-cadence torque without replacing on-bike specificity.",
        ],
        "decision_safety": safety,
        "limitations": [
            "Prescription model based on metabolic profile and load state — not a substitute for in-person S&C coaching.",
            "Exercise selection must respect equipment availability and injury history.",
            "No 1RM testing is implied; use RPE and technical quality as guardrails.",
        ],
        "context_used": {
            "goal": goal_n,
            "season_phase": phase_n,
            "gym_experience": exp_n,
            "body_mass_strategy": mass_n,
            "metabolic_curves_available": bool(curves),
            "athlete_weight_kg": athlete_data.get("weight_kg"),
        },
    }
    if safety.get("safe_output"):
        payload["safe_output"] = safety["safe_output"]
        payload["reason"] = safety.get("reason")

    return annotate_payload(
        payload,
        module_name="strength_prescription_engine",
        method="physiology_first_prescription",
        confidence=0.68 if safety.get("status") == "ok" else 0.45,
    )
