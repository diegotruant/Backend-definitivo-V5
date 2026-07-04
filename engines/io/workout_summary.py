"""Workout summary wrapper with two-phase endurance HRV and thermal context.

The legacy orchestrator is preserved in `workout_summary_legacy.py`. This
module keeps its public API while overriding bounded HRV/DFA-alpha1 window
placement and adding core-temperature context when a body-temperature sensor is
available.

- all RR samples remain available;
- the first hour keeps dense windows for ramp/progressive/early autonomic data;
- later endurance windows are sparser to follow durability decay without
  creating thousands of redundant DFA-alpha1 windows;
- core body temperature is surfaced into thermal, cardiac and durability
  interpretation without replacing the original power/HR calculations.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from engines.io import workout_summary_legacy as _legacy
from engines.io.workout_summary_legacy import *  # noqa: F401,F403
from engines.recovery.hrv_endurance_schedule import analyze_rr_stream_endurance_scheduled
from engines.recovery.thermal_engine import analyze_thermal_session
from engines.recovery.hrv_engine import analyze_rr_stream as _analyze_rr_stream

_legacy_build_workout_summary = _legacy.build_workout_summary
from engines.io.workout_summary_legacy import _mmp_curve_to_dict  # noqa: F401


def _argument(args: tuple[Any, ...], kwargs: dict[str, Any], index: int, name: str, default: Any = None) -> Any:
    if name in kwargs:
        return kwargs[name]
    if len(args) > index:
        return args[index]
    return default


def _stream_series(stream: Any, attr: str, n: int) -> list[Optional[float]]:
    raw = getattr(stream, attr, None)
    if raw is None:
        return []
    out: list[Optional[float]] = []
    for value in list(raw[:n]):
        try:
            f = float(value)
        except (TypeError, ValueError):
            out.append(None)
            continue
        out.append(f if np.isfinite(f) else None)
    return out


def _has_core_temperature(stream: Any, n: int) -> bool:
    for value in _stream_series(stream, "core_body_temp", n):
        if value is not None and 30.0 <= value <= 45.0:
            return True
    return False


def _build_thermal_report(stream: Any, *, ftp: Optional[float]) -> Optional[dict[str, Any]]:
    if stream is None:
        return None
    n = int(getattr(stream, "n_samples", 0) or 0)
    if n <= 0 or not _has_core_temperature(stream, n):
        return None
    power = _stream_series(stream, "power", n)
    hr = _stream_series(stream, "heart_rate", n)
    core = _stream_series(stream, "core_body_temp", n)
    skin = _stream_series(stream, "skin_temp", n)
    ambient = _stream_series(stream, "ambient_temp", n)
    if not power or not core:
        return None
    report = analyze_thermal_session(
        core_temp_stream=core,
        power_stream=[float(v or 0.0) for v in power],
        hr_stream=[float(v or 0.0) for v in hr] if hr else None,
        skin_temp_stream=skin or None,
        ambient_temp_stream=ambient or None,
        ftp=ftp,
    )
    return report.to_dict() if hasattr(report, "to_dict") else dict(report)


def _thermal_interpretation(report: dict[str, Any]) -> dict[str, Any]:
    peak = report.get("core_temp_peak")
    thermal_pct = report.get("thermal_drift_pct")
    fatigue_bpm = report.get("cardiac_drift_fatigue_bpm")
    adjusted_decay = report.get("power_decay_thermal_adjusted_pct")
    raw_decay = report.get("power_decay_raw_pct")
    heat_compatible = bool(
        (isinstance(peak, (int, float)) and peak >= 38.5)
        or (isinstance(thermal_pct, (int, float)) and thermal_pct >= 50.0)
    )
    autonomic_fatigue_compatible = bool(
        isinstance(fatigue_bpm, (int, float)) and fatigue_bpm >= 3.0 and not heat_compatible
    )
    return {
        "heat_strain_compatible": heat_compatible,
        "autonomic_fatigue_compatible": autonomic_fatigue_compatible,
        "thermal_drift_pct": thermal_pct,
        "cardiac_drift_fatigue_bpm": fatigue_bpm,
        "power_decay_raw_pct": raw_decay,
        "power_decay_thermal_adjusted_pct": adjusted_decay,
        "interpretation": (
            "heat_strain_dominant" if heat_compatible else
            "fatigue_residual_dominant" if autonomic_fatigue_compatible else
            "thermal_context_available"
        ),
    }


def _attach_thermal_context(out: dict[str, Any], stream: Any, *, ftp: Optional[float]) -> None:
    report = _build_thermal_report(stream, ftp=ftp)
    if not report:
        return
    sections = out.setdefault("sections", {})
    sections["thermal"] = report
    if report.get("data_quality") == "no_data":
        return

    interpretation = _thermal_interpretation(report)
    sections["thermal_interpretation"] = {"status": "success", **interpretation}

    cardiac = sections.get("cardiac")
    if isinstance(cardiac, dict):
        cardiac["thermal_context"] = {
            "available": True,
            "core_temp_peak_c": report.get("core_temp_peak"),
            "core_temp_mean_c": report.get("core_temp_mean"),
            "core_temp_start_c": report.get("core_temp_start"),
            "core_temp_end_c": report.get("core_temp_end"),
            "thermal_rise_rate_c_per_min": report.get("thermal_rise_rate"),
            "thermal_drift_pct": report.get("thermal_drift_pct"),
            "cardiac_drift_total_bpm": report.get("cardiac_drift_total_bpm"),
            "cardiac_drift_thermal_bpm": report.get("cardiac_drift_thermal_bpm"),
            "cardiac_drift_fatigue_bpm": report.get("cardiac_drift_fatigue_bpm"),
            "interpretation": interpretation["interpretation"],
        }

    sections["thermal_adjusted_durability"] = {
        "status": "success",
        "available": True,
        "power_decay_raw_pct": report.get("power_decay_raw_pct"),
        "power_decay_thermal_adjusted_pct": report.get("power_decay_thermal_adjusted_pct"),
        "heat_tolerance_threshold_c": report.get("heat_tolerance_threshold"),
        "heat_tolerance_classification": report.get("heat_tolerance_classification"),
        "eta_correction_factor": report.get("eta_correction_factor"),
        "interpretation": interpretation["interpretation"],
        "note": "Raw durability decay is shown alongside thermal-adjusted decay when core-temperature data are available.",
    }

    headline = out.setdefault("headline", {})
    headline["core_temp_peak_c"] = report.get("core_temp_peak")
    headline["thermal_drift_pct"] = report.get("thermal_drift_pct")
    headline["thermal_adjusted_power_decay_pct"] = report.get("power_decay_thermal_adjusted_pct")
    headline["thermal_fatigue_residual_bpm"] = report.get("cardiac_drift_fatigue_bpm")

    warnings = out.setdefault("warnings", [])
    if interpretation["heat_strain_compatible"]:
        msg = "Core-temperature data indicate heat strain may explain part of cardiac drift/durability loss."
    else:
        msg = "Core-temperature data were used to contextualize cardiac drift and durability decay."
    if not any("Core-temperature data" in str(item) for item in warnings):
        warnings.append(msg)


def build_workout_summary(*args: Any, **kwargs: Any) -> dict:
    """Run the legacy summary with two-phase bounded HRV/DFA and thermal context."""
    last_schedule: dict[str, Any] = {}

    call_kwargs = dict(kwargs)
    if call_kwargs.get("hrv_step_seconds") is None:
        call_kwargs["hrv_step_seconds"] = 10.0

    hrv_max_windows = int(call_kwargs.get("hrv_max_windows") or 500)

    def _scheduled_rr_analyzer(
        rr_samples: list[dict[str, Any]],
        *,
        window_seconds: int = 120,
        step_seconds: float = 10.0,
        context: Any = None,
    ) -> list[dict[str, Any]]:
        import engines.recovery.hrv_engine as hrv_engine

        current_rr = hrv_engine.analyze_rr_stream
        if current_rr is not _analyze_rr_stream:
            return current_rr(
                rr_samples,
                window_seconds=window_seconds,
                step_seconds=step_seconds,
                context=context,
            )
        timeline, schedule = analyze_rr_stream_endurance_scheduled(
            rr_samples,
            window_seconds=window_seconds,
            step_seconds=step_seconds,
            max_windows=hrv_max_windows,
            context=context,
        )
        last_schedule.clear()
        last_schedule.update(schedule)
        return timeline

    call_kwargs["hrv_analyze_fn"] = _scheduled_rr_analyzer
    out = _legacy_build_workout_summary(*args, **call_kwargs)

    if last_schedule:
        hrv = (out.get("sections") or {}).get("hrv")
        if isinstance(hrv, dict) and hrv.get("available") is True:
            hrv.update(
                {
                    "n_windows": len(hrv.get("timeline") or []),
                    "step_seconds": last_schedule.get("dense_step_seconds"),
                    "dense_step_seconds": last_schedule.get("dense_step_seconds"),
                    "sparse_step_seconds": last_schedule.get("sparse_step_seconds"),
                    "dense_until_seconds": last_schedule.get("dense_until_seconds"),
                    "schedule_mode": last_schedule.get("mode"),
                    "schedule": last_schedule,
                    "adaptive_step_applied": bool(last_schedule.get("adaptive_step_applied")),
                }
            )
            warnings = out.setdefault("warnings", [])
            if last_schedule.get("adaptive_step_applied"):
                adaptive_warning = (
                    "HRV/DFA-alpha1 step increased to keep large endurance analysis bounded. "
                    "All RR beats are preserved; only high-cost DFA window density is thinned."
                )
                if not any("HRV/DFA-alpha1 step increased" in str(item) for item in warnings):
                    warnings.append(adaptive_warning)
            if last_schedule.get("mode") == "two_phase_endurance":
                warning = (
                    "HRV/DFA-alpha1 uses a two-phase endurance schedule: "
                    f"dense first hour at ~{last_schedule.get('dense_step_seconds')}s, "
                    f"then sparse endurance-decay windows at ~{last_schedule.get('sparse_step_seconds')}s. "
                    "All RR beats are preserved; only high-cost DFA window density is thinned."
                )
                if not any("two-phase endurance schedule" in str(item) for item in warnings):
                    warnings.append(warning)

    stream = _argument(args, kwargs, 0, "stream")
    ftp = _argument(args, kwargs, 2, "ftp")
    _attach_thermal_context(out, stream, ftp=ftp)
    return out
