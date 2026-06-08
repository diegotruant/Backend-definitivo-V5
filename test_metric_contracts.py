#!/usr/bin/env python3
"""
Regression tests for unified metric uncertainty/API contracts.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))


print("\n[1] Public contract helpers")
from engines import (
    ConfidenceLevel,
    MetricEnvelope,
    MetricUncertainty,
    annotate_payload,
    build_api_contract,
    build_uncertainty,
    metric_envelope,
    normalize_confidence,
    summarize_section_contracts,
)

check("normalize numeric 0..100", normalize_confidence(85) == 0.85)
check("normalize string HIGH", normalize_confidence("HIGH") == 0.9)
unc = build_uncertainty(module_name="metabolic_profiler", method="test", confidence=0.72)
check("uncertainty has MODERATE level", unc.confidence_level == ConfidenceLevel.MODERATE)
check("uncertainty serializes", unc.to_dict()["confidence_score"] == 0.72)
contract = build_api_contract(
    module_name="power_engine",
    status="success",
    method="coggan_power_metrics",
    confidence=1.0,
)
check("contract has schema version", contract["schema_version"] == "metric_contract.v1")
check("contract has tier", contract["tier"] == "REFERENCE")
payload = annotate_payload({"status": "success"}, module_name="durability_engine", confidence=0.6)
check("annotate_payload adds api_contract", "api_contract" in payload)
envelope = metric_envelope(
    "np",
    250.0,
    unit="W",
    module_name="power_engine",
    method="coggan_np",
    confidence=1.0,
)
check("metric_envelope has uncertainty", envelope["uncertainty"]["tier"] == "REFERENCE")
check("dataclasses importable", MetricEnvelope is not None and MetricUncertainty is not None)


print("\n[2] Engine payloads expose common contract")
from engines import AthleteContext, MetabolicProfiler
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.performance.power_engine import PowerEngine
from engines import build_workout_summary

base = datetime(2026, 1, 1, 8, 0, 0)
records = [
    {
        "timestamp": base + timedelta(seconds=i),
        "power": 220,
        "heart_rate": 145,
        "cadence": 88,
    }
    for i in range(1800)
]
stream = parse_fit_records_enhanced(records, session_dict={"sport": "cycling", "start_time": base})
power_result = PowerEngine(ftp=280, weight_kg=72).analyze(stream)
check("power result has api_contract", "api_contract" in power_result)
check("power result uncertainty very high",
      power_result["uncertainty"]["confidence_level"] == "very_high")

profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
mmp = {5: 1100, 30: 700, 60: 520, 180: 380, 300: 340,
       600: 310, 1200: 295, 1800: 285, 3600: 270}
snapshot = profiler.generate_metabolic_snapshot(mmp)
check("metabolic snapshot has api_contract", "api_contract" in snapshot)
check("metabolic snapshot tier MODEL", snapshot["api_contract"]["tier"] == "MODEL")

summary = build_workout_summary(stream, weight_kg=72.0, ftp=280.0)
check("summary has api_contract", "api_contract" in summary)
check("summary has section_contracts", "section_contracts" in summary)
check("section contracts include power", "power" in summary["section_contracts"])
section_summary = summarize_section_contracts(summary["sections"])
check("summarize_section_contracts returns power", "power" in section_summary)


print("\n" + "=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  {passed}/{total} metric contract checks passed")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL {name}: {detail}")
    sys.exit(1)

print("PASS Metric contract regressions passed.")
sys.exit(0)
