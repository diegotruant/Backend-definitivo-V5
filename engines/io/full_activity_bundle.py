from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from engines.core.athlete_context import AthleteContext
from engines.io.activity_charts import build_activity_charts
from engines.io.activity_intelligence import build_activity_intelligence
from engines.io.data_quality_report import build_data_quality_report
from engines.io.fit_parse_report import build_fit_parse_report
from engines.io.workout_summary import build_workout_summary
from engines.metabolic.metabolic_flexibility_engine import calculate_metabolic_flexibility_index
from engines.performance.durability_engine import (
    calculate_durability_index,
    calculate_np_drift,
    calculate_tte_sustainability,
    generate_durability_prescription,
    generate_hourly_decay_curve,
)
from engines.recovery.pedaling_balance import analyze_pedaling_balance


def _valid(values: Any, *, min_value: Optional[float] = None, max_value: Optional[float] = None) -> bool:
    if values is None:
        return False
    try:
        arr = np.asarray(values, dtype=float)
    except Exception:
        return False
    arr = arr[np.isfinite(arr)] if arr.size else arr
    if min_value is not None:
        arr = arr[arr >= min_value]
    if max_value is not None:
        arr = arr[arr <= max_value]
    return bool(arr.size)


def _has(stream: Any, signal: str, metabolic_snapshot: Optional[Dict[str, Any]]) -> bool:
    if signal == "power":
        return bool(getattr(stream, "has_power", False))
    if signal == "heart_rate":
        return bool(getattr(stream, "has_heart_rate", False))
    if signal == "rr":
        return bool(getattr(stream, "has_rr", False))
    if signal == "cadence":
        return _valid(getattr(stream, "cadence", None), min_value=1.0)
    if signal == "altitude":
        return _valid(getattr(stream, "altitude_m", None)) or _valid(getattr(stream, "altitude", None))
    if signal == "core_temperature":
        return bool(getattr(stream, "has_core_sensor", False)) and _valid(getattr(stream, "core_body_temp", None), min_value=30.0, max_value=45.0)
    if signal == "ambient_temperature":
        return _valid(getattr(stream, "ambient_temp", None), min_value=-40.0)
    if signal == "metabolic_snapshot":
        return bool(metabolic_snapshot and metabolic_snapshot.get("status") == "success")
    return False


def _path(payload: Dict[str, Any], dotted: str) -> Any:
    cur: Any = payload
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _status(value: Any) -> tuple[str, Optional[str]]:
    if value is None:
        return "skipped", "NO_OUTPUT"
    if isinstance(value, dict):
        if value.get("available") is False:
            return "skipped", str(value.get("reason") or "UNAVAILABLE")
        status = value.get("status")
        if status in {"error", "failed"}:
            return "error", str(value.get("reason") or value.get("error") or status)
        if status in {"skipped", "unavailable"}:
            return "skipped", str(value.get("reason") or status)
        if status == "partial":
            return "partial", str(value.get("reason") or "PARTIAL_OUTPUT")
        if status in {"success", "ok"}:
            return "success", None
        if status is not None:
            return "skipped", str(value.get("reason") or status)
        if value:
            return "success", None
        return "skipped", "EMPTY_OUTPUT"
    if isinstance(value, list) and not value:
        return "skipped", "EMPTY_OUTPUT"
    return "success", None


def _component(name: str, path: str, fn) -> tuple[Dict[str, Any], Dict[str, Any]]:
    try:
        value = fn()
        status, reason = _status(value)
    except Exception as exc:
        value = {"status": "error", "reason": str(exc)}
        status, reason = "error", str(exc)
    row = {"engine": name, "status": status, "output_path": path}
    if reason:
        row["reason"] = reason
    return value, row


def _entry(name: str, path: str, value: Any, required: tuple[str, ...], stream: Any, metabolic_snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    missing = [sig for sig in required if not _has(stream, sig, metabolic_snapshot)]
    if missing:
        return {"engine": name, "status": "skipped", "reason": "MISSING_REQUIRED_SIGNALS", "missing_signals": missing, "output_path": path}
    status, reason = _status(value)
    row = {"engine": name, "status": status, "output_path": path}
    if reason:
        row["reason"] = reason
    if required and status == "skipped" and reason in {"NO_OUTPUT", "EMPTY_OUTPUT"}:
        row["status"] = "partial"
        row["reason"] = "REQUIRED_SIGNAL_PRESENT_OUTPUT_NOT_EXPOSED"
        row["attention"] = "release_blocker"
    return row


def _zone_rows_from_candidate(candidate: Any) -> List[Dict[str, Any]]:
    """Extract zone rows from workout_summary zones section shapes."""
    if isinstance(candidate, list):
        return [row for row in candidate if isinstance(row, dict)]
    if not isinstance(candidate, dict):
        return []
    if candidate.get("available") is False:
        return []
    rows = candidate.get("zones") or candidate.get("time_in_zone") or candidate.get("distribution")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def _zones_for_charts(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    zones = ((summary.get("sections") or {}).get("zones") or {})
    if not isinstance(zones, dict):
        return []
    # Canonical keys from zones_engine.build_zones_section (workout_summary).
    # Legacy aliases kept for older snapshots and hand-built test payloads.
    for key in (
        "coggan_power",
        "metabolic_power",
        "coggan_power_zones",
        "power_zones",
        "metabolic_power_zones",
    ):
        rows = _zone_rows_from_candidate(zones.get(key))
        if rows:
            return rows
    return []


def _hrv_for_charts(summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    hrv = ((summary.get("sections") or {}).get("hrv") or {})
    return hrv if isinstance(hrv, dict) and hrv.get("available") is True else None


def _power_list(stream: Any) -> List[float]:
    n = int(getattr(stream, "n_samples", 0) or len(getattr(stream, "power", [])))
    return [float(p or 0.0) for p in getattr(stream, "power", [])[:n]]


def _metabolic_flexibility_from_snapshot(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    snapshot = snapshot or {}
    fatmax = snapshot.get("fatmax_power_watts") or snapshot.get("fatmax_watts") or snapshot.get("current_fatmax_watts")
    vt2 = snapshot.get("mlss_power_watts") or snapshot.get("vt2_watts") or snapshot.get("threshold_power_w")
    if fatmax is None or vt2 is None:
        return {"status": "partial", "reason": "MISSING_FATMAX_OR_VT2"}
    return calculate_metabolic_flexibility_index(float(fatmax), float(vt2))


def _pedaling_balance_from_stream(stream: Any, power_1hz: List[float]) -> Dict[str, Any]:
    n = int(getattr(stream, "n_samples", 0) or len(power_1hz))
    balance = [float(v) if v is not None and v == v else None for v in getattr(stream, "left_right_balance", [])[:n]]
    report = analyze_pedaling_balance(balance, power_1hz, pedaling_balance_source=getattr(stream, "pedaling_balance_source", "unknown"))
    return report.to_dict() if hasattr(report, "to_dict") else dict(report)


def _physiology_outputs(summary: Dict[str, Any], intelligence: Dict[str, Any]) -> Dict[str, Any]:
    sections = summary.get("sections") or {}
    out = {
        "status": "success",
        "hrv": sections.get("hrv"),
        "cardiac": sections.get("cardiac"),
        "cardiac_decoupling": intelligence.get("cardiac_decoupling"),
        "thermal": sections.get("thermal"),
        "thermal_context": intelligence.get("thermal_context"),
        "thermal_adjusted_durability": sections.get("thermal_adjusted_durability"),
        "mader_durability": sections.get("mader_durability"),
        "fatmax": sections.get("fatmax"),
        "metabolic_snapshot": sections.get("metabolic_snapshot"),
    }
    out["exposed_keys"] = [key for key, value in out.items() if key != "status" and _status(value)[0] == "success"]
    return out


EXPECTATIONS = (
    ("power", "workout_summary.sections.power", ("power",)),
    ("metabolic_snapshot", "workout_summary.sections.metabolic_snapshot", ("power",)),
    ("fatmax", "workout_summary.sections.fatmax", ("power",)),
    ("zones", "workout_summary.sections.zones", ()),
    ("classification", "workout_summary.sections.classification", ("power",)),
    ("hrv", "workout_summary.sections.hrv", ("rr",)),
    ("cardiac", "workout_summary.sections.cardiac", ("power", "heart_rate")),
    ("mader_durability", "workout_summary.sections.mader_durability", ("power", "metabolic_snapshot")),
    ("statistics", "workout_summary.sections.statistics", ()),
    ("physiological_resilience", "workout_summary.physiological_resilience", ()),
    ("thermal", "workout_summary.sections.thermal", ("core_temperature",)),
    ("thermal_adjusted_durability", "workout_summary.sections.thermal_adjusted_durability", ("power", "core_temperature")),
    ("best_efforts_power", "activity_intelligence.best_efforts_power", ("power",)),
    ("power_zones", "activity_intelligence.power_zones", ("power",)),
    ("heart_rate_zones", "activity_intelligence.heart_rate_zones", ("heart_rate",)),
    ("auto_intervals", "activity_intelligence.auto_intervals", ("power",)),
    ("cardiac_decoupling", "activity_intelligence.cardiac_decoupling", ("power", "heart_rate")),
    ("thermal_context", "activity_intelligence.thermal_context", ("core_temperature",)),
    ("data_quality", "activity_intelligence.data_quality", ()),
    ("chart_series", "activity_intelligence.chart_series", ()),
    ("physiology_outputs", "physiology_outputs", ()),
    ("physiology_hrv", "physiology_outputs.hrv", ("rr",)),
    ("physiology_cardiac", "physiology_outputs.cardiac", ("power", "heart_rate")),
    ("physiology_thermal", "physiology_outputs.thermal", ("core_temperature",)),
    ("physiology_thermal_context", "physiology_outputs.thermal_context", ("core_temperature",)),
    ("physiology_thermal_adjusted_durability", "physiology_outputs.thermal_adjusted_durability", ("power", "core_temperature")),
    ("chart_power", "activity_charts.power", ("power",)),
    ("chart_heart_rate", "activity_charts.heart_rate", ("heart_rate",)),
    ("chart_elevation", "activity_charts.elevation", ("altitude",)),
    ("chart_cadence", "activity_charts.cadence", ("cadence",)),
    ("chart_ambient_temp", "activity_charts.ambient_temp", ("ambient_temperature",)),
    ("chart_thermal", "activity_charts.thermal", ("core_temperature",)),
    # These derived charts require secondary analysis outputs in addition to raw signals,
    # so their absence must be visible but must not block the release bundle.
    ("chart_time_in_power_zone", "activity_charts.time_in_power_zone", ()),
    ("chart_time_in_intensity", "activity_charts.time_in_intensity", ()),
)


def build_full_activity_bundle(
    stream: Any,
    *,
    weight_kg: float,
    ftp: Optional[float] = None,
    lthr: Optional[float] = None,
    context: Optional[AthleteContext] = None,
    metabolic_snapshot: Optional[Dict[str, Any]] = None,
    hrv_step_seconds: Optional[float] = None,
    hrv_max_windows: int = 500,
    file_id: str = "activity.fit",
    file_hash: Optional[str] = None,
) -> Dict[str, Any]:
    ctx = context if context is not None else AthleteContext()
    manifest: List[Dict[str, Any]] = []
    parse_report, row = _component("parse_report", "parse_report", lambda: build_fit_parse_report(stream=stream, file_id=file_id, file_hash=file_hash))
    manifest.append(row)
    data_quality, row = _component("data_quality_report", "data_quality_report", lambda: build_data_quality_report(stream))
    manifest.append(row)
    summary, row = _component("workout_summary", "workout_summary", lambda: build_workout_summary(stream, weight_kg=weight_kg, ftp=ftp, lthr=lthr, context=ctx, metabolic_snapshot=metabolic_snapshot, hrv_step_seconds=hrv_step_seconds, hrv_max_windows=hrv_max_windows))
    manifest.append(row)
    effective_ftp = ftp or (summary.get("headline") or {}).get("ftp_w")
    try:
        effective_cp = (((summary.get("sections") or {}).get("power") or {}).get("critical_power") or {}).get("cp_w")
    except AttributeError:
        effective_cp = None
    intelligence, row = _component("activity_intelligence", "activity_intelligence", lambda: build_activity_intelligence(stream, weight_kg=weight_kg, ftp=effective_ftp, cp=effective_cp, lthr=lthr))
    manifest.append(row)
    charts, row = _component("activity_charts", "activity_charts", lambda: build_activity_charts(stream, zones=_zones_for_charts(summary), hrv_durability=_hrv_for_charts(summary)))
    manifest.append(row)

    power_1hz = _power_list(stream)

    durability_index_result, row = _component(
        "durability_index", "durability_index",
        lambda: calculate_durability_index(power_1hz, duration_seconds=len(power_1hz)),
    )
    manifest.append(row)

    durability_prescription_result, row = _component(
        "durability_prescription", "durability_prescription",
        lambda: (
            generate_durability_prescription(durability_index_result["durability_index"], durability_index_result["classification"])
            if isinstance(durability_index_result, dict) and "durability_index" in durability_index_result
            else {"status": "skipped", "reason": "durability_index_unavailable"}
        ),
    )
    manifest.append(row)

    np_drift_result, row = _component("np_drift", "np_drift", lambda: calculate_np_drift(power_1hz, len(power_1hz)))
    manifest.append(row)

    hourly_decay_result, row = _component(
        "hourly_decay_curve", "hourly_decay_curve",
        lambda: generate_hourly_decay_curve(power_1hz, len(power_1hz)),
    )
    manifest.append(row)

    tte_result, row = _component(
        "tte_sustainability", "tte_sustainability",
        lambda: calculate_tte_sustainability(power_1hz, effective_cp) if effective_cp else {"status": "skipped", "reason": "MISSING_CRITICAL_POWER"},
    )
    manifest.append(row)

    metabolic_flexibility_result, row = _component(
        "metabolic_flexibility", "metabolic_flexibility",
        lambda: _metabolic_flexibility_from_snapshot(metabolic_snapshot),
    )
    manifest.append(row)

    pedaling_balance_result, row = _component(
        "pedaling_balance", "pedaling_balance",
        lambda: _pedaling_balance_from_stream(stream, power_1hz),
    )
    manifest.append(row)

    physiology_outputs = _physiology_outputs(summary, intelligence)
    bundle = {
        "status": "success",
        "schema_version": "1.1.0",
        "parse_report": parse_report,
        "data_quality_report": data_quality,
        "workout_summary": summary,
        "activity_intelligence": intelligence,
        "activity_charts": charts,
        "physiology_outputs": physiology_outputs,
        "durability_index": durability_index_result,
        "durability_prescription": durability_prescription_result,
        "np_drift": np_drift_result,
        "hourly_decay_curve": hourly_decay_result,
        "tte_sustainability": tte_result,
        "metabolic_flexibility": metabolic_flexibility_result,
        "pedaling_balance": pedaling_balance_result,
    }
    for name, path, required in EXPECTATIONS:
        manifest.append(_entry(name, path, _path(bundle, path), required, stream, metabolic_snapshot))
    counts = {"success": 0, "skipped": 0, "partial": 0, "error": 0}
    blockers = 0
    for row in manifest:
        status = str(row.get("status") or "error")
        counts[status] = counts.get(status, 0) + 1
        if row.get("attention") == "release_blocker":
            blockers += 1
    bundle["engine_manifest"] = manifest
    bundle["manifest_summary"] = {"total_engines": len(manifest), "success": counts.get("success", 0), "skipped": counts.get("skipped", 0), "partial": counts.get("partial", 0), "error": counts.get("error", 0), "release_blockers": blockers, "physiology_exposed_keys": bundle["physiology_outputs"]["exposed_keys"]}
    bundle["status"] = "error" if counts.get("error", 0) else "partial" if blockers else "success"
    return bundle
