#!/usr/bin/env python3
"""
Test: v3.6.0 — Pedaling balance analysis
==========================================

Validates:
  1. Source gating: single_estimated → refused; dual → analyzed; unknown → flagged
  2. Symmetric ride → classification=symmetric, no recommendation
  3. Marked stable asymmetry → recommendation
  4. Drift detection (progressive load transfer between legs)
  5. Drift recommendation triggered even from symmetric baseline
  6. Zone-by-zone breakdown
  7. Insufficient data path
  8. Trend analysis across multiple sessions
"""
import sys
import math
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import date, timedelta

from engines import (
    analyze_pedaling_balance, analyze_balance_trend,
    PedalingBalanceReport, BalanceTrend,
)


results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if not ok and detail else ""))


random.seed(42)


# =============================================================================
# 1. Source gating
# =============================================================================
print("\n[1] Source gating")

# Single-side → refused regardless of data quality
r = analyze_pedaling_balance(
    balance_stream=[50.0]*1800, power_stream=[200.0]*1800,
    pedaling_balance_source="single_estimated",
)
check("single_estimated → refused", r.data_quality == "refused_single_side")
check("single_estimated → no stats computed", r.avg_left_pct is None)

# Unknown → accepted by default
r = analyze_pedaling_balance(
    balance_stream=[49.0]*1800, power_stream=[180.0]*1800,
    pedaling_balance_source="unknown",
)
check("unknown → analyzed by default", r.data_quality in ("good", "limited"))
check("unknown → flagged in notes",
      any("unconfirmed" in n.lower() for n in r.notes))

# Unknown + accept_unknown_source=False → refused
r = analyze_pedaling_balance(
    balance_stream=[49.0]*1800, power_stream=[180.0]*1800,
    pedaling_balance_source="unknown", accept_unknown_source=False,
)
check("unknown + strict mode → refused",
      r.data_quality == "refused_single_side")

# Dual → good
r = analyze_pedaling_balance(
    balance_stream=[49.5]*1800, power_stream=[180.0]*1800,
    pedaling_balance_source="dual",
)
check("dual → data_quality=good", r.data_quality == "good")


# =============================================================================
# 2. Symmetric session
# =============================================================================
print("\n[2] Symmetric session")

balance = [50.0 + random.gauss(0, 1.0) for _ in range(3600)]
power = [180.0 + random.gauss(0, 5) for _ in range(3600)]
r = analyze_pedaling_balance(balance, power, pedaling_balance_source="dual", ftp=250)

check("symmetric: classification", r.asymmetry_classification == "symmetric")
check("symmetric: asymmetry < 2%", r.asymmetry_pct < 2.0,
      f"got {r.asymmetry_pct}%")
check("symmetric: no recommendation", r.clinical_recommendation is None)
check("symmetric: drift stable", r.drift_classification == "stable")


# =============================================================================
# 3. Marked asymmetry
# =============================================================================
print("\n[3] Marked asymmetry (stable)")

balance = [40.0 + random.gauss(0, 1.0) for _ in range(3600)]  # 40/60
power = [180.0 + random.gauss(0, 5) for _ in range(3600)]
r = analyze_pedaling_balance(balance, power, pedaling_balance_source="dual", ftp=250)

check("marked: classification correct",
      r.asymmetry_classification in ("moderate", "marked"))
check("marked: dominant=right", r.dominant_leg == "right")
check("marked: recommendation present", r.clinical_recommendation is not None)
check("marked: unilateral mentioned",
      "unilateral" in (r.clinical_recommendation or "").lower())


# =============================================================================
# 4. Intra-session drift (the clinically interesting case)
# =============================================================================
print("\n[4] Intra-session drift")

# Session starts 50/50 and ends 45/55 — RIGHT leg progressively takes more.
# Drift needs to be > 1.5% between halves to be detected as "drifting".
# We design a 5% total shift to produce ~2.5% half-vs-half drift.
balance = []
n = 5400  # 90 min
for i in range(n):
    progress = i / n
    base = 50.0 - progress * 5.0    # 50.0 → 45.0 (5% shift, drift between halves ≈ 2.5)
    balance.append(base + random.gauss(0, 0.6))
power = [170.0 + random.gauss(0, 5) for _ in range(n)]
r = analyze_pedaling_balance(balance, power, pedaling_balance_source="dual", ftp=250)

check("drift: detected", r.drift_classification in ("drifting", "strong_drift"),
      f"got {r.drift_classification} drift={r.intra_session_drift}")
check("drift: direction is rightward",
      r.drift_direction == "rightward",
      f"got {r.drift_direction}")
check("drift: drift value is negative (left decreasing)",
      r.intra_session_drift < -1.0,
      f"got {r.intra_session_drift}")
check("drift: recommendation triggered (even from near-symmetric)",
      r.clinical_recommendation is not None)
check("drift: recommendation mentions 'left' as weaker leg",
      "left" in (r.clinical_recommendation or "").lower())


# =============================================================================
# 5. Balance-by-zone
# =============================================================================
print("\n[5] Balance by power zone")

balance = []
power = []
# Z2: 30min @ 180W, symmetric
for _ in range(1800):
    balance.append(50.0 + random.gauss(0, 1))
    power.append(180 + random.gauss(0, 5))
# Z4: 20min @ 260W, mild asymmetry (47/53)
for _ in range(1200):
    balance.append(47.0 + random.gauss(0, 1))
    power.append(260 + random.gauss(0, 8))
# Z5: 10min @ 320W, more pronounced (44/56)
for _ in range(600):
    balance.append(44.5 + random.gauss(0, 1.5))
    power.append(320 + random.gauss(0, 10))

r = analyze_pedaling_balance(balance, power, pedaling_balance_source="dual", ftp=250)

check("zones: dict populated", r.balance_by_zone is not None)
check("zones: z1_z2 ≈ 50", abs(r.balance_by_zone.get("z1_z2", 50) - 50) < 1.5)
check("zones: z3_z4 ≈ 47", abs(r.balance_by_zone.get("z3_z4", 0) - 47) < 1.5)
check("zones: z5_plus ≈ 44.5", abs(r.balance_by_zone.get("z5_plus", 0) - 44.5) < 2)
check("zones: shift_with_load detected",
      r.zone_shift_flag == "shifts_with_load")


# =============================================================================
# 6. No FTP → no zone analysis but still works
# =============================================================================
print("\n[6] No FTP provided")

r = analyze_pedaling_balance(
    [49.0]*1800, [180.0]*1800,
    pedaling_balance_source="dual",
    ftp=None,
)
check("no FTP: still classifies", r.asymmetry_classification is not None)
check("no FTP: balance_by_zone is None", r.balance_by_zone is None)


# =============================================================================
# 7. Insufficient data
# =============================================================================
print("\n[7] Insufficient data")

# Very short session
r = analyze_pedaling_balance(
    [49.0]*30, [180.0]*30,
    pedaling_balance_source="dual",
)
check("30 samples → insufficient_data", r.data_quality == "insufficient_data")

# All low power (below 100W threshold)
r = analyze_pedaling_balance(
    [49.0]*3600, [50.0]*3600,
    pedaling_balance_source="dual",
)
check("all low power → insufficient_data", r.data_quality == "insufficient_data")

# NaN balance values
import math
nan_balance = [float("nan")] * 1800
r = analyze_pedaling_balance(
    nan_balance, [200.0]*1800,
    pedaling_balance_source="dual",
)
check("all-NaN balance → insufficient_data",
      r.data_quality == "insufficient_data")


# =============================================================================
# 8. Output contract
# =============================================================================
print("\n[8] Output contract")

r = analyze_pedaling_balance(
    [49.0]*1800, [180.0]*1800,
    pedaling_balance_source="dual", ftp=250,
)
d = r.to_dict()
required = {
    "data_quality", "pedaling_balance_source", "n_total_samples",
    "n_valid_samples", "avg_left_pct", "avg_right_pct", "asymmetry_pct",
    "dominant_leg", "asymmetry_classification", "first_half_left_pct",
    "second_half_left_pct", "intra_session_drift", "drift_classification",
    "drift_direction", "balance_by_zone", "zone_shift_flag",
    "clinical_recommendation", "notes", "tier",
}
check("to_dict has all required keys",
      required.issubset(d.keys()),
      f"missing: {required - set(d.keys())}")
check("tier is REFERENCE", d["tier"] == "REFERENCE")


# =============================================================================
# 9. Trend analysis across multiple sessions
# =============================================================================
print("\n[9] Trend analysis")

def make_session_report(asym_pct, drift):
    """Build a synthetic session report for trend testing."""
    return PedalingBalanceReport(
        data_quality="good",
        pedaling_balance_source="dual",
        n_total_samples=3600,
        n_valid_samples=3500,
        avg_left_pct=50 - asym_pct/2,
        avg_right_pct=50 + asym_pct/2,
        asymmetry_pct=asym_pct,
        dominant_leg="right" if asym_pct > 0 else "left",
        asymmetry_classification=(
            "symmetric" if asym_pct < 4 else
            "mild" if asym_pct < 10 else
            "moderate"
        ),
        first_half_left_pct=50 - asym_pct/2 + 1,
        second_half_left_pct=50 - asym_pct/2 - 1,
        intra_session_drift=drift,
        drift_classification=(
            "stable" if abs(drift) < 1.5 else
            "drifting" if abs(drift) < 3.0 else
            "strong_drift"
        ),
        drift_direction=(
            "stable" if abs(drift) < 1.5 else
            "leftward" if drift > 0 else
            "rightward"
        ),
        balance_by_zone={"z1_z2": 50 - asym_pct/2},
    )

# Worsening trend (asymmetry growing across 9 sessions)
reports = [
    make_session_report(2, 0.5),
    make_session_report(3, 0.8),
    make_session_report(4, 1.0),
    make_session_report(5, 1.2),
    make_session_report(6, 1.8),
    make_session_report(7, 2.0),
    make_session_report(8, 2.2),
    make_session_report(9, 2.5),
    make_session_report(10, 2.8),
]
trend = analyze_balance_trend(reports)

check("trend: 9 usable sessions", trend.n_endurance_sessions == 9)
check("trend: detected as worsening", trend.trend == "worsening")
check("trend: delta > 0", trend.trend_delta_pct > 0)
check("trend: avg drift computed", trend.avg_drift_per_session is not None)

# Stable trend
stable_reports = [make_session_report(5, 0.5) for _ in range(6)]
trend = analyze_balance_trend(stable_reports)
check("trend: stable detected", trend.trend == "stable")

# Insufficient data
short_reports = [make_session_report(5, 0.5)]
trend = analyze_balance_trend(short_reports)
check("trend: <3 sessions → no trend",
      trend.trend is None and "Need at least" in (trend.notes[0] if trend.notes else ""))

# Mix with refused sessions — should be filtered
mixed = [
    make_session_report(5, 1),
    make_session_report(6, 1),
    PedalingBalanceReport(
        data_quality="refused_single_side",
        pedaling_balance_source="single_estimated",
        n_total_samples=1800, n_valid_samples=0,
    ),
    make_session_report(7, 1),
    make_session_report(8, 1),
]
trend = analyze_balance_trend(mixed)
check("trend: filters out refused sessions",
      trend.n_endurance_sessions == 4)


# =============================================================================
# 10. FIT parser integration
# =============================================================================
print("\n[10] FIT parser integration")

from engines.fit_parser import ActivityStreamEnhanced
import numpy as np

# Default stream should have the balance arrays
s = ActivityStreamEnhanced(n_samples=100)
check("ActivityStream has left_right_balance",
      hasattr(s, "left_right_balance"))
check("balance starts as NaN",
      np.all(np.isnan(s.left_right_balance)))
check("pedaling_balance_source attr default",
      s.pedaling_balance_source == "unknown")


# =============================================================================
# REPORT
# =============================================================================
print()
print("=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  v3.6.0 PEDALING BALANCE: {passed}/{total} ({100*passed/total:.0f}%)")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  ✗ {name}: {detail}")
    sys.exit(1)
else:
    print("✓ All v3.6.0 pedaling balance checks passed.")
    sys.exit(0)
