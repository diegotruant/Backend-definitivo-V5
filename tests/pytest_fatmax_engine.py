"""FATmax engine — lab/model report tests."""

from __future__ import annotations

from engines.metabolic.fatmax_engine import (
    GasExchangePoint,
    build_lab_fatmax_report,
    build_model_fatmax_report,
    compare_fatmax_reports,
    substrate_oxidation_from_vo2_vco2,
)


def test_substrate_oxidation_from_vo2_vco2_is_physiological() -> None:
    out = substrate_oxidation_from_vo2_vco2(3.0, 2.55)
    assert out["status"] == "success"
    assert 0.7 <= out["rer"] <= 0.9
    assert out["fat_g_min"] > 0
    assert out["carbohydrate_g_min"] > 0


def test_lab_fatmax_report_exposes_measured_mfo_and_base_width() -> None:
    points = [
        GasExchangePoint(power_w=120, vo2_l_min=2.05, vco2_l_min=1.65),
        GasExchangePoint(power_w=160, vo2_l_min=2.45, vco2_l_min=1.95),
        GasExchangePoint(power_w=190, vo2_l_min=2.80, vco2_l_min=2.22),
        GasExchangePoint(power_w=230, vo2_l_min=3.20, vco2_l_min=2.75),
        GasExchangePoint(power_w=270, vo2_l_min=3.60, vco2_l_min=3.35),
    ]
    report = build_lab_fatmax_report(points, athlete_weight_kg=72, mlss_power_w=285)
    assert report["status"] == "success"
    assert report["measurement_tier"] == "LAB_MEASURED"
    assert report["summary"]["mfo_tier"] == "measured_from_vo2_vco2"
    assert report["summary"]["fatmax_power_w"] in {160.0, 190.0, 230.0}
    assert report["summary"]["mfo_g_min"] > 0.5
    assert report["curve"]["fatmax_base"]["available"] is True
    assert report["confidence_score"] >= 0.75


def test_model_fatmax_report_never_claims_lab_measurement() -> None:
    snapshot = {
        "status": "success",
        "fatmax_power_watts": 185.0,
        "mlss_power_watts": 282.0,
        "map_aerobic_watts": 392.0,
        "estimated_vo2max": 58.0,
        "estimated_vlamax_mmol_L_s": 0.42,
        "expressiveness": {"reliability": {"mlss": True, "vo2max": True}},
    }
    report = build_model_fatmax_report(
        snapshot,
        athlete_weight_kg=72,
        gender="MALE",
        training_years=12,
        discipline="ROAD",
    )
    assert report["status"] == "success"
    assert report["measurement_tier"] == "MODEL_ESTIMATE"
    assert report["summary"]["mfo_tier"] == "estimated_model_proxy_not_gas_exchange"
    assert report["curve"]["fatmax_base"]["available"] is True
    assert report["confidence_score"] >= 0.65
    assert any("not measured" in item for item in report["limitations"])


def test_fatmax_compare_detects_right_shift_and_width_change() -> None:
    previous = {
        "summary": {"fatmax_power_w": 172.0, "mfo_g_min": 0.52},
        "curve": {"fatmax_base": {"width_w": 32.0}},
    }
    current = {
        "summary": {"fatmax_power_w": 190.0, "mfo_g_min": 0.60},
        "curve": {"fatmax_base": {"width_w": 48.0}},
    }
    shift = compare_fatmax_reports(previous, current).to_dict()
    assert shift["available"] is True
    assert shift["direction"] == "right_shift"
    assert shift["delta_fatmax_w"] == 18.0
    assert shift["delta_base_width_w"] == 16.0
