"""Female athlete optional context — respectful, non-prescriptive, not medical."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload

SCHEMA_VERSION = "female_athlete_context.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_female_athlete_context(
    *,
    athlete_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    checkin: Optional[Dict[str, Any]] = None,
    twin_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Optional self-reported context — never auto-prescribe from cycle phase."""
    twin = twin_state or {}
    ctx = dict(context or twin.get("female_athlete_context_state") or {})
    checkin_data = checkin or twin.get("checkin_state") or {}

    if not ctx and not any(
        checkin_data.get(k) is not None
        for k in ("energy", "sleep_quality", "symptoms", "cycle_phase")
    ):
        return annotate_payload(
            {
                "status": "success",
                "schema_version": SCHEMA_VERSION,
                "measurement_tier": PRESCRIPTION_MODEL,
                "athlete_id": athlete_id,
                "female_athlete_context": {
                    "status": "not_reported",
                    "coach_note": "Optional context not provided. Use subjective readiness like any athlete.",
                    "auto_prescription_from_cycle": False,
                    "not_a_diagnosis": True,
                },
                "limitations": [
                    "Female athlete context is optional and self-reported.",
                    "Never use cycle phase alone to prescribe training intensity.",
                ],
            },
            module_name="female_athlete_context_engine",
            method="build_female_athlete_context",
            confidence=0.3,
        )

    symptoms = ctx.get("symptoms") or checkin_data.get("symptoms") or []
    if isinstance(symptoms, str):
        symptoms = [symptoms]

    energy = _num(ctx.get("energy") or checkin_data.get("energy"))
    sleep = _num(ctx.get("sleep_quality") or checkin_data.get("sleep_quality"))
    pain = _num(ctx.get("pain") or checkin_data.get("joint_pain"))
    irregular = bool(ctx.get("menstrual_irregularity") or ctx.get("amenorrhea_reported"))
    cycle_phase = ctx.get("cycle_phase")  # self-reported only, not used for prescription

    coach_notes: List[str] = [
        "Use subjective symptoms and readiness, not automatic cycle-based prescription.",
    ]
    professional_review = False

    if irregular:
        professional_review = True
        coach_notes.append(
            "Menstrual irregularity reported — consider qualified clinical/nutrition review before load increase."
        )
    if energy is not None and energy <= 4:
        coach_notes.append("Low energy reported — prioritize recovery and fueling conversation.")
    if pain is not None and pain >= 7:
        coach_notes.append("Elevated pain reported — review load and medical flags with coach.")
    if sleep is not None and sleep <= 4:
        coach_notes.append("Poor sleep reported — avoid stacking intensity without recovery.")

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete_id,
        "female_athlete_context": {
            "status": "optional_context_available",
            "cycle_phase_reported": cycle_phase,
            "symptoms_reported": list(symptoms) if isinstance(symptoms, list) else [],
            "energy": energy,
            "sleep_quality": sleep,
            "pain": pain,
            "menstrual_irregularity": irregular,
            "coach_note": " ".join(coach_notes),
            "professional_review_recommended": professional_review,
            "auto_prescription_from_cycle": False,
            "not_a_diagnosis": True,
        },
        "limitations": [
            "This is not medical or hormonal diagnosis.",
            "Cycle phase is informational only — coach interprets with athlete context.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="female_athlete_context_engine",
        method="build_female_athlete_context",
        confidence=0.5 if ctx else 0.4,
    )
