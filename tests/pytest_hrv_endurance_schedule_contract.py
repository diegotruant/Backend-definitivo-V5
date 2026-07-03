from __future__ import annotations

import pytest

from engines.recovery import hrv_endurance_schedule as sched
from engines.recovery.hrv_endurance_schedule import (
    _rr_stream_duration_s,
    _split_rr_samples_by_elapsed,
    analyze_rr_stream_endurance_scheduled,
    plan_endurance_hrv_schedule,
)


def _rr_samples(n: int = 5000, *, with_elapsed: bool = True):
    rows = []
    for i in range(n):
        row = {"rr": [800.0 + (i % 5)]}
        if with_elapsed:
            row["elapsed"] = float(i)
        rows.append(row)
    return rows


def test_rr_duration_uses_elapsed_or_rr_sum() -> None:
    assert _rr_stream_duration_s([{"elapsed": 0.0, "rr": [1000.0]}, {"elapsed": 10.0, "rr": [900.0]}]) == 10.0
    assert _rr_stream_duration_s([{"rr": [1000.0, 500.0]}, {"rr": [500.0]}]) == 2.0
    assert _rr_stream_duration_s([{"elapsed": "bad", "rr": [1000.0]}]) == 1.0


def test_split_rr_samples_by_elapsed_success_and_fallback() -> None:
    dense, sparse, has_elapsed = _split_rr_samples_by_elapsed(_rr_samples(5), split_s=3.0)
    assert has_elapsed is True
    assert len(dense) == 3
    assert len(sparse) == 2

    dense, sparse, has_elapsed = _split_rr_samples_by_elapsed(_rr_samples(5, with_elapsed=False), split_s=3.0)
    assert has_elapsed is False
    assert len(dense) == 5
    assert sparse == []

    dense, sparse, has_elapsed = _split_rr_samples_by_elapsed([{"elapsed": "x", "rr": [800.0]}], split_s=3.0)
    assert has_elapsed is False
    assert sparse == []


def test_plan_schedule_single_phase_adapts_when_window_budget_is_tight() -> None:
    plan = plan_endurance_hrv_schedule(duration_s=600.0, requested_step_seconds=10.0, max_windows=5)
    assert plan["mode"] == "single_phase"
    assert plan["adaptive_step_applied"] is True
    assert plan["dense_step_seconds"] > 10.0


def test_plan_schedule_two_phase_budget_and_non_adaptive_case() -> None:
    non_adaptive = plan_endurance_hrv_schedule(duration_s=4000.0, requested_step_seconds=300.0, max_windows=100)
    assert non_adaptive["mode"] == "two_phase_endurance"
    assert non_adaptive["adaptive_step_applied"] is False
    assert non_adaptive["dense_window_budget"] >= 1
    assert non_adaptive["sparse_window_budget"] >= 0

    adaptive = plan_endurance_hrv_schedule(duration_s=20_000.0, requested_step_seconds=10.0, max_windows=20)
    assert adaptive["mode"] == "two_phase_endurance"
    assert adaptive["adaptive_step_applied"] is True
    assert adaptive["sparse_step_seconds"] >= 60.0


def test_analyze_rr_stream_scheduled_empty_and_single_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    timeline, plan = analyze_rr_stream_endurance_scheduled([])
    assert timeline == []
    assert plan["mode"] == "empty"

    calls = []

    def fake_analyze(rr_samples, *, window_seconds=120, step_seconds=10.0, context=None):
        calls.append((len(rr_samples), window_seconds, step_seconds, context))
        return [{"timestamp": 1.0}]

    monkeypatch.setattr(sched, "analyze_rr_stream", fake_analyze)
    timeline, plan = analyze_rr_stream_endurance_scheduled(_rr_samples(300), step_seconds=10.0, max_windows=500)
    assert timeline[0]["metadata"]["schedule_phase"] == "single_phase"
    assert plan["actual_windows"] == 1
    assert calls[0][0] == 300


def test_analyze_rr_stream_scheduled_two_phase_and_no_elapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_analyze(rr_samples, *, window_seconds=120, step_seconds=10.0, context=None):
        return [{"timestamp": float(i)} for i, _ in enumerate(rr_samples[:2])]

    monkeypatch.setattr(sched, "analyze_rr_stream", fake_analyze)
    timeline, plan = analyze_rr_stream_endurance_scheduled(_rr_samples(5000), step_seconds=10.0, max_windows=50)
    assert plan["mode"] == "two_phase_endurance"
    assert plan["dense_actual_windows"] == 2
    assert plan["sparse_actual_windows"] == 2
    assert {row["metadata"]["schedule_phase"] for row in timeline} == {"dense_first_hour", "sparse_endurance_decay"}

    timeline, plan = analyze_rr_stream_endurance_scheduled(_rr_samples(5000, with_elapsed=False), step_seconds=10.0, max_windows=50)
    assert plan["mode"] == "single_phase_no_elapsed"
    assert timeline[0]["metadata"]["schedule_phase"] == "single_phase_no_elapsed"
