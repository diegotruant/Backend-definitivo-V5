"""Smoke test for reference worker script (in-memory stores)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIT = ROOT / "tests" / "assets" / "fit" / "garmin_power_hr.fit"
WORKER = ROOT / "tools" / "worker" / "ingest_athlete_model_pipeline.py"


def test_worker_ingest_athlete_model_pipeline_runs() -> None:
    if not FIT.exists():
        import pytest

        pytest.skip("missing FIT asset")
    proc = subprocess.run(
        [
            sys.executable,
            str(WORKER),
            str(FIT),
            "--athlete-id",
            "athlete-worker-smoke",
            "--activity-id",
            "activity-worker-smoke",
            "--activity-file-id",
            "file-worker-smoke",
            "--ride-date",
            "2026-06-30",
            "--weight-kg",
            "72",
            "--dry-run",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert "mmp_status" in payload
    assert payload["mmp_curve_source"] in {"athlete_mmp_aggregate", "mmp_aggregator_rolling_window", "none"}
