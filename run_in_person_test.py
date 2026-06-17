#!/usr/bin/env python3
"""
Run an in-person test envelope (tablet app JSON) through test_protocols.

Usage:
  python3 run_in_person_test.py path/to/envelope.json
  cat envelope.json | python3 run_in_person_test.py

See TEST_JSON_CONTRACT.md for the input schema.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.test_protocols import run_test as run_in_person_test


def main() -> int:
    if len(sys.argv) < 2:
        raw = sys.stdin.read()
        if not raw.strip():
            print("Usage: run_in_person_test.py <envelope.json>", file=sys.stderr)
            return 1
        envelope = json.loads(raw)
    else:
        path = Path(sys.argv[1])
        envelope = json.loads(path.read_text(encoding="utf-8"))

    athlete = envelope.get("athlete") or {}
    weight = float(athlete.get("weight_kg") or 70.0)
    profiler = MetabolicProfiler(weight=weight, context=AthleteContext())

    result = run_in_person_test(envelope, profiler=profiler)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
