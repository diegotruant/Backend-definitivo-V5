"""Coach orchestrator — daily brief and session decision from unified context."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.coach.adherence_engine import evaluate_adherence
from engines.coach.attention_engine import evaluate_athlete_attention
from engines.coach.communication_draft_engine import build_communication_draft
from engines.coach.constraints_engine import evaluate_constraints
from engines.coach.decision_safety_engine import evaluate_decision_safety
from engines.coach.equipment_comfort_engine import evaluate_equipment_comfort
from engines.coach.female_athlete_context_engine import build_female_athlete_context
from engines.coach.injury_illness_engine import evaluate_training_safety
from engines.coach.pnei_context_engine import build_pnei_context
from engines.coach.testing_scheduler_engine import build_testing_plan
from engines.core.metric_contracts import annotate_payload
from engines.endocrine.endocrine_context_engine import build_endocrine_context

SCHEMA_DAILY = "coach_daily_brief.v1"
SCHEMA_SESSION = "coach_session_decision.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"

_INTENSITY_KEYWORDS = {
    "vo2": "high",
    "anaerobic": "high",
    "threshold": "moderate_high",
    "interval": "moderate_high",
    "gym": "moderate_high",
    "strength": "moderate_high",
    "endurance": "low",
    "zone2": "low",
    "recovery": "low",
    "mobility": "low",
}


def _session_intensity(planned_session: Dict[str, Any]) -> str:
    text = " ".join(
        str(planned_session.get(k) or "")
        for k in ("type", "name", "description", "focus")
    ).lower()
    for keyword, level in _INTENSITY_KEYWORDS.items():
        if keyword in text:
            return level
    return "moderate"


def _downgrade_session(planned: Dict[str, Any], reason: str) -> Dict[str, Any]:
    intensity = _session_intensity(planned)
    if intensity in {"high", "moderate_high"}:
        return {
            "recommendation": "downgrade",
            "replacement": {
                "type": "endurance_easy",
                "duration_min": planned.get("duration_min") or 60,
                "focus": "zone2_and_mobility",
            },
            "reason": reason,
        }
    return {
        "recommendation": "modify",
        "replacement": {
            "type": planned.get("type") or "endurance",
            "duration_min": max(30, int((planned.get("duration_min") or 60) * 0.8)),
            "focus": "reduce_density",
        },
        "reason": reason,
    }


def _priority_actions(
    *,
    attention: Dict[str, Any],
    decision_safety: Dict[str, Any],
    pnei: Dict[str, Any],
    adherence: Optional[Dict[str, Any]],
    testing: Optional[Dict[str, Any]],
    equipment: Optional[Dict[str, Any]],
) -> List[str]:
    actions: List[str] = []
    attn = attention.get("athlete_attention") or attention
    if attn.get("priority") == "high":
        actions.append(attn.get("recommended_coach_action") or "Check in before prescribing intensity.")

    safety = decision_safety.get("decision_safety") or decision_safety
    if safety.get("level") != "ok_to_auto_suggest":
        actions.append(safety.get("human_action") or "Review safety gate before progressing.")

    pnei_ctx = pnei.get("pnei_context") or pnei
    if pnei_ctx.get("status") in {"caution", "human_review", "professional_review"}:
        actions.append(pnei_ctx.get("human_action") or "PNEI context suggests load modification.")

    if adherence:
        comp = adherence.get("compliance") or {}
        if comp.get("missed_key_work"):
            actions.append(comp.get("coach_note") or "Review adherence before progressing.")

    if testing:
        rec = testing.get("testing_recommendation") or {}
        if rec.get("priority") == "high":
            actions.append(f"Priority test: {rec.get('test')} — {rec.get('reason', 'calibration weak')}.")

    if equipment:
        review = equipment.get("equipment_comfort_review") or equipment
        if review.get("status") in {"review_recommended", "high_priority_review"}:
            actions.append(review.get("coach_action") or "Review equipment/comfort flags.")

    return actions[:6]


def build_daily_brief(
    *,
    athlete_id: str,
    twin_state: Optional[Dict[str, Any]] = None,
    load_state: Optional[Dict[str, Any]] = None,
    readiness_state: Optional[Dict[str, Any]] = None,
    checkin: Optional[Dict[str, Any]] = None,
    recent_checkins: Optional[Sequence[Dict[str, Any]]] = None,
    last_compliance: Optional[Dict[str, Any]] = None,
    upcoming_key_session: bool = False,
    constraints: Optional[Dict[str, Any]] = None,
    equipment_state: Optional[Dict[str, Any]] = None,
    comfort_notes: Optional[Sequence[str]] = None,
    female_athlete_context: Optional[Dict[str, Any]] = None,
    metabolic_snapshot: Optional[Dict[str, Any]] = None,
    include_communication_draft: bool = True,
) -> Dict[str, Any]:
    """Unified coach daily brief — triage, context and recommended actions."""
    twin = twin_state or {}
    athlete = athlete_id or twin.get("athlete_id") or "unknown"

    attention = evaluate_athlete_attention(
        athlete_id=athlete,
        twin_state=twin,
        load_state=load_state,
        readiness_state=readiness_state,
        checkin=checkin,
        last_compliance=last_compliance,
        upcoming_key_session=upcoming_key_session,
        recent_checkins=recent_checkins,
    )

    pnei = build_pnei_context(
        athlete_id=athlete,
        twin_state=twin,
        load_state=load_state or twin.get("load_state"),
        readiness_state=readiness_state or twin.get("readiness_state"),
        checkin=checkin,
        recent_checkins=recent_checkins,
    )
    endocrine = build_endocrine_context(
        athlete_id=athlete,
        twin_state=twin,
        checkin=checkin,
        female_athlete_context=female_athlete_context,
    )
    training_safety = evaluate_training_safety(
        athlete_id=athlete,
        twin_state=twin,
        checkin=checkin,
        recent_checkins=recent_checkins,
        load_state=load_state,
        readiness_state=readiness_state,
    )
    safety = evaluate_decision_safety(
        athlete_id=athlete,
        twin_state=twin,
        load_state=load_state,
        readiness_state=readiness_state,
        last_compliance=last_compliance,
        checkin=checkin,
        recent_checkins=recent_checkins,
        upcoming_key_session=upcoming_key_session,
        pnei_context=pnei,
        endocrine_context=endocrine,
        training_safety=training_safety,
    )

    adherence = None
    compliance = last_compliance
    if compliance is None and isinstance(twin.get("last_compliance_results"), list) and twin["last_compliance_results"]:
        compliance = twin["last_compliance_results"][0]
    if compliance:
        adherence = evaluate_adherence(
            athlete_id=athlete,
            performed_compliance=compliance,
            readiness_state=readiness_state,
            checkin=checkin,
        )

    testing = build_testing_plan(
        athlete_id=athlete,
        metabolic_snapshot=metabolic_snapshot or twin.get("metabolic_snapshot"),
        twin_state=twin,
    )

    constraint_adapt = None
    if constraints or twin.get("constraints_state"):
        constraint_adapt = evaluate_constraints(
            athlete_id=athlete,
            constraints=constraints or (twin.get("constraints_state") or {}).get("reported"),
        )

    equipment = evaluate_equipment_comfort(
        athlete_id=athlete,
        equipment_state=equipment_state,
        comfort_notes=comfort_notes,
        checkin=checkin,
        twin_state=twin,
    )

    female_ctx = build_female_athlete_context(
        athlete_id=athlete,
        context=female_athlete_context,
        checkin=checkin,
        twin_state=twin,
    )

    draft = None
    if include_communication_draft:
        draft = build_communication_draft(
            athlete_id=athlete,
            athlete_profile=twin.get("athlete_profile"),
            decision_safety=safety,
            attention=attention,
            adherence_report=adherence,
            checkin=checkin,
        )

    priority_actions = _priority_actions(
        attention=attention,
        decision_safety=safety,
        pnei=pnei,
        adherence=adherence,
        testing=testing,
        equipment=equipment,
    )

    attn = attention.get("athlete_attention") or {}
    safety_gate = (safety.get("decision_safety") or {}).get("intensity_gate", "ok_to_auto_suggest")

    payload = {
        "status": "success",
        "schema_version": SCHEMA_DAILY,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete,
        "coach_daily_brief": {
            "attention_priority": attn.get("priority"),
            "attention_reasons": attn.get("reasons"),
            "intensity_gate": safety_gate,
            "priority_actions": priority_actions,
            "modules": {
                "attention": attention,
                "decision_safety": safety,
                "pnei_context": pnei,
                "endocrine_context": endocrine,
                "training_safety": training_safety,
                "adherence": adherence,
                "testing_plan": testing,
                "constraints": constraint_adapt,
                "equipment_comfort": equipment,
                "female_athlete_context": female_ctx,
                "communication_draft": draft,
            },
            "coach_review_required": safety_gate != "ok_to_auto_suggest" or attn.get("priority") == "high",
            "not_autonomous": True,
        },
        "limitations": [
            "Daily brief aggregates signals — coach validates before acting.",
            "Not medical diagnosis or autonomous coaching.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="coach_orchestrator",
        method="daily_brief",
        confidence=0.68 if priority_actions else 0.5,
    )


def build_session_decision(
    *,
    athlete_id: str,
    planned_session: Dict[str, Any],
    twin_state: Optional[Dict[str, Any]] = None,
    load_state: Optional[Dict[str, Any]] = None,
    readiness_state: Optional[Dict[str, Any]] = None,
    checkin: Optional[Dict[str, Any]] = None,
    recent_checkins: Optional[Sequence[Dict[str, Any]]] = None,
    environment_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compare planned session against physiology and PNEI/endocrine/safety context."""
    twin = twin_state or {}
    brief = build_daily_brief(
        athlete_id=athlete_id,
        twin_state=twin,
        load_state=load_state,
        readiness_state=readiness_state,
        checkin=checkin,
        recent_checkins=recent_checkins,
        include_communication_draft=False,
    )
    modules = (brief.get("coach_daily_brief") or {}).get("modules") or {}

    pnei_status = ((modules.get("pnei_context") or {}).get("pnei_context") or {}).get("status", "ok")
    endo_status = ((modules.get("endocrine_context") or {}).get("endocrine_context") or {}).get("status", "ok")
    safety_level = ((modules.get("decision_safety") or {}).get("decision_safety") or {}).get("level")
    training_status = ((modules.get("training_safety") or {}).get("training_safety") or {}).get("status", "ok")

    physiology_capable = True
    snapshot = twin.get("metabolic_snapshot") or {}
    if not snapshot.get("mlss_power_watts") and not snapshot.get("mlss_power_w"):
        physiology_capable = False

    final = "proceed"
    reason = "Context supports planned session."
    replacement = None

    if training_status == "stop" or safety_level == "professional_review_recommended":
        final = "hold"
        reason = "Training safety or professional review required."
        replacement = _downgrade_session(planned_session, reason)
    elif pnei_status in {"human_review", "professional_review"} or endo_status == "professional_review":
        final = "downgrade"
        reason = "High systemic strain despite metabolic profile — modify session."
        replacement = _downgrade_session(
            planned_session,
            "PNEI/endocrine context unfavorable for planned intensity.",
        )
    elif pnei_status == "caution" or endo_status == "caution" or safety_level == "coach_review_recommended":
        intensity = _session_intensity(planned_session)
        if intensity in {"high", "moderate_high"}:
            final = "downgrade"
            reason = "Moderate systemic strain — reduce session density."
            replacement = _downgrade_session(planned_session, reason)

    if environment_context and environment_context.get("temperature_c", 20) >= 32:
        if final == "proceed" and _session_intensity(planned_session) in {"high", "moderate_high"}:
            final = "modify"
            reason = "Heat stress — cap intensity even if physiology supports load."

    payload = {
        "status": "success",
        "schema_version": SCHEMA_SESSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete_id,
        "session_decision": {
            "planned_session": planned_session,
            "physiology_status": "capable" if physiology_capable else "unknown",
            "pnei_status": pnei_status,
            "endocrine_status": endo_status,
            "final_recommendation": final,
            "replacement": replacement,
            "reason": reason,
            "intensity_gate": (modules.get("decision_safety") or {}).get("decision_safety", {}).get("intensity_gate"),
            "coach_review_required": final in {"hold", "downgrade", "modify"},
        },
        "limitations": [
            "Session decision is advisory — coach confirms with athlete before changing plan.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="coach_orchestrator",
        method="session_decision",
        confidence=0.65 if physiology_capable else 0.45,
    )
