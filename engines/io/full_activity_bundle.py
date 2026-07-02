from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from engines.core.athlete_context import AthleteContext
from engines.io.activity_charts import build_activity_charts
from engines.io.activity_intelligence import build_activity_intelligence
from engines.io.data_quality_report import build_data_quality_report
from engines.io.fit_parse_report import build_fit_parse_report
from engines.io.workout_summary import build_workout_summary


def _valid(values: Any, *, min_value: Optional[float] = None) -> bool:
    if values is None:
        return False
    try:
        arr = np.asarray(values, dtype=float)
    except Exception:
        return False
    arr = arr[np.isfinite(arr)] if arr.size else arr
    if min_value is not None:
        arr = arr[arr >= min_value]
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
        return bool(getattr(stream, "has_core_sensor", False)) and _valid(getattr(stream, "core_body_temp", None), min_value=30.0)
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
        if status in {"success", "ok"} or value:
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
    return row


def _zones_for_charts(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    zones = ((summary.get("sections") or {}).get("zones") or {})
    for key in ("coggan_power_zones", "power_zones", "metabolic_power_zones"):
        candidate = zones.get(key) if isinstance(zones, dict) else None
        if isinstance(candidate, dict):
            rows = candidate.get("zones") or candidate.get("time_in_zone") or candidate.get("distribution")
            if isinstance(rows, list):
                return rows
        if isinstance(candidate, list):
            return candidate
    return []


def _hrv_for_charts(summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    hrv = ((summary.get("sections") or {}).get("hrv") or {})
    return hrv if isinstance(hrv, dict) and hrv.get("available") is True else None


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
    ("data_quality", "activity_intelligence.data_quality", ()),
    ("chart_series", "activity_intelligence.chart_series", ()),
    ("chart_power", "activity_charts.power", ("power",)),
    ("chart_heart_rate", "activity_charts.heart_rate", ("heart_rate",)),
    ("chart_elevation", "activity_charts.elevation", ("altitude",)),
    ("chart_cadence", "activity_charts.cadence", ("cadence",)),
    ("chart_ambient_temp", "activity_charts.ambient_temp", ("ambient_temperature",)),
    ("chart_thermal", "activity_charts.thermal", ("core_temperature",)),
    ("chart_time_in_power_zone", "activity_charts.time_in_power_zone", ("power",)),
    ("chart_time_in_intensity", "activity_charts.time_in_intensity", ("rr",)),
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
    bundle = {"status": "success", "schema_version": "1.0.0", "parse_report": parse_report, "data_quality_report": data_quality, "workout_summary": summary, "activity_intelligence": intelligence, "activity_charts": charts}
    for name, path, required in EXPECTATIONS:
        manifest.append(_entry(name, path, _path(bundle, path), required, stream, metabolic_snapshot))
    counts = {"success": 0, "skipped": 0, "partial": 0, "error": 0}
    for row in manifest:
        status = str(row.get("status") or "error")
        counts[status] = counts.get(status, 0) + 1
    bundle["engine_manifest"] = manifest
    bundle["manifest_summary"] = {"total_engines": len(manifest), "success": counts.get("success", 0), "skipped": counts.get("skipped", 0), "partial": counts.get("partial", 0), "error": counts.get("error", 0)}
    bundle["status"] = "error" if counts.get("error", 0) else "success"
    return bundle
