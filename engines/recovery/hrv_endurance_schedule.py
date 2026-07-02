"""Two-phase endurance HRV/DFA scheduling helpers.

Keeps all RR samples available while reducing only high-cost DFA-alpha1
window placement density on long endurance files.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engines.core.athlete_context import AthleteContext
from engines.recovery.hrv_engine import analyze_rr_stream


def _rr_stream_duration_s(rr_samples: List[Dict[str, Any]]) -> float:
    """Return elapsed duration when available, otherwise fall back to summed RR time."""
    elapsed_values: List[float] = []
    rr_sum_s = 0.0
    for sample in rr_samples:
        rr_values = [float(rr) for rr in (sample.get("rr") or []) if rr is not None]
        rr_sum_s += sum(rr_values) / 1000.0
        elapsed_raw = sample.get("elapsed", sample.get("elapsed_s"))
        if elapsed_raw is not None:
            try:
                elapsed_values.append(float(elapsed_raw))
            except (TypeError, ValueError):
                pass
    if elapsed_values:
        return max(elapsed_values) - min(elapsed_values)
    return rr_sum_s


def _split_rr_samples_by_elapsed(
    rr_samples: List[Dict[str, Any]],
    *,
    split_s: float,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
    """Split RR samples around elapsed time. Returns (dense, sparse, has_elapsed)."""
    dense: List[Dict[str, Any]] = []
    sparse: List[Dict[str, Any]] = []
    has_elapsed = True
    for sample in rr_samples:
        elapsed_raw = sample.get("elapsed", sample.get("elapsed_s"))
        if elapsed_raw is None:
            has_elapsed = False
            break
        try:
            elapsed_s = float(elapsed_raw)
        except (TypeError, ValueError):
            has_elapsed = False
            break
        if elapsed_s < split_s:
            dense.append(sample)
        else:
            sparse.append(sample)
    if not has_elapsed:
        return rr_samples, [], False
    return dense, sparse, True


def plan_endurance_hrv_schedule(
    *,
    duration_s: float,
    window_seconds: int = 120,
    requested_step_seconds: float = 10.0,
    max_windows: int = 500,
    dense_until_seconds: float = 3600.0,
    sparse_min_step_seconds: float = 60.0,
    dense_budget_fraction: float = 0.70,
) -> Dict[str, Any]:
    """Plan a two-phase HRV schedule for endurance sessions.

    All RR beats remain available to the analysis. The plan only controls the
    placement density of expensive DFA-alpha1 windows:

    * denser windows in the first hour, where ramp/progressive behavior and
      early autonomic state are most informative;
    * sparser windows after one hour, where the product mainly needs endurance
      decay, heat/autonomic drift and late-ride degradation trends.
    """
    duration_s = max(0.0, float(duration_s))
    window_s = float(window_seconds)
    requested_step = max(1.0, float(requested_step_seconds))
    max_windows_i = max(1, int(max_windows or 0))
    dense_until_s = max(window_s, float(dense_until_seconds))
    sparse_min_step = max(requested_step, float(sparse_min_step_seconds))

    if duration_s <= dense_until_s or duration_s <= window_s:
        expected = int(max(0.0, duration_s - window_s) / requested_step) + 1 if duration_s > window_s else 0
        step = requested_step
        if expected > max_windows_i:
            step = max(requested_step, (duration_s - window_s) / max(float(max_windows_i - 1), 1.0))
        return {
            "mode": "single_phase",
            "duration_s": round(duration_s, 3),
            "dense_until_seconds": dense_until_s,
            "dense_step_seconds": round(float(step), 3),
            "sparse_step_seconds": None,
            "expected_windows_at_requested_step": expected,
            "target_max_windows": max_windows_i,
            "adaptive_step_applied": bool(abs(float(step) - requested_step) > 1e-9),
        }

    dense_duration = dense_until_s
    sparse_duration = max(0.0, duration_s - dense_until_s)
    desired_dense_windows = int(max(0.0, dense_duration - window_s) / requested_step) + 1
    desired_sparse_windows = int(max(0.0, sparse_duration - window_s) / sparse_min_step) + 1 if sparse_duration > window_s else 0
    expected_total = desired_dense_windows + desired_sparse_windows

    if expected_total <= max_windows_i:
        dense_budget = desired_dense_windows
        sparse_budget = max(desired_sparse_windows, 0)
    else:
        dense_budget = min(
            desired_dense_windows,
            max(1, int(round(max_windows_i * float(dense_budget_fraction)))),
        )
        sparse_budget = max(1, max_windows_i - dense_budget)

    dense_step = requested_step
    if dense_budget > 1:
        dense_step = max(requested_step, (dense_duration - window_s) / max(float(dense_budget - 1), 1.0))
    elif desired_dense_windows > 0:
        dense_step = max(requested_step, dense_duration)

    sparse_step = sparse_min_step
    if sparse_duration > window_s and sparse_budget > 1:
        sparse_step = max(sparse_min_step, (sparse_duration - window_s) / max(float(sparse_budget - 1), 1.0))
    elif sparse_duration > 0:
        sparse_step = max(sparse_min_step, sparse_duration)

    return {
        "mode": "two_phase_endurance",
        "duration_s": round(duration_s, 3),
        "dense_until_seconds": dense_until_s,
        "dense_step_seconds": round(float(dense_step), 3),
        "sparse_step_seconds": round(float(sparse_step), 3),
        "expected_windows_at_requested_step": int(max(0.0, duration_s - window_s) / requested_step) + 1,
        "desired_dense_windows": desired_dense_windows,
        "desired_sparse_windows_at_min_step": desired_sparse_windows,
        "dense_window_budget": dense_budget,
        "sparse_window_budget": sparse_budget,
        "target_max_windows": max_windows_i,
        "adaptive_step_applied": bool(
            abs(float(dense_step) - requested_step) > 1e-9
            or abs(float(sparse_step) - sparse_min_step) > 1e-9
        ),
    }


def analyze_rr_stream_endurance_scheduled(
    rr_samples: List[Dict[str, Any]],
    window_seconds: int = 120,
    step_seconds: float = 10.0,
    max_windows: int = 500,
    dense_until_seconds: float = 3600.0,
    sparse_min_step_seconds: float = 60.0,
    context: Optional[AthleteContext] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Analyze all RR samples with dense-first-hour/sparse-endurance windows.

    This does not discard RR data. It only changes where expensive DFA-alpha1
    windows are evaluated. All elapsed RR samples are assigned either to the
    dense first-hour phase or to the sparse endurance phase.
    """
    if not rr_samples:
        return [], {
            "mode": "empty",
            "adaptive_step_applied": False,
            "expected_windows_at_requested_step": 0,
        }

    duration_s = _rr_stream_duration_s(rr_samples)
    schedule = plan_endurance_hrv_schedule(
        duration_s=duration_s,
        window_seconds=window_seconds,
        requested_step_seconds=step_seconds,
        max_windows=max_windows,
        dense_until_seconds=dense_until_seconds,
        sparse_min_step_seconds=sparse_min_step_seconds,
    )

    if schedule["mode"] == "single_phase":
        timeline = analyze_rr_stream(
            rr_samples,
            window_seconds=window_seconds,
            step_seconds=float(schedule["dense_step_seconds"]),
            context=context,
        )
        for row in timeline:
            row.setdefault("metadata", {})["schedule_phase"] = "single_phase"
        return timeline, schedule | {"actual_windows": len(timeline)}

    dense_samples, sparse_samples, has_elapsed = _split_rr_samples_by_elapsed(
        rr_samples,
        split_s=float(schedule["dense_until_seconds"]),
    )
    if not has_elapsed:
        fallback = plan_endurance_hrv_schedule(
            duration_s=duration_s,
            window_seconds=window_seconds,
            requested_step_seconds=step_seconds,
            max_windows=max_windows,
            dense_until_seconds=duration_s,
            sparse_min_step_seconds=sparse_min_step_seconds,
        )
        timeline = analyze_rr_stream(
            rr_samples,
            window_seconds=window_seconds,
            step_seconds=float(fallback["dense_step_seconds"]),
            context=context,
        )
        for row in timeline:
            row.setdefault("metadata", {})["schedule_phase"] = "single_phase_no_elapsed"
        fallback["mode"] = "single_phase_no_elapsed"
        return timeline, fallback | {"actual_windows": len(timeline)}

    dense_timeline = analyze_rr_stream(
        dense_samples,
        window_seconds=window_seconds,
        step_seconds=float(schedule["dense_step_seconds"]),
        context=context,
    ) if dense_samples else []
    for row in dense_timeline:
        row.setdefault("metadata", {})["schedule_phase"] = "dense_first_hour"

    sparse_timeline = analyze_rr_stream(
        sparse_samples,
        window_seconds=window_seconds,
        step_seconds=float(schedule["sparse_step_seconds"] or sparse_min_step_seconds),
        context=context,
    ) if sparse_samples else []
    for row in sparse_timeline:
        row.setdefault("metadata", {})["schedule_phase"] = "sparse_endurance_decay"

    timeline = sorted(dense_timeline + sparse_timeline, key=lambda row: float(row.get("timestamp", 0.0)))
    schedule["actual_windows"] = len(timeline)
    schedule["dense_actual_windows"] = len(dense_timeline)
    schedule["sparse_actual_windows"] = len(sparse_timeline)
    schedule["rr_samples_dense"] = len(dense_samples)
    schedule["rr_samples_sparse"] = len(sparse_samples)
    return timeline, schedule
