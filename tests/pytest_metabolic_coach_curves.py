"""Coach-facing metabolic curves."""

from __future__ import annotations

from engines.metabolic.metabolic_coach_curves import (
    build_energy_contribution_curve,
    build_lactate_curve,
    build_metabolic_curves_report,
    build_session_fuel_demand_curve,
    build_substrate_curve,
    build_vo2_demand_curve,
)


SNAPSHOT = {
    "status": "success",
    "fatmax_power_watts": 185.0,
    "mlss_power_watts": 282.0,
    "map_aerobic_watts": 392.0,
    "estimated_vo2max": 58.0,
    "estimated_vlamax_mmol_L_s": 0.42,
    "expressiveness": {"reliability": {"mlss": True, "vo2max": True}},
}

LACTATE_STEPS = [
    {"power_w": 120, "lactate_mmol": 1.2},
    {"power_w": 170, "lactate_mmol": 1.7},
    {"power_w": 220, "lactate_mmol": 2.4},
    {"power_w": 270, "lactate_mmol": 4.1},
    {"power_w": 320, "lactate_mmol": 7.2},
]


def test_vo2_demand_curve_maps_watts_to_pct_vo2max() -> None:
    curve = build_vo2_demand_curve(
        SNAPSHOT,
        weight_kg=72,
        eta=0.22,
        power_points=[120, 185, 282, 392],
    )
    assert curve["measurement_tier"] == "MODEL_ESTIMATE"
    assert len(curve["points"]) == 4
    pct_by_power = {row["power_w"]: row["pct_vo2max"] for row in curve["points"]}
    assert pct_by_power[120.0] < pct_by_power[282.0] < pct_by_power[392.0]
    assert any(anchor["label"] == "MLSS" for anchor in curve["anchors"])
    assert curve["model_parameters"]["eta_used"] == 0.22


def test_vo2_demand_curve_returns_insufficient_data_without_weight() -> None:
    curve = build_vo2_demand_curve(SNAPSHOT, weight_kg=None)
    assert curve["measurement_tier"] == "INSUFFICIENT_DATA"
    assert curve["points"] == []
    assert curve["confidence_score"] == 0.0


def test_vo2_demand_curve_generates_default_power_grid_from_fatmax_only() -> None:
    snapshot = {"status": "success", "fatmax_power_watts": 200.0, "estimated_vo2max": 55.0}
    curve = build_vo2_demand_curve(snapshot, weight_kg=70)
    assert curve["measurement_tier"] == "MODEL_ESTIMATE"
    assert len(curve["points"]) >= 10
    domains = {row["domain"] for row in curve["points"]}
    assert "fatmax_low_aerobic_domain" in domains or "moderate_aerobic_domain" in domains


def test_lactate_curve_serializes_threshold_anchors_when_steps_available() -> None:
    curve = build_lactate_curve(LACTATE_STEPS)
    assert curve["measurement_tier"] == "LAB_MEASURED"
    assert len(curve["points"]) == 5
    assert curve["thresholds"]["aerobic_2mmol_watts"] is not None
    assert curve["confidence_score"] >= 0.7


def test_lactate_curve_requires_three_steps() -> None:
    curve = build_lactate_curve(LACTATE_STEPS[:2])
    assert curve["measurement_tier"] == "INSUFFICIENT_DATA"
    assert curve["points"] == []


def test_lactate_curve_skips_invalid_rows() -> None:
    curve = build_lactate_curve(
        LACTATE_STEPS
        + [
            {"power_w": 0, "lactate_mmol": 1.0},
            {"power_w": 350, "lactate_mmol": None},
            {"power_w": 360, "lactate_mmol": -1.0},
            {"power_w": "bad", "lactate_mmol": 2.0},
        ]
    )
    assert curve["measurement_tier"] == "LAB_MEASURED"
    assert len(curve["points"]) == 5


def test_session_fuel_demand_curve_extrapolates_substrate_above_curve() -> None:
    power = [420.0] * 120
    curve = build_session_fuel_demand_curve(
        SNAPSHOT,
        power_stream=power,
        weight_kg=72,
        gender="MALE",
        training_years=12,
        discipline="ROAD",
    )
    assert curve["measurement_tier"] == "MODEL_ESTIMATE"
    assert curve["summary"]["carbohydrate_g"] > 0


def test_substrate_curve_builds_from_snapshot() -> None:
    curve = build_substrate_curve(
        SNAPSHOT,
        weight_kg=72,
        gender="MALE",
        training_years=12,
        discipline="ROAD",
    )
    assert curve["measurement_tier"] in {"MODEL_ESTIMATE", "HEURISTIC"}
    assert curve["points"]
    assert any(anchor["label"] == "FATmax" for anchor in curve["anchors"])


def test_substrate_curve_returns_insufficient_data_for_empty_snapshot() -> None:
    curve = build_substrate_curve({}, weight_kg=72)
    assert curve["measurement_tier"] == "INSUFFICIENT_DATA"
    assert curve["points"] == []


def test_energy_contribution_curve_scales_with_vlamax() -> None:
    curve = build_energy_contribution_curve(SNAPSHOT, durations_s=[5, 30, 300, 3600])
    assert curve["measurement_tier"] == "HEURISTIC"
    assert len(curve["points"]) == 4
    short = curve["points"][0]
    long = curve["points"][-1]
    assert short["pcr_pct"] > long["pcr_pct"]
    assert long["oxidative_pct"] > short["oxidative_pct"]


def test_session_fuel_demand_curve_integrates_substrate_model() -> None:
    power = [180.0] * 120 + [300.0] * 60
    curve = build_session_fuel_demand_curve(
        SNAPSHOT,
        power_stream=power,
        weight_kg=72,
        gender="MALE",
        training_years=12,
        discipline="ROAD",
        dt_s=1.0,
    )
    assert curve["measurement_tier"] == "MODEL_ESTIMATE"
    assert curve["summary"]["carbohydrate_g"] > 0
    assert curve["summary"]["fat_g"] > 0
    assert curve["points"][0]["time_s"] == 0.0
    assert curve["points"][-1]["time_s"] == curve["summary"]["duration_s"] - 1.0


def test_session_fuel_demand_curve_requires_power_stream() -> None:
    curve = build_session_fuel_demand_curve(SNAPSHOT, power_stream=[200.0], weight_kg=72)
    assert curve["measurement_tier"] == "INSUFFICIENT_DATA"
    assert curve["points"] == []


def test_metabolic_curves_report_returns_frontend_ready_curve_bundle() -> None:
    report = build_metabolic_curves_report(
        SNAPSHOT,
        weight_kg=72,
        gender="MALE",
        training_years=12,
        discipline="ROAD",
        eta=0.22,
        lactate_steps=LACTATE_STEPS,
    )
    assert report["status"] == "success"
    assert "vo2_demand" in report["available_curves"]
    assert "substrate_oxidation" in report["available_curves"]
    assert "lactate" in report["available_curves"]
    assert "energy_contribution_by_duration" in report["available_curves"]
    assert report["curves"]["vo2_demand"]["frontend_hint"]["chart_type"] == "line"
    assert report["db_contract"]["store_points"] is True


def test_vo2_demand_curve_uses_default_power_grid_without_anchors() -> None:
    curve = build_vo2_demand_curve({"estimated_vo2max": 50.0}, weight_kg=70)
    assert curve["measurement_tier"] == "MODEL_ESTIMATE"
    assert curve["points"][0]["power_w"] >= 40.0


def test_vo2_demand_curve_marks_recovery_domain_at_low_power() -> None:
    curve = build_vo2_demand_curve(SNAPSHOT, weight_kg=72, power_points=[80])
    assert curve["points"][0]["domain"] == "recovery_low_aerobic"


def test_energy_contribution_curve_ignores_non_positive_durations() -> None:
    curve = build_energy_contribution_curve(SNAPSHOT, durations_s=[0, -5, 30])
    assert len(curve["points"]) == 1
    assert curve["points"][0]["duration_s"] == 30.0


def test_session_fuel_demand_curve_fails_when_substrate_unavailable() -> None:
    power = [200.0] * 120
    curve = build_session_fuel_demand_curve({}, power_stream=power, weight_kg=72)
    assert curve["measurement_tier"] == "INSUFFICIENT_DATA"
    assert curve["points"] == []


def test_metabolic_curves_report_marks_missing_session_fuel_without_power() -> None:
    report = build_metabolic_curves_report(
        SNAPSHOT,
        weight_kg=72,
        gender="MALE",
        training_years=12,
        discipline="ROAD",
        include_curves=["session_fuel_demand"],
    )
    assert "session_fuel_demand" in report["missing_curves"][0]["curve"] or report["missing_curves"]
    fuel = report["curves"]["session_fuel_demand"]
    assert fuel["measurement_tier"] == "INSUFFICIENT_DATA"
