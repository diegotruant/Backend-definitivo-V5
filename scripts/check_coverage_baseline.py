#!/usr/bin/env python3
"""Fail CI if coverage drops below tests/coverage_baseline.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "tests" / "coverage_baseline.json"
REPORT_PATH = ROOT / "coverage.json"


def main() -> int:
    if not REPORT_PATH.is_file():
        print("coverage.json missing — run make coverage-test first", file=sys.stderr)
        return 1

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    totals = json.loads(REPORT_PATH.read_text(encoding="utf-8"))["totals"]
    line = float(totals["percent_covered"])
    branch = float(totals["percent_branches_covered"])

    min_line = float(baseline["line_percent"])
    min_branch = float(baseline["branch_percent"])

    ok = True
    if line + 1e-6 < min_line:
        print(f"LINE coverage regressed: {line:.2f}% < baseline {min_line:.2f}%", file=sys.stderr)
        ok = False
    if branch + 1e-6 < min_branch:
        print(f"BRANCH coverage regressed: {branch:.2f}% < baseline {min_branch:.2f}%", file=sys.stderr)
        ok = False

    if ok:
        print(f"Coverage OK — line {line:.2f}% (>= {min_line:.2f}%), branch {branch:.2f}% (>= {min_branch:.2f}%)")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
