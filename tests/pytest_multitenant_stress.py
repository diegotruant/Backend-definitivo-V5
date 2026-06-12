from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from tools.stress.multitenant_stress import build_workload, percentile, summarise, RequestResult, write_outputs


def test_stress_workload_contracts_are_serialisable():
    # Build all profiles and generate one payload per endpoint. This catches
    # schema drift before a real load run fails minutes later.
    from tools.stress.multitenant_stress import WorkloadContext
    import random

    for profile in ["balanced", "read-heavy", "ingest-heavy", "projection-heavy", "full"]:
        ctx = WorkloadContext(
            rng=random.Random(42),
            tenant_count=2,
            coach_count=4,
            athlete_count=16,
            power_samples_min=20,
            power_samples_max=60,
            calendar_events_min=2,
            calendar_events_max=6,
        )
        for item in build_workload(profile):
            kwargs = item.kwargs_factory(ctx, "tenant-1", "coach-1", "athlete-1")
            # httpx kwargs can carry json or form data; both must be JSON/string serialisable.
            if "json" in kwargs:
                json.dumps(kwargs["json"])
            if "data" in kwargs:
                json.dumps(kwargs["data"])


def test_stress_summary_pass_fail_thresholds(tmp_path: Path):
    args = Namespace(
        started_at=1.0,
        base_url="http://test",
        profile="balanced",
        duration_s=1,
        requests=3,
        concurrency=1,
        tenant_count=1,
        coach_count=1,
        athlete_count=1,
        power_samples_min=1,
        power_samples_max=1,
        calendar_events_min=1,
        calendar_events_max=1,
        max_error_rate=0.01,
        max_p95_ms=1000,
    )
    rows = [
        RequestResult("health", 200, True, 10, 100),
        RequestResult("health", 200, True, 20, 100),
        RequestResult("manual_load", 200, True, 30, 100),
    ]
    summary = summarise(rows, elapsed_s=0.5, args=args)
    assert summary["status"] == "pass"
    assert summary["aggregate"]["requests"] == 3
    assert summary["aggregate"]["throughput_rps"] == 6.0
    write_outputs(summary, rows, tmp_path)
    assert (tmp_path / "stress_summary.json").exists()
    assert (tmp_path / "stress_requests.csv").exists()
    assert (tmp_path / "stress_report.md").exists()


def test_percentile_interpolation():
    assert percentile([10, 20, 30, 40], 0.5) == 25
    assert percentile([10], 0.95) == 10
