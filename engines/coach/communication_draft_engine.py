"""Coach communication drafts — supportive messages for human review, not auto-send."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload

SCHEMA_VERSION = "communication_draft.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"


def _pick_name(athlete_profile: Optional[Dict[str, Any]], athlete_id: Optional[str]) -> str:
    if athlete_profile:
        for key in ("first_name", "name", "display_name"):
            if athlete_profile.get(key):
                return str(athlete_profile[key]).split()[0]
    return athlete_id or "athlete"


def _highlights(
    *,
    decision_safety: Dict[str, Any],
    attention: Dict[str, Any],
    adherence: Dict[str, Any],
    checkin: Optional[Dict[str, Any]],
) -> List[str]:
    points: List[str] = []
    level = decision_safety.get("level") or decision_safety.get("safety", {}).get("level")
    if level and level != "ok_to_auto_suggest":
        points.append(f"Safety gate: {level.replace('_', ' ')}.")

    priority = attention.get("attention_priority") or attention.get("priority")
    if priority in {"high", "medium"}:
        reasons = attention.get("reasons") or attention.get("attention_reasons") or []
        reason_txt = ", ".join(reasons[:2]) if reasons else "elevated attention score"
        points.append(f"Attention {priority}: {reason_txt}.")

    compliance = adherence.get("compliance") if isinstance(adherence.get("compliance"), dict) else adherence
    score = compliance.get("score") if isinstance(compliance, dict) else None
    if score is not None and float(score) < 70:
        note = compliance.get("coach_note") if isinstance(compliance, dict) else None
        points.append(note or f"Adherence at {score}% — review target realism.")

    if checkin:
        fatigue = checkin.get("perceived_fatigue")
        motivation = checkin.get("motivation")
        if fatigue is not None and float(fatigue) >= 8:
            points.append("Subjective fatigue is high.")
        if motivation is not None and float(motivation) <= 4:
            points.append("Motivation is low — explore barriers without judgment.")

    psych = decision_safety.get("psychological_support_flag") or {}
    if psych.get("human_check_recommended"):
        points.append("Subjective signals suggest a supportive check-in (not a diagnosis).")

    return points[:5]


def _draft_body(name: str, highlights: List[str], tone: str) -> str:
    greeting = f"Hi {name}," if tone != "brief" else f"{name} —"
    if not highlights:
        opener = "Quick check-in before the next block."
        body = f"{greeting}\n\n{opener} How are you feeling about the plan and recovery this week?"
        if tone == "direct":
            body += "\n\nReply with sleep, legs and any constraints for the next 48 h."
        return body

    if tone == "supportive":
        opener = "I reviewed your recent training signals and wanted to connect before we adjust anything."
    elif tone == "direct":
        opener = "Flags from your recent data:"
    else:
        opener = "Training review:"

    bullets = "\n".join(f"• {h}" for h in highlights)
    closing = (
        "No need to change everything at once — let me know how this matches what you're feeling."
        if tone == "supportive"
        else "Send a short update so we can calibrate the next sessions."
        if tone == "direct"
        else "Reply when you can."
    )
    return f"{greeting}\n\n{opener}\n\n{bullets}\n\n{closing}"


def build_communication_draft(
    *,
    athlete_id: Optional[str] = None,
    athlete_profile: Optional[Dict[str, Any]] = None,
    twin_state: Optional[Dict[str, Any]] = None,
    decision_safety: Optional[Dict[str, Any]] = None,
    attention: Optional[Dict[str, Any]] = None,
    adherence_report: Optional[Dict[str, Any]] = None,
    checkin: Optional[Dict[str, Any]] = None,
    tone: str = "supportive",
    channel: str = "message",
) -> Dict[str, Any]:
    """Draft coach-facing message text from safety, attention and adherence signals."""
    twin = twin_state or {}
    profile = athlete_profile or twin.get("athlete_profile") or {}
    safety = decision_safety or twin.get("decision_safety_state") or {}
    attn = attention or twin.get("coach_attention_state") or {}
    adherence = adherence_report or (twin.get("adherence_state") or {}).get("latest_report") or {}
    checkin_data = checkin or twin.get("checkin_state") or {}

    name = _pick_name(profile, athlete_id)
    tone_norm = str(tone or "supportive").strip().lower()
    if tone_norm not in {"supportive", "direct", "brief"}:
        tone_norm = "supportive"

    highlights = _highlights(
        decision_safety=safety,
        attention=attn,
        adherence=adherence,
        checkin=checkin_data if isinstance(checkin_data, dict) else None,
    )
    subject = "Quick training check-in" if highlights else "How is the block going?"
    if any("Safety" in h or "Attention high" in h for h in highlights):
        subject = "Let's align before the next key session"

    body = _draft_body(name, highlights, tone_norm)

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete_id,
        "communication_draft": {
            "subject": subject,
            "body": body,
            "channel": channel,
            "tone": tone_norm,
            "highlights": highlights,
            "coach_review_required": True,
            "not_autonomous": True,
            "not_a_diagnosis": True,
        },
        "limitations": [
            "Draft is generated for coach editing — do not auto-send without human review.",
            "Psychological flags recommend conversation, not clinical assessment.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="communication_draft_engine",
        method="coach_communication_draft",
        confidence=0.6 if highlights else 0.45,
    )
