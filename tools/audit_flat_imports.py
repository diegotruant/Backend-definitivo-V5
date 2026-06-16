#!/usr/bin/env python3
"""Audit legacy flat imports and `from engines import ...` usage."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

PATTERNS = [
    re.compile(r"^\s*from\s+engines\s+import\s+"),
    re.compile(
        r"^\s*from\s+("
        r"analysis|athlete_context|athlete_physiological_prior|audit|data_quality_engine|metric_contracts|tiers|"
        r"bayesian_profiler|coggan_classifier|cross_validation_engine|detraining_engine|lab_data|"
        r"lactate_validation_engine|metabolic_current|metabolic_flexibility_engine|metabolic_kalman|"
        r"metabolic_profiler|metabolic_profiler_phenotype|zones_engine|"
        r"durability_engine|efforts_analyzer|interval_detector|mader_durability|mmp_aggregator|mmp_quality|"
        r"neural_ode|power_engine|race_prediction_engine|test_protocols|training_variability_engine|"
        r"w_prime_balance_engine|"
        r"cardiac_engine|explainability_engine|hrv_engine|pedaling_balance|thermal_engine|"
        r"activity_charts|activity_intelligence|fit_parser|session_router|workout_summary"
        r")\s+import\s+"
    ),
]


def is_match(line: str) -> bool:
    return any(p.search(line) for p in PATTERNS)


def scan(path: Path) -> list[str]:
    if not path.exists():
        return []
    out: list[str] = []
    for file in sorted(path.rglob("*.py")):
        rel = file.relative_to(ROOT)
        for idx, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
            if is_match(line):
                out.append(f"{rel}:{idx}:{line.strip()}")
    return out


def main() -> None:
    areas = ["api", "tests", "tools", "engines"]
    total = 0
    for area in areas:
        hits = scan(ROOT / area)
        total += len(hits)
        print(f"[{area}] {len(hits)}")
        for row in hits[:10]:
            print(f"  {row}")
        if len(hits) > 10:
            print(f"  ... {len(hits)-10} more")
    print(f"\nTotal matches: {total}")


if __name__ == "__main__":
    main()
