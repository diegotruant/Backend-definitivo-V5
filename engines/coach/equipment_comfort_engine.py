"""Equipment and comfort tracking — position, materials, pain-performance links."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from engines.core.metric_contracts import annotate_payload

SCHEMA_VERSION = "equipment_comfort_review.v1"
PRESCRIPTION_MODEL = "PRESCRIPTION_MODEL"

COMFORT_FLAGS = {
    "saddle": ["saddle", "sella", "perineal", "groin"],
    "back": ["back", "lombare", "lower_back", "lumbar"],
    "hands": ["hand", "mani", "numbness", "formicolio", "wrist"],
    "feet": ["foot", "feet", "piedi", "shoe", "scarpe"],
    "knee": ["knee", "ginocchio"],
}


def _match_flag(text: str) -> Optional[str]:
    lower = text.lower()
    for flag, keywords in COMFORT_FLAGS.items():
        if any(k in lower for k in keywords):
            return flag
    return None


def _extract_notes(notes: Any) -> List[str]:
    if not notes:
        return []
    if isinstance(notes, str):
        return [notes]
    if isinstance(notes, list):
        return [str(n) for n in notes if n]
    return []


def evaluate_equipment_comfort(
    *,
    athlete_id: Optional[str] = None,
    equipment_state: Optional[Dict[str, Any]] = None,
    comfort_notes: Optional[Sequence[str]] = None,
    position_change_log: Optional[Sequence[Dict[str, Any]]] = None,
    session_history: Optional[Sequence[Dict[str, Any]]] = None,
    checkin: Optional[Dict[str, Any]] = None,
    twin_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Correlate comfort flags with performance patterns — coach review, not bike fit prescription."""
    twin = twin_state or {}
    equipment = dict(equipment_state or twin.get("equipment_state") or {})
    notes = list(comfort_notes or equipment.get("comfort_notes") or [])
    if checkin and checkin.get("notes"):
        notes.extend(_extract_notes(checkin.get("notes")))
    for flag in (checkin or {}).get("pain_flags") or []:
        notes.append(str(flag))

    comfort_flags: List[str] = []
    for note in notes:
        matched = _match_flag(note)
        if matched:
            comfort_flags.append(matched)

    recent_position_changes = [
        row for row in (position_change_log or equipment.get("position_change_log") or [])
        if isinstance(row, dict)
    ]
    if recent_position_changes:
        comfort_flags.append("recent_position_change")

    power_drop_after_90 = False
    back_pain_repeated = "back" in comfort_flags
    for session in session_history or []:
        if not isinstance(session, dict):
            continue
        duration = session.get("duration_min") or session.get("elapsed_min")
        decay = session.get("power_decay_pct") or session.get("power_drop_pct")
        try:
            if duration and float(duration) >= 90 and decay and float(decay) >= 8:
                power_drop_after_90 = True
        except (TypeError, ValueError):
            pass

    links: List[Dict[str, Any]] = []
    if power_drop_after_90 and back_pain_repeated:
        links.append({
            "flag": "possible_position_issue",
            "reason": "Power drops after 90 min with repeated back pain notes.",
            "coach_action": "Review bike fit or endurance position.",
        })
    if "saddle" in comfort_flags:
        links.append({
            "flag": "saddle_comfort_risk",
            "reason": "Saddle/perineal discomfort reported — may affect sustained power.",
            "coach_action": "Review saddle height, reach and pressure distribution.",
        })
    if "hands" in comfort_flags:
        links.append({
            "flag": "hand_numbness_risk",
            "reason": "Hand/wrist discomfort may limit long sessions.",
            "coach_action": "Check cockpit setup and hand position on long rides.",
        })
    if recent_position_changes and power_drop_after_90:
        links.append({
            "flag": "position_change_adaptation",
            "reason": "Recent position change with durability drop.",
            "coach_action": "Allow adaptation period before increasing load.",
        })

    status = "ok"
    if links:
        status = "review_recommended"
    if len(comfort_flags) >= 3:
        status = "high_priority_review"

    payload = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "measurement_tier": PRESCRIPTION_MODEL,
        "athlete_id": athlete_id,
        "equipment_comfort_review": {
            "status": status,
            "comfort_flags": sorted(set(comfort_flags)),
            "comfort_performance_links": links,
            "equipment_reported": {
                "saddle_model": equipment.get("saddle_model"),
                "bike_type": equipment.get("bike_type"),
                "recent_position_changes": len(recent_position_changes),
            },
            "coach_action": (
                links[0]["coach_action"] if links else "No equipment comfort flags — routine monitoring."
            ),
        },
        "limitations": [
            "Comfort review supports coach workflow — not automated bike fit or medical advice.",
        ],
    }
    return annotate_payload(
        payload,
        module_name="equipment_comfort_engine",
        method="evaluate_equipment_comfort",
        confidence=0.55 if links else 0.4,
    )
