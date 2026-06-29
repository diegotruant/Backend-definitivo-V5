"""Daily readiness and load-risk scoring.

Scores are model estimates, not medical diagnostics. Inputs are deliberately
plain JSON so the API remains stateless and database-agnostic.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from engines.core.metric_contracts import annotate_payload
from engines.core.model_safety import finalize_model_metadata

EWMA_CHRONIC_TRUST_DAYS = 42
EWMA_ACUTE_TRUST_DAYS = 14


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_iso_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _ewma_trust_metadata(
    state: Dict[str, Any],
    *,
    reference_date: Optional[date] = None,
) -> Dict[str, Any]:
    """Compute EWMA warm-up metadata for coach-facing trust boundaries."""
    today = reference_date or date.today()
    started = _parse_iso_date(state.get("ewma_tracking_started_at"))
    sessions = int(state.get("load_sessions_count") or 0)
    chronic = _num(state.get("chronic_load"), 0.0)

    if started is None and sessions <= 0 and chronic <= 0.0:
        return {
            "ewma_tracking_started_at": None,
            "load_sessions_count": 0,
            "confidence_valid_from_date": None,
            "acute_trust_from_date": None,
            "ewma_warmup_complete": False,
            "ewma_trust_level": "cold",
            "ewma_warmup_weeks_remaining": EWMA_CHRONIC_TRUST_DAYS // 7,
        }

    if started is None:
        started = today

    acute_from = started + timedelta(days=EWMA_ACUTE_TRUST_DAYS)
    chronic_from = started + timedelta(days=EWMA_CHRONIC_TRUST_DAYS)
    days_elapsed = max(0, (today - started).days)

    if days_elapsed >= EWMA_CHRONIC_TRUST_DAYS and sessions >= 8:
        trust_level = "stable"
        weeks_remaining = 0
    elif days_elapsed >= EWMA_ACUTE_TRUST_DAYS or sessions >= 4:
        trust_level = "warming"
        weeks_remaining = max(0, (EWMA_CHRONIC_TRUST_DAYS - days_elapsed + 6) // 7)
    else:
        trust_level = "cold"
        weeks_remaining = max(1, (EWMA_CHRONIC_TRUST_DAYS - days_elapsed + 6) // 7)

    return {
        "ewma_tracking_started_at": started.isoformat(),
        "load_sessions_count": sessions,
        "confidence_valid_from_date": chronic_from.isoformat(),
        "acute_trust_from_date": acute_from.isoformat(),
        "ewma_warmup_complete": trust_level == "stable",
        "ewma_trust_level": trust_level,
        "ewma_warmup_weeks_remaining": weeks_remaining,
    }


def update_load_state(previous_state: Optional[Dict[str, Any]], session_load: float) -> Dict[str, Any]:
    """Update acute/chronic load using simple EWMA coefficients."""
    prev = previous_state or {}
    acute = _num(prev.get("acute_load"), 0.0)
    chronic = _num(prev.get("chronic_load"), 0.0)
    load = max(0.0, float(session_load or 0.0))
    alpha_acute = 1.0 - pow(2.718281828, -1.0 / 7.0)
    alpha_chronic = 1.0 - pow(2.718281828, -1.0 / 42.0)
    new_acute = acute + alpha_acute * (load - acute)
    new_chronic = chronic + alpha_chronic * (load - chronic)
    balance = new_chronic - new_acute

    sessions = int(prev.get("load_sessions_count") or 0)
    if load > 0:
        sessions += 1
    started_at = prev.get("ewma_tracking_started_at")
    if load > 0 and not started_at:
        started_at = date.today().isoformat()

    state = {
        "status": "success",
        "acute_load": round(new_acute, 1),
        "chronic_load": round(new_chronic, 1),
        "load_balance": round(balance, 1),
        "session_load": round(load, 1),
        "load_sessions_count": sessions,
        "ewma_tracking_started_at": started_at,
    }
    trust = _ewma_trust_metadata(state)
    state.update(trust)
    return state


def compute_load_risk(load_state: Dict[str, Any], *, planned_load: float = 0.0) -> Dict[str, Any]:
    acute = _num(load_state.get("acute_load"), 0.0) + max(0.0, float(planned_load or 0.0)) * 0.2
    chronic = max(1.0, _num(load_state.get("chronic_load"), 0.0))
    ratio = acute / chronic
    if ratio >= 1.5:
        risk = "high"
    elif ratio >= 1.25:
        risk = "moderate"
    elif ratio <= 0.55 and chronic > 20:
        risk = "detraining"
    else:
        risk = "low"
    assumptions: list[str] = []
    missing_inputs: list[str] = []
    quality_flags: list[str] = []
    if _num(load_state.get("acute_load"), 0.0) <= 0.0:
        missing_inputs.append("acute_load")
    if _num(load_state.get("chronic_load"), 0.0) <= 0.0:
        missing_inputs.append("chronic_load")

    trust = _ewma_trust_metadata(load_state)
    if trust["ewma_trust_level"] != "stable":
        quality_flags.append("ewma_cold_start")
        if trust["ewma_trust_level"] == "cold":
            quality_flags.append("cold_start_low_chronic_load")
        assumptions.append("load_risk_less_reliable_until_confidence_valid_from_date")

    if chronic <= 5.0:
        quality_flags.append("cold_start_low_chronic_load")
        assumptions.append("risk_estimate_based_on_limited_load_history")

    return {
        "status": "success",
        "risk": risk,
        "acute_chronic_ratio": round(ratio, 2),
        "planned_load": round(planned_load, 1),
        "confidence_valid_from_date": trust["confidence_valid_from_date"],
        "ewma_trust_level": trust["ewma_trust_level"],
        "ewma_warmup_complete": trust["ewma_warmup_complete"],
        "model_metadata": finalize_model_metadata(
            assumptions=assumptions,
            missing_inputs=missing_inputs,
            quality_flags=quality_flags,
            confidence=0.8 if trust["ewma_warmup_complete"] else 0.55 if trust["ewma_trust_level"] == "warming" else 0.35,
        ),
    }


def compute_readiness_today(
    *,
    load_state: Optional[Dict[str, Any]] = None,
    hrv_status: Optional[Dict[str, Any]] = None,
    sleep_status: Optional[Dict[str, Any]] = None,
    subjective: Optional[Dict[str, Any]] = None,
    recent_warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Combine available recovery/load signals into a 0-100 readiness score."""
    load = load_state or {}
    hrv = hrv_status or {}
    sleep = sleep_status or {}
    subj = subjective or {}
    warnings = list(recent_warnings or [])

    acute = _num(load.get("acute_load"), 0.0)
    chronic = max(1.0, _num(load.get("chronic_load"), 1.0))
    balance = _num(load.get("load_balance"), chronic - acute)
    load_component = _clamp(0.55 + (balance / max(chronic, 1.0)) * 0.5)

    assumptions: list[str] = []
    missing_inputs: list[str] = []
    quality_flags: list[str] = []
    hrv_component = _clamp(_num(hrv.get("score"), 0.65)) if hrv else 0.65
    sleep_component = _clamp(_num(sleep.get("score"), 0.65)) if sleep else 0.65
    subjective_component = _clamp(_num(subj.get("score"), 0.7)) if subj else 0.7
    if not hrv:
        assumptions.append("hrv_component_defaulted_to_0_65")
        missing_inputs.append("hrv_status")
    if not sleep:
        assumptions.append("sleep_component_defaulted_to_0_65")
        missing_inputs.append("sleep_status")
    if not subj:
        assumptions.append("subjective_component_defaulted_to_0_7")
        missing_inputs.append("subjective_status")
    if not load:
        assumptions.append("load_component_derived_without_historical_state")
        missing_inputs.append("load_state")

    trust = _ewma_trust_metadata(load)
    if trust["ewma_trust_level"] != "stable":
        quality_flags.append("ewma_cold_start")
        assumptions.append("readiness_load_component_less_reliable_during_ewma_warmup")

    score = (
        load_component * 0.42
        + hrv_component * 0.22
        + sleep_component * 0.18
        + subjective_component * 0.18
    )
    risk = compute_load_risk(load).get("risk", "low") if load else "unknown"
    if risk == "high":
        score *= 0.72
        warnings.append("high_load_risk")
    elif risk == "moderate":
        score *= 0.86
        warnings.append("moderate_load_risk")

    if trust["ewma_trust_level"] == "cold":
        warnings.append("ewma_cold_start")

    readiness_score = int(round(_clamp(score) * 100))
    recommendation = "train_as_planned"
    if readiness_score < 45:
        recommendation = "recovery_or_rest"
    elif readiness_score < 65:
        recommendation = "reduce_intensity"
    elif readiness_score > 85:
        recommendation = "ready_for_quality"

    base_confidence = 0.78 if load else 0.58
    if trust["ewma_trust_level"] == "cold":
        base_confidence = min(base_confidence, 0.45)
    elif trust["ewma_trust_level"] == "warming":
        base_confidence = min(base_confidence, 0.62)

    model_metadata = finalize_model_metadata(
        assumptions=assumptions,
        missing_inputs=missing_inputs,
        quality_flags=quality_flags,
        confidence=base_confidence,
    )
    payload = {
        "status": "success",
        "schema_version": "1.0.0",
        "readiness_score": readiness_score,
        "readiness_band": "low" if readiness_score < 45 else "moderate" if readiness_score < 75 else "high",
        "recommendation": recommendation,
        "confidence_valid_from_date": trust["confidence_valid_from_date"],
        "acute_trust_from_date": trust["acute_trust_from_date"],
        "ewma_trust_level": trust["ewma_trust_level"],
        "ewma_warmup_complete": trust["ewma_warmup_complete"],
        "ewma_warmup_weeks_remaining": trust["ewma_warmup_weeks_remaining"],
        "ewma_tracking_started_at": trust["ewma_tracking_started_at"],
        "load_sessions_count": trust["load_sessions_count"],
        "components": {
            "load": round(load_component, 3),
            "hrv": round(hrv_component, 3),
            "sleep": round(sleep_component, 3),
            "subjective": round(subjective_component, 3),
        },
        "load_risk": risk,
        "warnings": sorted(set(warnings)),
        "model_metadata": model_metadata,
    }
    return annotate_payload(
        payload,
        module_name="readiness_engine",
        method="daily_readiness",
        confidence=model_metadata["confidence_score"],
    )
