#!/usr/bin/env python3
"""Test: v5.0.0 — Thermal engine (core body temperature analysis)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import random
random.seed(42)

from engines import (
    analyze_thermal_session, analyze_heat_acclimation,
    ThermalSessionReport, HeatAcclimationTrend,
)

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if not ok and detail else ""))


# =============================================================================
# 1. No body-temperature data → graceful no_data
# =============================================================================
print("\n[1] No body-temperature data")

r = analyze_thermal_session(
    core_temp_stream=[float("nan")] * 3600,
    power_stream=[200.0] * 3600,
)
check("all-NaN → no_data", r.data_quality == "no_data")

r2 = analyze_thermal_session(
    core_temp_stream=[37.0] * 100,  # too few
    power_stream=[200.0] * 100,
)
check("too few samples → no_data", r2.data_quality == "no_data")


# =============================================================================
# 2. Normal endurance ride with progressive heating
# =============================================================================
print("\n[2] Normal endurance — progressive heating")

n = 5400  # 90 min
core = []
power = []
hr = []
for i in range(n):
    t_min = i / 60.0
    # Core temp: starts 37.2, rises to 38.8 over 90 min
    ct = 37.2 + (38.8 - 37.2) * (t_min / 90.0) + random.gauss(0, 0.05)
    core.append(ct)
    # Power: 200W steady with slight decay in second half
    pw = 200 - max(0, (t_min - 60)) * 0.5 + random.gauss(0, 8)
    power.append(max(60, pw))
    # HR: 130 baseline + thermal component + fatigue
    h = 130 + (ct - 37.2) * 9 + max(0, t_min - 60) * 0.15 + random.gauss(0, 2)
    hr.append(h)

r = analyze_thermal_session(core, power, hr_stream=hr, ftp=250)

check("status good", r.data_quality in ("good", "partial"))
check("core_temp_start ~37.2", abs(r.core_temp_start - 37.2) < 0.5,
      f"got {r.core_temp_start}")
check("core_temp_peak ~38.8", abs(r.core_temp_peak - 38.8) < 0.5,
      f"got {r.core_temp_peak}")
check("thermal_rise_rate > 0", r.thermal_rise_rate > 0)
check("thermal_rise_per_kj > 0", r.thermal_rise_per_kj > 0)
check("cardiac_drift_total > 0", r.cardiac_drift_total_bpm > 0)
check("cardiac_drift_thermal > 0", r.cardiac_drift_thermal_bpm > 0)
check("thermal_drift_pct between 0-100",
      0 < r.thermal_drift_pct < 100 if r.thermal_drift_pct else False)
check("time_in_zone populated", r.time_in_zone_s is not None)
check("eta_correction ≤ 1.0", r.eta_correction_factor <= 1.0)


# =============================================================================
# 3. Hot session — danger zone
# =============================================================================
print("\n[3] Hot session — danger zone")

n = 3600
core_hot = [38.5 + (i / n) * 1.5 + random.gauss(0, 0.05) for i in range(n)]
power_hot = [220 - max(0, (i/60 - 30)) * 2 + random.gauss(0, 10) for i in range(n)]
hr_hot = [150 + (core_hot[i] - 38.5) * 10 for i in range(n)]

r = analyze_thermal_session(core_hot, power_hot, hr_stream=hr_hot)

check("peak > 39.5", r.core_temp_peak > 39.5)
check("danger zone time > 0", r.time_in_zone_s["danger_above_39.5"] > 0)
check("warning note present", any("danger" in n.lower() for n in r.notes))


# =============================================================================
# 4. Cool session — no thermal issues
# =============================================================================
print("\n[4] Cool session — stable temp")

n = 3600
core_cool = [37.5 + random.gauss(0, 0.1) for _ in range(n)]
power_cool = [200 + random.gauss(0, 5) for _ in range(n)]

r = analyze_thermal_session(core_cool, power_cool)

check("core_temp_mean ~37.5", abs(r.core_temp_mean - 37.5) < 0.3)
check("rise_rate near zero", abs(r.thermal_rise_rate) < 0.005 if r.thermal_rise_rate else True)
check("no danger notes", not any("danger" in n.lower() for n in r.notes))


# =============================================================================
# 5. Output contract
# =============================================================================
print("\n[5] Output contract")

r = analyze_thermal_session(core, power, hr_stream=hr, ftp=250)
d = r.to_dict()
check("to_dict has tier", "tier" in d)
check("to_dict tier is MODEL", d["tier"] == "MODEL")
check("to_dict has core_temp_peak", "core_temp_peak" in d)


# =============================================================================
# 6. Heat acclimation trend
# =============================================================================
print("\n[6] Heat acclimation trend")

# Improving: rise rate decreases over sessions
sessions = []
for i in range(9):
    rate = 0.025 - i * 0.002  # decreasing
    sessions.append(ThermalSessionReport(
        data_quality="good", n_valid_samples=3000, n_total_samples=3600,
        thermal_rise_rate=rate,
        heat_tolerance_threshold=38.5 + i * 0.1,
    ))

trend = analyze_heat_acclimation(sessions)
check("trend: n_sessions=9", trend.n_sessions == 9)
check("trend: acclimating detected", trend.trend == "acclimating")
check("trend: delta < 0 (improving)", trend.delta_rise_rate < 0)
check("trend: summary present", trend.summary is not None and len(trend.summary) > 10)

# Too few sessions
trend_short = analyze_heat_acclimation(sessions[:2])
check("trend: <3 sessions → no trend", trend_short.trend is None)

# Stable
stable = [ThermalSessionReport(
    data_quality="good", n_valid_samples=3000, n_total_samples=3600,
    thermal_rise_rate=0.02,
) for _ in range(6)]
trend_stable = analyze_heat_acclimation(stable)
check("trend: stable detected", trend_stable.trend == "stable")


# =============================================================================
# 7. Parser integration
# =============================================================================
print("\n[7] Parser integration")

from engines.fit_parser import ActivityStreamEnhanced

s = ActivityStreamEnhanced(n_samples=100)
check("stream has core_body_temp", hasattr(s, "core_body_temp"))
check("stream has skin_temp", hasattr(s, "skin_temp"))
check("stream has ambient_temp", hasattr(s, "ambient_temp"))
check("stream has has_core_sensor", hasattr(s, "has_core_sensor"))
check("core_body_temp starts NaN", np.all(np.isnan(s.core_body_temp)))
check("has_core_sensor default False", s.has_core_sensor is False)


# =============================================================================
# REPORT
# =============================================================================
print()
print("=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"  v5.0.0 THERMAL ENGINE: {passed}/{total} ({100*passed/total:.0f}%)")
print("=" * 60)

if passed < total:
    print("\nFailures:")
    for name, ok, detail in results:
        if not ok:
            print(f"  ✗ {name}: {detail}")
    sys.exit(1)
else:
    print("✓ All thermal engine checks passed.")
    sys.exit(0)
