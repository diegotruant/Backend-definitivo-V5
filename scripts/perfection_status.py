#!/usr/bin/env python3
"""Print progress toward tests/perfection_manifest.json targets."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "perfection_manifest.json"
BASELINE = ROOT / "tests" / "coverage_baseline.json"
COVERAGE = ROOT / "coverage.json"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    phase_id = manifest.get("current_phase", 1)
    phase = next(p for p in manifest["phases"] if p["id"] == phase_id)

    print(f"Perfection program — phase {phase_id}: {phase['name']} ({phase.get('status', '?')})")
    print()

    targets = phase.get("targets", {})
    if COVERAGE.is_file() and BASELINE.is_file():
        cov = json.loads(COVERAGE.read_text(encoding="utf-8"))["totals"]
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        line = float(cov["percent_covered"])
        branch = float(cov["percent_branches_covered"])
        t_line = targets.get("coverage_line_percent")
        t_branch = targets.get("coverage_branch_percent")
        if t_line is not None:
            print(f"  line coverage:   {line:5.1f}%  (phase target {t_line}%, baseline floor {base['line_percent']}%)")
        if t_branch is not None:
            print(f"  branch coverage: {branch:5.1f}%  (phase target {t_branch}%, baseline floor {base['branch_percent']}%)")

    for key, value in targets.items():
        if key.startswith("coverage_"):
            continue
        print(f"  {key}: target {value}")

    print()
    print("Deliverables this phase:")
    for item in phase.get("deliverables", []):
        print(f"  - {item}")

    next_phases = [p for p in manifest["phases"] if p["id"] > phase_id]
    if next_phases:
        nxt = next_phases[0]
        print()
        print(f"Next phase ({nxt['id']}): {nxt['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
