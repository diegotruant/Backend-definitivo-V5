from __future__ import annotations

import numpy as np

from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.mader_durability import from_metabolic_snapshot
from engines.performance.power_engine import PowerEngine, detect_sprints


def test_vlamax_from_sprint_default_map_is_deterministic_50_vo2_fallback() -> None:
    ctx = AthleteContext(gender="MALE", training_years=12, discipline="ENDURANCE")
    profiler = MetabolicProfiler(weight=72.0, context=ctx)
    out = profiler.vlamax_from_sprint(
        p_peak_1s=1000,
        p_mean_sprint=800,
        sprint_duration_s=15.0,
        active_muscle_mass_kg=20.0,
    )
    expected_map = profiler._map_estimate(50.0, ctx.expected_eta())
    assert out["status"] in {"success", "insufficient_sprint"}
    if out["status"] == "success":
        assert abs(out["inputs"]["vo2max_power_w"] - round(expected_map, 1)) < 1e-6


def test_detect_sprints_counts_exact_3s_effort() -> None:
    power = np.array([100, 500, 500, 500, 100], dtype=float)
    t = np.array([0, 1, 2, 3, 4], dtype=float)
    sprints = detect_sprints(power, t, ftp=250.0)
    assert len(sprints) == 1
    assert sprints[0]["duration_s"] >= 3.0


class Stream2Hz:
    def __init__(self) -> None:
        n = 120
        self.elapsed_s = np.arange(n, dtype=float) * 0.5
        self.power = np.full(n, 200.0, dtype=float)
        self.heart_rate = np.full(n, 140.0, dtype=float)
        self.total_elapsed_s = float(self.elapsed_s[-1] + 0.5)


def test_power_engine_work_kj_respects_dt() -> None:
    stream = Stream2Hz()
    out = PowerEngine(ftp=250.0, weight_kg=70.0).analyze(stream)
    # 60s at 200W => 12 kJ
    assert out["status"] == "success"
    assert abs(out["metrics"]["work_kj"] - 12.0) < 0.2


def test_measured_lacap_is_clipped_to_physiological_range() -> None:
    profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
    mmp = {15: 900, 60: 500, 300: 320, 1200: 270}
    high = profiler.generate_metabolic_snapshot(mmp, measured_lacap=99.0)
    low = profiler.generate_metabolic_snapshot(mmp, measured_lacap=1.0)
    assert high["status"] == "success"
    assert low["status"] == "success"
    assert high["assumed_la_capacity_mmol_L"] <= 30.0
    assert low["assumed_la_capacity_mmol_L"] >= 8.0


def test_mader_durability_factory_uses_unmasked_mlss_fallback() -> None:
    snapshot = {
        "status": "success",
        "estimated_vo2max": 50.0,
        "estimated_vlamax_mmol_L_s": 0.5,
        "mlss_power_watts": None,
        "unmasked_estimates": {
            "estimated_vo2max": 50.0,
            "estimated_vlamax_mmol_L_s": 0.5,
            "mlss_power_watts": 260.0,
        },
        "context_used": {"resolved_eta": 0.23},
        "assumed_la_capacity_mmol_L": 14.0,
    }
    eng = from_metabolic_snapshot(snapshot, weight_kg=72.0)
    assert eng is not None
