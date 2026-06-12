#!/usr/bin/env python3
"""Integration tests for mader_durability (Mader CP-residual forward ODE)."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))


print("\n[1] Engine import and self-demo")
from engines import (
    MaderDurabilityEngine,
    compute_session_durability,
    from_metabolic_snapshot,
    sustainability_targets,
    MetabolicProfiler,
    AthleteContext,
)

engine = MaderDurabilityEngine(
    weight_kg=75.0, vo2max=55.0, vlamax=0.45, mlss_w=265.0, eta=0.23,
)
rng = np.random.default_rng(7)
power = np.concatenate([
    np.full(1800, 150.0),
    rng.normal(230.0, 12.0, 3600).clip(120, 350),
    np.full(1200, 130.0),
])
out = engine.compute(power)
check("compute success", out.get("status") == "success")
check("cp residual curve length", len(out.get("cp_residual_curve", [])) == len(power))
check("lookup table non-empty", bool(out.get("cp_residual_at_kj")))
check("durability loss bounded", 0 <= float(out.get("durability_loss_pct", -1)) <= 100)
check("api_contract present", "api_contract" in out)


print("\n[2] Sustainability targets")
sus = sustainability_targets(out)
check("sustainability success", sus.get("status") == "success")
check("kj budgets present", bool(sus.get("kj_budgets")))
at_10 = (sus.get("sustainable_steady_power_w") or {}).get("at_10pct_cp_loss") or {}
check("3h sustainable power", at_10.get("3h", 0) > 0)
check("training recommendations", bool(sus.get("training_recommendations")))


print("\n[3] Sprinter vs diesel (higher VLamax → faster CP loss)")
power_long = np.concatenate([np.full(3600, 200.0), np.full(3600, 280.0)])
diesel = MaderDurabilityEngine(75, 58, 0.30, 270).compute(power_long)
sprinter = MaderDurabilityEngine(75, 48, 0.85, 220).compute(power_long)
check(
    "sprinter loses more CP than diesel",
    float(sprinter.get("durability_loss_pct", 0)) >= float(diesel.get("durability_loss_pct", 0)),
    f"sprinter={sprinter.get('durability_loss_pct')} diesel={diesel.get('durability_loss_pct')}",
)


print("\n[4] from_metabolic_snapshot + compute_session_durability")
mmp = {15: 980, 60: 540, 300: 340, 720: 300, 1200: 285, 3600: 255}
profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
snap = profiler.generate_metabolic_snapshot(mmp)
eng = from_metabolic_snapshot(snap, weight_kg=72.0)
check("factory from snapshot", eng is not None)
session = compute_session_durability(list(power), snap, weight_kg=72.0)
check("session pipeline success", session.get("status") == "success")
check("session has sustainability", session.get("sustainability", {}).get("status") == "success")


print("\n[5] workout_summary wiring")
from engines import build_workout_summary
from engines.io.fit_parser import parse_fit_records_enhanced
from datetime import datetime, timedelta

base = datetime(2025, 6, 1, 8, 0, 0)
records = [
    {
        "timestamp": base + timedelta(seconds=i),
        "power": int(200 + 30 * np.sin(i / 300)),
        "heart_rate": int(140 + 5 * np.sin(i / 400)),
    }
    for i in range(7200)
]
stream = parse_fit_records_enhanced(records, session_dict={"sport": "cycling", "start_time": base})
summary = build_workout_summary(stream, weight_kg=72.0, ftp=280.0, metabolic_snapshot=snap)
md_sec = summary.get("sections", {}).get("mader_durability", {})
check("workout_summary mader section", md_sec.get("status") == "success")
check("headline mader fields", "mader_durability_loss_pct" in summary.get("headline", {}))


print("\n[6] session_router with metabolic profile")
from engines.io.session_router import decide_route, route_and_run

def _free_ride(n=2000, seed=1):
    rng = np.random.default_rng(seed)
    base = 150 + 60 * np.sin(np.linspace(0, 30, n))
    return list(np.clip(base + rng.normal(0, 35, n), 0, None))

d = decide_route(_free_ride(), filename="ride.fit", ftp=270, has_rr=False, has_metabolic_profile=True)
check("ride routes mader_durability", "mader_durability" in d.engines_to_run)
routed = route_and_run(
    _free_ride(), None, weight_kg=72.0, filename="ride.fit", ftp=270,
    metabolic_snapshot=snap,
)
check(
    "route_and_run mader result",
    routed.get("results", {}).get("mader_durability", {}).get("status") == "success",
)


print("\n[7] Tier registration")
from engines import tier_for, Tier
check("mader_durability tier MODEL", tier_for("mader_durability") == Tier.MODEL)


print("\n" + "=" * 50)
passed = sum(1 for _, ok, _ in results if ok)
print(f"  {passed}/{len(results)} passed")
if passed < len(results):
    sys.exit(1)
print("PASS Mader durability integration checks passed.")
