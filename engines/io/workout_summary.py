"""Workout summary wrapper with two-phase endurance HRV scheduling.

The legacy orchestrator is preserved in `workout_summary_legacy.py`. This
module keeps its public API while overriding only the HRV/DFA-alpha1 window
placement used inside the summary pipeline:

- all RR samples remain available;
- the first hour keeps dense windows for ramp/progressive/early autonomic data;
- later endurance windows are sparser to follow durability decay without
  creating thousands of redundant DFA-alpha1 windows.
"""

from __future__ import annotations

from typing import Any

from engines.io import workout_summary_legacy as _legacy
from engines.io.workout_summary_legacy import *  # noqa: F401,F403
from engines.recovery.hrv_endurance_schedule import analyze_rr_stream_endurance_scheduled

_legacy_build_workout_summary = _legacy.build_workout_summary


def build_workout_summary(*args: Any, **kwargs: Any) -> dict:
    """Run the legacy summary with two-phase bounded HRV/DFA scheduling."""
    last_schedule: dict[str, Any] = {}

    # If callers omit an explicit HRV step, preserve the intended dense-first-hour
    # behavior by passing the normal 10s requested step to the legacy orchestrator.
    # The scheduled analyzer below is what bounds later endurance windows.
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
            warning = (
                "HRV/DFA-alpha1 uses a two-phase endurance schedule: "
                f"dense first hour at ~{last_schedule.get('dense_step_seconds')}s, "
                f"then sparse endurance-decay windows at ~{last_schedule.get('sparse_step_seconds')}s. "
                "All RR beats are preserved; only high-cost DFA window density is thinned."
            )
            warnings = out.setdefault("warnings", [])
            if not any("All RR beats are preserved" in str(item) for item in warnings):
                warnings.append(warning)

    return out
