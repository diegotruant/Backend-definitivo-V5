"""Stateless TwinState update helpers."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from engines.readiness.readiness_engine import update_load_state

from .models import build_twin_state, validate_twin_state


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _append_event(state: Dict[str, Any], event: Dict[str, Any]) -> None:
    state.setdefault("event_log", [])
    state["event_log"].append({"at": _now_iso(), **event})
    # Keep the state blob bounded for client round-trips.
    state["event_log"] = state["event_log"][-200:]


def update_twin_state_from_ride(
    state_payload: Dict[str, Any],
    *,
    ride_summary: Optional[Dict[str, Any]] = None,
    ingest_result: Optional[Dict[str, Any]] = None,
    power_source_report: Optional[Dict[str, Any]] = None,
    ride_id: Optional[str] = None,
    metabolic_snapshot: Optional[Dict[str, Any]] = None,
    lactate_steps: Optional[Sequence[Dict[str, Any]]] = None,
    sync_metabolic_curves: bool = True,
) -> Dict[str, Any]:
    """Return a new TwinState with ride-derived sections updated."""
    state = build_twin_state(state_payload) if state_payload.get("schema_version") is None else validate_twin_state(state_payload)
    state = deepcopy(state)
    now = _now_iso()
    ride_summary = ride_summary or {}
    ingest_result = ingest_result or {}

    if ingest_result.get("curve"):
        state["rolling_power_curve"] = ingest_result["curve"]
    if power_source_report:
        state["power_source_state"] = power_source_report

    if ride_summary:
        headline = ride_summary.get("headline") or ride_summary.get("summary") or {}
        sections = ride_summary.get("sections") or {}
        sensor_quality = state.get("sensor_quality") or {}
        if sections.get("cardiac"):
            sensor_quality["last_cardiac"] = sections["cardiac"]
        if sections.get("hrv"):
            sensor_quality["last_hrv"] = sections["hrv"]
        if sections.get("power"):
            sensor_quality["last_power"] = sections["power"]
        if headline:
            sensor_quality["last_headline"] = headline
            session_load = headline.get("training_load") or headline.get("tss") or headline.get("session_load")
            try:
                load_value = float(session_load) if session_load is not None else 0.0
            except (TypeError, ValueError):
                load_value = 0.0
            if load_value > 0:
                state["load_state"] = update_load_state(state.get("load_state"), load_value)
        if ride_summary.get("physiological_resilience"):
            state["physiological_resilience"] = ride_summary["physiological_resilience"]
        state["sensor_quality"] = sensor_quality
        if ride_summary.get("warnings"):
            state.setdefault("warnings", []).extend(ride_summary.get("warnings") or [])
            state["warnings"] = state["warnings"][-100:]

    profile_refresh = bool(ingest_result.get("profile_should_refresh"))
    active_metabolic_profile = ingest_result.get("active_metabolic_profile")
    if active_metabolic_profile:
        from .metabolic_curves_sync import sync_twin_from_versioned_profile

        state = sync_twin_from_versioned_profile(state, active_metabolic_profile, force=True)
        profile_refresh = True
    elif metabolic_snapshot is not None:
        from .metabolic_curves_sync import sync_lactate_state_from_steps, sync_twin_after_profile_refresh

        if lactate_steps:
            state = sync_twin_after_profile_refresh(state, metabolic_snapshot, lactate_steps=lactate_steps)
        else:
            state = sync_twin_after_profile_refresh(state, metabolic_snapshot)
    elif lactate_steps and sync_metabolic_curves:
        from .metabolic_curves_sync import sync_lactate_state_from_steps

        state = sync_lactate_state_from_steps(state, lactate_steps)

    state["updated_at"] = now
    _append_event(state, {
        "type": "ride_ingested",
        "ride_id": ride_id,
        "has_summary": bool(ride_summary),
        "curve_updated": bool(ingest_result.get("curve")),
        "profile_refreshed": profile_refresh and (
            active_metabolic_profile is not None or metabolic_snapshot is not None
        ),
        "metabolic_curves_synced": sync_metabolic_curves and (
            active_metabolic_profile is not None or metabolic_snapshot is not None
        ),
        "athlete_model_source": (
            "athlete_metabolic_profile_versions" if active_metabolic_profile else None
        ),
    })
    return validate_twin_state(state)


def update_twin_state_from_workout_result(
    state_payload: Dict[str, Any],
    *,
    compliance_result: Dict[str, Any],
    assignment_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a workout compliance result and update state timestamp."""
    state = build_twin_state(state_payload) if state_payload.get("schema_version") is None else validate_twin_state(state_payload)
    state = deepcopy(state)
    now = _now_iso()
    entry = {"assignment_id": assignment_id, "result": compliance_result, "recorded_at": now}
    state.setdefault("last_compliance_results", [])
    state["last_compliance_results"].append(entry)
    state["last_compliance_results"] = state["last_compliance_results"][-50:]
    state["updated_at"] = now
    _append_event(state, {
        "type": "workout_compliance_recorded",
        "assignment_id": assignment_id,
        "classification": compliance_result.get("classification"),
        "compliance_score": compliance_result.get("compliance_score"),
    })
    return validate_twin_state(state)
