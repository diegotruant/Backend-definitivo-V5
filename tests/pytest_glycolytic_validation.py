"""Tests for vLaPeak validation and glycolytic profile contract."""

from __future__ import annotations

from engines.metabolic.glycolytic_validation_engine import (
    build_glycolytic_profile,
    compute_vlapeak_observed,
    glycolytic_flux_index,
    validate_vlapeak_against_model,
    validate_wingate_glycolytic,
)
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.test_protocols import run_wingate_test


def test_compute_vlapeak_observed_wackerhage() -> None:
    out = compute_vlapeak_observed(1.1, 8.6, 15.0)
    assert out["status"] == "success"
    assert out["vlapeak_observed_mmol_l_s"] == round(7.5 / 15.0, 4)


def test_glycolytic_flux_index_scales_with_vlamax() -> None:
    low = glycolytic_flux_index(0.25)
    mid = glycolytic_flux_index(0.45)
    high = glycolytic_flux_index(0.75)
    assert low < mid < high
    assert 0 <= low <= 100


def test_validate_vlapeak_within_tolerance() -> None:
    out = validate_vlapeak_against_model(
        vlapeak_observed_mmol_l_s=0.50,
        predicted_vlapeak_mmol_l_s=0.52,
        model_vlamax_mmol_l_s=0.47,
    )
    assert out["validated"] is True
    assert out["error_pct"] == 4.0


def test_metabolic_snapshot_includes_glycolytic_profile() -> None:
    profiler = MetabolicProfiler(weight=72.0)
    mmp = {1: 900, 5: 800, 15: 700, 60: 500, 180: 380, 300: 340, 600: 310, 1200: 285}
    snap = profiler.generate_metabolic_snapshot(mmp)
    assert snap["status"] == "success"
    gp = snap.get("glycolytic_profile") or {}
    assert gp.get("status") == "success"
    assert "glycolytic_flux_index" in gp
    assert gp["predicted_vlapeak"]["predicted_vlapeak_mmol_l_s"] is not None
    assert gp["vlamax_semantics"] == "model_parameter_not_direct_measurement"


def test_wingate_with_lactate_runs_glycolytic_validation() -> None:
    profiler = MetabolicProfiler(weight=72.0)
    envelope = {
        "test_type": "wingate",
        "athlete": {"weight_kg": 72},
        "mmp": {"1": 900, "5": 800, "15": 700, "60": 500, "300": 340, "1200": 285},
        "test_data": {
            "duration_s": 15,
            "power_stream": [900] * 15,
            "lactate_pre_mmol": 1.1,
            "lactate_post_mmol": 8.6,
        },
    }
    out = run_wingate_test(envelope, profiler=profiler)
    assert out["status"] == "success"
    gv = out["glycolytic_validation"]
    assert gv["status"] == "success"
    assert gv["vlapeak_observed"]["vlapeak_observed_mmol_l_s"] == round(7.5 / 15.0, 4)
    assert "validation" in gv


def test_validate_wingate_glycolytic_direct() -> None:
    profiler = MetabolicProfiler(weight=72.0)
    mmp = {1: 900, 5: 800, 15: 700, 60: 500, 300: 340, 1200: 285}
    out = validate_wingate_glycolytic(
        lactate_pre_mmol=1.0,
        lactate_post_mmol=7.0,
        duration_s=15.0,
        peak_power_w=900.0,
        mean_power_w=850.0,
        profiler=profiler,
        mmp=mmp,
    )
    assert out["status"] == "success"
    assert out["validation"]["vlapeak_observed_mmol_l_s"] == round(6.0 / 15.0, 4)


def test_build_glycolytic_profile_includes_glycogen_cost_when_combustion_present() -> None:
    profiler = MetabolicProfiler(weight=72.0)
    snap = profiler.generate_metabolic_snapshot(
        {5: 800, 60: 500, 300: 340, 1200: 285, 3600: 265},
    )
    profile = build_glycolytic_profile(snap, profiler=profiler)
    if snap.get("combustion_curve"):
        assert profile.get("predicted_glycogen_cost") is not None
