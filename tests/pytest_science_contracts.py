"""Tests for conservative science contracts and coach-facing warnings."""

from __future__ import annotations

from engines.core.science_contracts import (
    cp_anchor_warnings,
    derive_effective_cadence_rpm,
    fatmax_contract_fields,
    fatmax_limitations,
    resolve_w_prime_tau,
    vlamax_contract_fields,
)
from engines.io.workout_summary import build_workout_summary
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.metabolic.zones_engine import seiler_polarization
from engines.performance.physiological_resilience import build_physiological_resilience
from engines.performance.power_engine import fit_critical_power
from engines.performance.w_prime_balance_engine import calculate_w_prime_balance
from tests.fixtures.synthetic_fit import build_synthetic_fit_bytes, parse_synthetic_fit


def test_cp_fit_warns_without_20min_anchor() -> None:
    mmp = [
        {"duration_s": 180, "power_w": 320},
        {"duration_s": 300, "power_w": 300},
        {"duration_s": 600, "power_w": 280},
    ]
    result = fit_critical_power(mmp)
    assert result is not None
    assert result["warnings"]
    assert result["warnings"][0]["code"] == "CP_NO_20MIN_ANCHOR"


def test_cp_fit_no_warning_with_20min_anchor() -> None:
    mmp = [
        {"duration_s": 180, "power_w": 320},
        {"duration_s": 300, "power_w": 300},
        {"duration_s": 600, "power_w": 280},
        {"duration_s": 1200, "power_w": 260},
    ]
    result = fit_critical_power(mmp)
    assert result is not None
    assert result.get("warnings") == []


def test_fatmax_contract_fields_distinguish_lab_and_model() -> None:
    lab = fatmax_contract_fields(measurement_tier="LAB_MEASURED")
    model = fatmax_contract_fields(measurement_tier="MODEL_ESTIMATE")
    assert lab["mfo_is_measured"] is True
    assert model["mfo_is_model_proxy"] is True
    assert "indirect calorimetry" in lab["fatmax_interpretation"].lower()
    assert "not indirect-calorimetry" in model["fatmax_interpretation"].lower()
    assert fatmax_limitations(measurement_tier="LAB_MEASURED")
    assert fatmax_limitations(measurement_tier="MODEL_ESTIMATE")


def test_vlamax_contract_fields_on_snapshot() -> None:
    profiler = MetabolicProfiler(weight=75.0)
    mmp = {1: 900, 5: 800, 15: 700, 60: 500, 180: 380, 300: 340, 600: 310, 1200: 285}
    snap = profiler.generate_metabolic_snapshot(mmp, effective_cadence_rpm=120.0)
    assert snap["status"] == "success"
    assert snap["vlamax_disclaimer"]
    assert "not a direct blood" in snap["vlamax_disclaimer"].lower()
    assert snap["vlamax_label"] == "estimated_lactate_accumulation_rate"
    assert snap["vlamax_not_direct_glycolytic_rate"] is True
    assert snap["vlamax_tier"] == "MODEL"
    assert snap["cadence_anchor"]["effective_cadence_rpm"] == 120.0
    limits = snap.get("limitations") or (snap.get("uncertainty") or {}).get("limitations") or []
    assert limits
    assert any("lactate accumulation" in str(lim).lower() for lim in limits)


def test_segmented_snapshot_carries_vlamax_disclaimer() -> None:
    profiler = MetabolicProfiler(weight=75.0)
    mmp = {
        5: 1100,
        15: 950,
        60: 500,
        180: 380,
        300: 340,
        600: 310,
        1200: 285,
        3600: 260,
    }
    snap = profiler.generate_metabolic_snapshot_segmented(mmp, effective_cadence_rpm=125.0)
    assert snap["status"] == "success"
    assert snap.get("fit_method") == "segmented"
    assert snap["vlamax_disclaimer"]
    assert snap["vlamax_tier"] == "MODEL"


def test_resolve_w_prime_tau_models() -> None:
    skiba, model = resolve_w_prime_tau("skiba_default")
    assert skiba == 546.0
    assert model == "skiba_default"

    elite, model = resolve_w_prime_tau("skiba_default", athlete_level="elite")
    assert elite == 417.0
    assert model == "bartram_elite"

    custom, model = resolve_w_prime_tau(
        "individualized",
        athlete_profile={"w_prime_tau_s": 480.0},
    )
    assert custom == 480.0
    assert model == "individualized"


def test_calculate_w_prime_balance_uses_tau_model() -> None:
    power = [200.0, 400.0, 200.0]
    default = calculate_w_prime_balance(power, cp=250, w_prime=20000)
    elite = calculate_w_prime_balance(
        power,
        cp=250,
        w_prime=20000,
        tau_model="bartram_elite",
        athlete_level="elite",
    )
    assert default[-1] != elite[-1]


def test_seiler_polarized_wording_not_prescriptive() -> None:
    import inspect

    from engines.metabolic import zones_engine

    source = inspect.getsource(zones_engine.seiler_polarization)
    assert "not universally superior" in source
    assert "Valid and common endurance distribution" in source


def test_physiological_resilience_from_mader_section() -> None:
    resilience = build_physiological_resilience(
        mader_durability={
            "status": "success",
            "durability_loss_pct": 7.4,
            "confidence_score": 0.7,
        }
    )
    assert resilience["status"] == "success"
    assert resilience["dcp_pct"] == 7.4
    assert resilience["label"] == "physiological_resilience"


def test_workout_summary_exposes_physiological_resilience() -> None:
    raw = build_synthetic_fit_bytes(
        [
            (1_735_689_600 + i * 60, 220 + (i % 5) * 5, 140 + i % 3, 90)
            for i in range(20)
        ]
    )
    stream = parse_synthetic_fit(raw)
    summary = build_workout_summary(stream, weight_kg=75.0, ftp=250.0)
    assert "physiological_resilience" in summary


def test_derive_effective_cadence_rpm_excludes_coasting() -> None:
    raw = build_synthetic_fit_bytes(
        [
            (1_735_689_600 + i * 60, 220, 140, 0 if i < 5 else 95)
            for i in range(20)
        ]
    )
    stream = parse_synthetic_fit(raw)
    cadence = derive_effective_cadence_rpm(stream)
    assert cadence == 95.0


def test_workout_summary_includes_cadence_anchor_from_stream() -> None:
    raw = build_synthetic_fit_bytes(
        [
            (1_735_689_600 + i * 60, 220 + (i % 5) * 5, 140 + i % 3, 120)
            for i in range(30)
        ]
    )
    stream = parse_synthetic_fit(raw)
    summary = build_workout_summary(stream, weight_kg=75.0, ftp=250.0)
    assert "cadence_anchor" in summary
    assert summary["cadence_anchor"]["effective_cadence_rpm"] == 120.0
    assert summary["cadence_anchor"]["cadence_anchor_status"] == "measured"
    metabolic = summary.get("sections", {}).get("metabolic_snapshot") or {}
    if metabolic.get("status") == "success":
        assert metabolic["cadence_anchor"]["effective_cadence_rpm"] == 120.0


def test_workout_summary_cadence_warning_below_130_rpm() -> None:
    raw = build_synthetic_fit_bytes(
        [
            (1_735_689_600 + i * 60, 220, 140, 110)
            for i in range(30)
        ]
    )
    stream = parse_synthetic_fit(raw)
    summary = build_workout_summary(stream, weight_kg=75.0, ftp=250.0)
    metabolic = summary.get("sections", {}).get("metabolic_snapshot") or {}
    if metabolic.get("status") == "success":
        limits = metabolic.get("limitations") or []
        assert any("below typical" in str(lim).lower() for lim in limits)
