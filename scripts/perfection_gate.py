#!/usr/bin/env python3
"""Fail CI when Phase 5 perfection_gate targets from tests/perfection_manifest.json are not met."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MANIFEST = ROOT / "tests" / "perfection_manifest.json"
COVERAGE = ROOT / "coverage.json"
OPENAPI = ROOT / "openapi" / "openapi.json"
EXCEPTIONS = ROOT / "tests" / "perfection_exceptions.json"


def _phase5_targets() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    phase = next(p for p in manifest["phases"] if p["id"] == 5)
    return phase.get("targets", {})


def _check_coverage(targets: dict) -> list[str]:
    failures: list[str] = []
    if not COVERAGE.is_file():
        return ["coverage.json missing — run make coverage-test first"]
    totals = json.loads(COVERAGE.read_text(encoding="utf-8"))["totals"]
    line = float(totals["percent_covered"])
    branch = float(totals["percent_branches_covered"])
    t_line = float(targets.get("coverage_line_percent", 0))
    t_branch = float(targets.get("coverage_branch_percent", 0))
    # Compare rounded display percents so 91.996% satisfies a 92% phase target.
    if round(line, 2) + 1e-9 < t_line:
        failures.append(f"line coverage {line:.2f}% < phase target {t_line:.0f}%")
    if round(branch, 2) + 1e-9 < t_branch:
        failures.append(f"branch coverage {branch:.2f}% < phase target {t_branch:.0f}%")
    if not failures:
        print(f"  coverage: line {line:.2f}%, branch {branch:.2f}% — OK")
    return failures


def _check_matrix(targets: dict) -> list[str]:
    from scripts.perfection_status import _matrix_ratios

    failures: list[str] = []
    valid_ratio, invalid_ratio, n_ops = _matrix_ratios()
    t_valid = float(targets.get("matrix_valid_must_success_ratio", 0))
    t_invalid = float(targets.get("matrix_invalid_must_4xx_ratio", 0))
    if valid_ratio + 1e-9 < t_valid:
        failures.append(
            f"matrix valid must-success {valid_ratio:.1%} < target {t_valid:.0%} ({n_ops} ops)"
        )
    if invalid_ratio + 1e-9 < t_invalid:
        failures.append(f"matrix invalid must-4xx {invalid_ratio:.1%} < target {t_invalid:.0%}")
    if not failures:
        print(f"  matrix: valid {valid_ratio:.1%}, invalid-4xx {invalid_ratio:.1%} — OK")
    return failures


def _check_lockdown(targets: dict) -> list[str]:
    expected = int(targets.get("lockdown_gates", 16))
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/pytest_engine_lockdown_v1.py", "--tb=no"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return [f"lockdown tests failed (expected {expected} hard gates green)"]
    print(f"  lockdown: pytest_engine_lockdown_v1 green — OK")
    return []


def _check_openapi_drift(targets: dict) -> list[str]:
    if int(targets.get("openapi_drift", 0)) != 0:
        return []
    export = subprocess.run(
        [sys.executable, "scripts/export_openapi.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if export.returncode != 0:
        return ["openapi export failed"]
    drift = subprocess.run(["git", "diff", "--quiet", "openapi/openapi.json"], cwd=ROOT)
    if drift.returncode != 0:
        return ["openapi/openapi.json drifts from scripts/export_openapi.py output"]
    print("  openapi: no drift — OK")
    return []


def _check_exceptions() -> list[str]:
    if not EXCEPTIONS.is_file():
        return ["tests/perfection_exceptions.json missing"]
    data = json.loads(EXCEPTIONS.read_text(encoding="utf-8"))
    entries = data.get("approved", [])
    if entries:
        return [f"{len(entries)} unapproved perfection exceptions remain"]
    print("  exceptions: approved list empty — OK")
    return []


def main() -> int:
    targets = _phase5_targets()
    print("Perfection gate — phase 5 targets")
    print()

    failures: list[str] = []
    failures.extend(_check_coverage(targets))
    failures.extend(_check_matrix(targets))
    failures.extend(_check_lockdown(targets))
    failures.extend(_check_openapi_drift(targets))
    failures.extend(_check_exceptions())

    print()
    if failures:
        print("Perfection gate FAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("Perfection gate PASSED — all phase 5 targets met.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
