"""Explicit behavior contracts for bimodal MMP routing and Mader forward ODE durability.

Coverage suites only assert that segmented/auto helpers return without error.
These tests state product semantics: when a sprint-heavy curve should be
segmented, how aerobic estimates differ from a joint fit, and how the Mader
ODE should respond on a hard ride built from that profile.
"""

from __future__ import annotations

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.mader_durability import (
    MaderDurabilityEngine,
    compute_session_durability,
    from_metabolic_snapshot,
)

CTX = AthleteContext(gender="MALE", training_years=10, discipline="ROAD")

# Ratio 1100/240 ≈ 4.58 — above default 4.2 bimodal threshold.
BIMODAL_MMP = {5: 1100, 15: 1000, 60: 520, 300: 340, 1200: 270, 3600: 240}

# Smooth diesel decay — no short anchor for ratio detection (joint_auto via fallback).
DIESEL_MMP = {300: 340, 600: 310, 1200: 290, 1800: 285, 3600: 270}

# Coherent all-rounder: ratio ≈ 4.07, below 4.2 — must not segment.
UNIMODAL_MMP = {5: 1100, 30: 700, 60: 520, 300: 340, 1200: 295, 3600: 270}

# Gigi-like sprinter: ratio ≈ 4.19 (below auto threshold) but segmented still
# materially lifts aerobic estimates vs a joint fit.
SPRINTER_AEROBIC_MMP = {1: 961, 5: 900, 60: 400, 300: 280, 1200: 255, 3600: 215}


def _supra_mlss_ride(mlss_w: float, *, above_w: float = 40.0) -> list[float]:
    """Two-hour ride: aerobic base then sustained work above MLSS."""
    power = np.concatenate(
        [
            np.full(3600, 200.0),
            np.full(3600, mlss_w + above_w),
        ]
    )
    return [float(p) for p in power]


def _lookup_cp_values(cp_at_kj: dict[int, float]) -> list[float]:
    keys = sorted(cp_at_kj)
    return [float(cp_at_kj[k]) for k in keys]


@pytest.fixture
def profiler() -> MetabolicProfiler:
    return MetabolicProfiler(weight=72.0, context=CTX)


def test_bimodal_auto_fit_selects_segmented_when_ratio_exceeds_threshold(
    profiler: MetabolicProfiler,
) -> None:
    """P_short/P_long ≥ 4.2 must route to segmented fit, not joint."""
    mmp = profiler._coerce_mmp_dict(BIMODAL_MMP)
    ratio = MetabolicProfiler._bimodality_ratio(mmp)
    assert ratio is not None
    assert ratio >= 4.2

    snap = profiler.generate_metabolic_snapshot_auto(BIMODAL_MMP)
    assert snap["status"] == "success"
    assert snap["fit_method"] == "segmented"
    assert snap["bimodality_ratio"] == pytest.approx(round(ratio, 2), abs=0.05)
    assert "segmented" in (snap.get("fit_strategy_reason") or "").lower()
    assert snap.get("segmented_detail", {}).get("vo2max_source") == "aerobic_domain"


def test_unimodal_curve_uses_joint_auto_fit(profiler: MetabolicProfiler) -> None:
    """Coherent power-duration curves (ratio < 4.2) must stay on the joint fit path."""
    mmp = profiler._coerce_mmp_dict(UNIMODAL_MMP)
    ratio = MetabolicProfiler._bimodality_ratio(mmp)
    assert ratio is not None
    assert ratio < 4.2

    snap = profiler.generate_metabolic_snapshot_auto(UNIMODAL_MMP)
    assert snap["status"] == "success"
    assert snap["fit_method"] == "joint_auto"
    assert snap["bimodality_ratio"] == pytest.approx(round(ratio, 2), abs=0.05)
    assert "unimodal" in (snap.get("fit_strategy_reason") or "").lower()


def test_endurance_only_mmp_still_uses_joint_auto_not_segmented(
    profiler: MetabolicProfiler,
) -> None:
    """Long-anchor-only curves cannot be judged bimodal — still no segmented routing."""
    snap = profiler.generate_metabolic_snapshot_auto(DIESEL_MMP)
    assert snap["status"] == "success"
    assert snap["fit_method"] == "joint_auto"
    assert snap.get("bimodality_ratio") is None
    assert "joint fit" in (snap.get("fit_strategy_reason") or "").lower()


def test_segmented_fit_preserves_aerobic_estimates_on_sprinter_heavy_curve() -> None:
    """Joint fit on sprint-heavy MMP must not drag MLSS/VO2 below segmented aerobic domain."""
    profiler = MetabolicProfiler(weight=90.0, context=CTX)
    joint = profiler.generate_metabolic_snapshot(SPRINTER_AEROBIC_MMP)
    segmented = profiler.generate_metabolic_snapshot_segmented(SPRINTER_AEROBIC_MMP)

    assert joint["status"] == "success"
    assert segmented["status"] == "success"
    assert segmented["fit_method"] == "segmented"

    detail = segmented["segmented_detail"]
    assert detail["joint_mlss_power_watts"] == joint["mlss_power_watts"]
    assert detail["joint_vo2max"] == joint["estimated_vo2max"]

    # Product contract: aerobic domain is not contaminated by the sprint anchor.
    assert float(segmented["mlss_power_watts"]) > float(joint["mlss_power_watts"])
    assert float(segmented["estimated_vo2max"]) > float(joint["estimated_vo2max"])


def test_bimodal_segmented_snapshot_feeds_mader_ode_pipeline(
    profiler: MetabolicProfiler,
) -> None:
    """Segmented bimodal profile → forward ODE must report CP loss on supra-MLSS work."""
    snap = profiler.generate_metabolic_snapshot_segmented(BIMODAL_MMP)
    assert snap["status"] == "success"

    engine = from_metabolic_snapshot(snap, weight_kg=72.0)
    assert engine is not None

    mlss = float(snap["mlss_power_watts"])
    session = compute_session_durability(_supra_mlss_ride(mlss), snap, weight_kg=72.0)

    assert session["status"] == "success"
    assert session["cp_baseline"] == pytest.approx(mlss, abs=1.0)
    assert float(session["durability_loss_pct"]) > 0.0
    assert float(session["cp_min"]) < float(session["cp_baseline"])
    assert float(session["session_kj_above_cp"]) > 0.0
    assert session["sustainability"]["status"] == "success"
    assert session["sustainability"]["kj_budgets"]


def test_mader_cp_residual_lookup_non_increasing_with_kj(
    profiler: MetabolicProfiler,
) -> None:
    """Residual CP at higher kJ budgets must not exceed earlier budgets (smoothed lookup)."""
    snap = profiler.generate_metabolic_snapshot_segmented(BIMODAL_MMP)
    mlss = float(snap["mlss_power_watts"])
    session = compute_session_durability(_supra_mlss_ride(mlss, above_w=45.0), snap, 72.0)

    lookup = session.get("cp_residual_at_kj") or {}
    assert len(lookup) >= 3

    cp_values = _lookup_cp_values(lookup)
    for earlier, later in zip(cp_values, cp_values[1:]):
        assert earlier >= later - 1.0, (
            "CP_residual lookup should not rise materially as kJ above CP accumulates"
        )


def test_mader_ode_depletes_more_cp_when_athlete_threshold_is_lower() -> None:
    """Same external load: lower MLSS (sprinter threshold) → more CP loss than diesel threshold.

    Regression guard for the mechanistic story in mader_durability self-test: identical
    second-hour power is more damaging when the athlete's threshold sits further below it.
    """
    power_long = np.concatenate([np.full(3600, 200.0), np.full(3600, 280.0)])

    diesel = MaderDurabilityEngine(weight_kg=75.0, vo2max=58.0, vlamax=0.30, mlss_w=270.0)
    sprinter = MaderDurabilityEngine(weight_kg=75.0, vo2max=48.0, vlamax=0.85, mlss_w=220.0)

    diesel_out = diesel.compute(power_long)
    sprinter_out = sprinter.compute(power_long)

    assert diesel_out["status"] == "success"
    assert sprinter_out["status"] == "success"
    assert float(sprinter_out["durability_loss_pct"]) >= float(diesel_out["durability_loss_pct"])
    assert float(sprinter_out["session_kj_above_cp"]) > float(diesel_out["session_kj_above_cp"])
