"""Tests for power-series VLamax proxy (cLaMax_P)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api_app import app
from engines.metabolic.glycolytic_validation_engine import build_glycolytic_profile
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.metabolic.power_vlamax_estimator import estimate_vlamax_from_power_series

client = TestClient(app)

MMP = {"5": 900, "60": 400, "300": 320, "1200": 280}
ATHLETE = {"weight_kg": 70, "gender": "MALE", "training_years": 10, "discipline": "ENDURANCE"}


def _maximal_sprint_15s() -> list[float]:
    """Sustained all-out 15 s trace (validated-style mean/peak ratio)."""
    peak = 1099.0
    power: list[float] = []
    for i in range(15):
        if i <= 1:
            power.append(peak)
        else:
            power.append(max(650.0, peak - (i - 1) * 18.0))
    return power


def test_power_series_estimator_success() -> None:
    profiler = MetabolicProfiler(weight=70.0)
    out = estimate_vlamax_from_power_series(
        _maximal_sprint_15s(),
        dt_s=1.0,
        weight_kg=70.0,
        eta=profiler.context.expected_eta(),
        active_muscle_mass_kg=profiler.active_muscle_mass,
        vo2max_power_w=400.0,
    )
    assert out["status"] == "success"
    assert 0.05 <= out["estimated_vlamax_mmol_l_s"] <= 1.5
    assert out["method"] == "power_series_glycolytic_proxy_v1"
    assert out["confidence"] >= 0.5
    assert "t_p_peak_s" in out["features"]


def test_power_series_rejects_spike_only_sprint() -> None:
    profiler = MetabolicProfiler(weight=70.0)
    power = [1200.0] + [200.0] * 14
    out = estimate_vlamax_from_power_series(
        power,
        weight_kg=70.0,
        eta=profiler.context.expected_eta(),
        active_muscle_mass_kg=profiler.active_muscle_mass,
    )
    assert out["status"] == "insufficient_sprint"


def test_power_series_lactate_calibration() -> None:
    profiler = MetabolicProfiler(weight=70.0)
    out = estimate_vlamax_from_power_series(
        _maximal_sprint_15s(),
        weight_kg=70.0,
        eta=profiler.context.expected_eta(),
        active_muscle_mass_kg=profiler.active_muscle_mass,
        vo2max_power_w=400.0,
        lactate_pre_mmol_l=1.2,
        lactate_peak_mmol_l=8.0,
    )
    assert out["status"] == "success"
    assert "observed_vlapeak_mmol_l_s" in out
    assert out["lactate_calibration"]["lactate_delta_mmol_l"] == pytest.approx(6.8, abs=0.01)


def test_glycolytic_profile_includes_power_derived_vlamax() -> None:
    profiler = MetabolicProfiler(weight=70.0)
    snap = profiler.generate_metabolic_snapshot(MMP)
    assert snap["status"] == "success"
    profile = build_glycolytic_profile(
        snap,
        profiler=profiler,
        mmp=MMP,
        sprint_power=_maximal_sprint_15s(),
        vo2max_power_w=snap.get("map_aerobic_watts"),
    )
    assert profile["status"] == "success"
    assert "power_derived_vlamax" in profile
    assert profile["power_derived_vlamax"]["method"] == "power_series_glycolytic_proxy_v1"
    assert "vlamax_derivation" in profile
    assert profile["vlamax_derivation"]["agreement"]["verdict"] in {"coherent", "divergent"}


def test_api_vlamax_from_power_series() -> None:
    response = client.post(
        "/profile/vlamax-from-power-series",
        json={
            "athlete": ATHLETE,
            "power": _maximal_sprint_15s(),
            "vo2max_power_w": 400,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    assert body["method"] == "power_series_glycolytic_proxy_v1"


def test_api_glycolytic_profile_with_sprint_power() -> None:
    response = client.post(
        "/profile/glycolytic-profile",
        json={
            "mmp": MMP,
            "athlete": ATHLETE,
            "sprint_power": _maximal_sprint_15s(),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    assert "power_derived_vlamax" in body
