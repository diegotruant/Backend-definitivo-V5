"""Adaptive load orchestrator.

This layer consumes the existing FIT stream and workout_summary output, then
combines external load, internal/cardiac response, RR-derived autonomic strain,
thermal strain, longitudinal trend, and morning readiness into one report.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from engines.adaptive_load.models import AthleteLoadProfile, DailyStatus
from engines.adaptive_load.readiness import calculate_readiness
from engines.adaptive_load.recommendation import generate_recommendation
from engines.adaptive_load.scoring import (
    calculate_external_load,
    calculate_internal_load,
    calculate_rr_metrics,
    calculate_session_load,
    calculate_thermal_load,
    extract_cardiac_metrics,
    extract_power_metrics,
)
from engines.adaptive_load.trend import calculate_load_trend
from engines.core.metric_contracts import annotate_payload, summarize_section_contracts
from engines.recovery.thermal_engine import analyze_thermal_session


def build_adaptive_load_report(
    *,
    stream: Any,
    workout_summary: Dict[str, Any],
    athlete_profile: AthleteLoadProfile,
    daily_status: Optional[DailyStatus] = None,
    history: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the adaptive load report for one activity plus optional context."""
    power_metrics = extract_power_metrics(workout_summary)
    cardiac_metrics = extract_cardiac_metrics(workout_summary)
    external_load = calculate_external_load(power_metrics)
    internal_load = calculate_internal_load(cardiac_metrics)
    rr_metrics = calculate_rr_metrics(stream)

    thermal_report = analyze_thermal_session(
        core_temp_stream=_as_list(getattr(stream, "core_body_temp", [])),
        power_stream=_as_list(getattr(stream, "power", [])),
        hr_stream=_as_list(getattr(stream, "heart_rate", [])),
        skin_temp_stream=_as_list(getattr(stream, "skin_temp", [])),
        ambient_temp_stream=_as_list(getattr(stream, "ambient_temp", [])),
        ftp=athlete_profile.ftp,
    ).to_dict()
    thermal_load = calculate_thermal_load(thermal_report)

    session_load = calculate_session_load(
        external_load=external_load,
        internal_load=internal_load,
        rr_metrics=rr_metrics,
        thermal_load=thermal_load,
    )
    trend = calculate_load_trend(history, session_load.get("score"))
    readiness = calculate_readiness(daily_status)
    recommendation = generate_recommendation(
        session_load=session_load,
        trend=trend,
        readiness=readiness,
    )

    sections = {
        "session_load": session_load,
        "trend": trend,
        "readiness": readiness,
        "recommendation": recommendation,
    }
    headline = {
        "session_load_score": session_load.get("score"),
        "readiness_score": readiness.get("score"),
        "recommendation": recommendation.get("status"),
        "load_ratio": trend.get("load_ratio"),
        "tsb": trend.get("tsb"),
        "thermal_load_score": thermal_load.get("score"),
        "autonomic_strain_score": rr_metrics.get("autonomic_strain_score"),
    }

    payload: Dict[str, Any] = {
        "status": "success" if session_load.get("score") is not None else "partial",
        "schema_version": "adaptive_load.v1",
        "stream_metadata": workout_summary.get("stream_metadata", {}),
        "athlete_profile": {
            "weight_kg": athlete_profile.weight_kg,
            "ftp": athlete_profile.ftp,
            "hr_max": athlete_profile.hr_max,
            "hr_rest": athlete_profile.hr_rest,
            "lthr": athlete_profile.lthr,
        },
        "sections": sections,
        "headline": headline,
        "section_contracts": summarize_section_contracts(sections),
        "warnings": _build_warnings(session_load, trend, readiness),
    }
    return annotate_payload(
        payload,
        module_name="adaptive_load_engine",
        method="deterministic_load_readiness_recommendation",
        confidence=0.55,
        limitations=[
            "Score cutoffs are deterministic heuristics and should be individually calibrated.",
            "During-session RR-derived HRV is an acute strain marker, not a replacement for morning HRV.",
            "Thermal strain requires true body-temperature data; ambient temperature is not core temperature.",
        ],
    )


def _as_list(values: Any) -> list[Any]:
    if values is None:
        return []
    if hasattr(values, "tolist"):
        return values.tolist()
    return list(values)


def _build_warnings(
    session_load: Dict[str, Any],
    trend: Dict[str, Any],
    readiness: Dict[str, Any],
) -> list[str]:
    warnings = []
    if not (session_load.get("autonomic_load") or {}).get("available"):
        warnings.append("RR intervals not available or insufficient: autonomic strain omitted.")
    if not (session_load.get("thermal_load") or {}).get("available"):
        warnings.append("Core body temperature not available: thermal load omitted.")
    if trend.get("status") == "insufficient_data":
        warnings.append("Historical load is insufficient for robust ATL/CTL/TSB trend.")
    if not readiness.get("available"):
        warnings.append("Daily readiness not provided or insufficient: recommendation uses session/trend only.")
    return warnings
