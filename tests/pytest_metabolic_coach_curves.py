"""Coach-facing metabolic curves."""

from __future__ import annotations

from engines.metabolic.metabolic_coach_curves import (
    build_lactate_curve,
    build_metabolic_curves_report,
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


def test_lactate_curve_serializes_threshold_anchors_when_steps_available() -> None:
    curve = build_lactate_curve([
        {"power_w": 120, "lactate_mmol": 1.2},
        {"power_w": 170, "lactate_mmol": 1.7},
        {"power_w": 220, "lactate_mmol": 2.4},
        {"power_w": 270, "lactate_mmol": 4.1},
        {"power_w": 320, "lactate_mmol": 7.2},
    ])
    assert curve["measurement_tier"] == "LAB_MEASURED"
    assert len(curve["points"]) == 5
    assert curve["thresholds"]["aerobic_2mmol_watts"] is not None
    assert curve["confidence_score"] >= 0.7


def test_metabolic_curves_report_returns_frontend_ready_curve_bundle() -> None:
    report = build_metabolic_curves_report(
        SNAPSHOT,
        weight_kg=72,
        gender="MALE",
        training_years=12,
        discipline="ROAD",
        eta=0.22,
        lactate_steps=[
            {"power_w": 120, "lactate_mmol": 1.2},
            {"power_w": 170, "lactate_mmol": 1.7},
            {"power_w": 220, "lactate_mmol": 2.4},
            {"power_w": 270, "lactate_mmol": 4.1},
            {"power_w": 320, "lactate_mmol": 7.2},
        ],
    )
    assert report["status"] == "success"
    assert "vo2_demand" in report["available_curves"]
    assert "substrate_oxidation" in report["available_curves"]
    assert "lactate" in report["available_curves"]
    assert "energy_contribution_by_duration" in report["available_curves"]
    assert report["curves"]["vo2_demand"]["frontend_hint"]["chart_type"] == "line"
    assert report["db_contract"]["store_points"] is True
