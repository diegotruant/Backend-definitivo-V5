"""FATmax engine — lab/model report tests."""

from __future__ import annotations

from engines.metabolic.fatmax_engine import (
    FATMAX_MLSS_RATIO,
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


def test_substrate_oxidation_rejects_invalid_inputs() -> None:
    out = substrate_oxidation_from_vo2_vco2(0.0, 2.0)
    assert out["status"] == "invalid_data"
    assert out["fat_g_min"] is None


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
    assert report["mfo_is_measured"] is True
    assert report["curve"]["carbohydrate_crossover"]["method"] == "indirect_calorimetry_g_min"
    assert report["curve"]["smoothing"]["applied"] is True


def test_lab_fatmax_report_rejects_too_few_points() -> None:
    report = build_lab_fatmax_report(
        [
            GasExchangePoint(power_w=120, vo2_l_min=2.0, vco2_l_min=1.6),
            GasExchangePoint(power_w=160, vo2_l_min=2.4, vco2_l_min=1.9),
        ],
        athlete_weight_kg=72,
    )
    assert report["status"] == "insufficient_data"
    assert report["reason"] == "at_least_three_gas_exchange_points_required"


def test_lab_fatmax_report_flags_rer_mismatch_and_invalid_points() -> None:
    points = [
        GasExchangePoint(power_w=120, vo2_l_min=2.05, vco2_l_min=1.65, rer=0.99),
        GasExchangePoint(power_w=160, vo2_l_min=0.0, vco2_l_min=1.95),
        GasExchangePoint(power_w=190, vo2_l_min=2.80, vco2_l_min=2.22, heart_rate_bpm=142),
        GasExchangePoint(power_w=230, vo2_l_min=3.20, vco2_l_min=2.75),
    ]
    report = build_lab_fatmax_report(points, athlete_weight_kg=72, mlss_power_w=285)
    assert report["status"] == "success"
    warning_types = {item["type"] for item in report["warnings"]}
    assert "rer_mismatch" in warning_types
    assert "invalid_gas_point" in warning_types
    assert report["curve"]["carbohydrate_crossover_w"] is not None


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


def test_model_fatmax_report_derives_from_mlss_only() -> None:
    snapshot = {
        "status": "success",
        "mlss_power_watts": 280.0,
        "estimated_vo2max": 55.0,
        "estimated_vlamax_mmol_L_s": 0.50,
    }
    report = build_model_fatmax_report(
        snapshot,
        athlete_weight_kg=70,
        gender="FEMALE",
        training_years=8,
        discipline="SPRINT",
        recent_training_status="BASE",
        environment_context={"temperature_c": 18},
        nutrition_context={"fed_state": "fasted"},
        previous_report={"summary": {"fatmax_power_w": 180.0, "mfo_g_min": 0.5}},
    )
    assert report["status"] == "success"
    assert report["summary"]["fatmax_power_w"] == round(280.0 * FATMAX_MLSS_RATIO, 1)
    assert report["mfo_is_model_proxy"] is True
    assert report["curve"]["carbohydrate_crossover"]["method"] == "model_proxy_fraction"
    assert report["shift"]["available"] is True
    assert report["influencing_factors"]["environment"]["available"] is True
    assert report["influencing_factors"]["nutrition"]["available"] is True


def test_model_fatmax_report_insufficient_without_mlss_or_fatmax() -> None:
    report = build_model_fatmax_report({"status": "success"}, athlete_weight_kg=72)
    assert report["status"] == "insufficient_data"
    assert report["reason"] == "fatmax_or_mlss_unavailable"


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
    assert "Base width increased" in shift["interpretation"]


def test_fatmax_compare_left_shift_and_narrowing() -> None:
    previous = {
        "summary": {"fatmax_power_w": 200.0, "mfo_g_min": 0.62},
        "curve": {"fatmax_base": {"width_w": 55.0}},
    }
    current = {
        "summary": {"fatmax_power_w": 185.0, "mfo_g_min": 0.55},
        "curve": {"fatmax_base": {"width_w": 38.0}},
    }
    shift = compare_fatmax_reports(previous, current).to_dict()
    assert shift["direction"] == "left_shift"
    assert "narrowed" in shift["interpretation"]


def test_fatmax_compare_stable_when_delta_small() -> None:
    previous = {"summary": {"fatmax_power_w": 180.0, "mfo_g_min": 0.50}}
    current = {"summary": {"fatmax_power_w": 184.0, "mfo_g_min": 0.52}}
    shift = compare_fatmax_reports(previous, current).to_dict()
    assert shift["direction"] == "stable"


def test_fatmax_compare_not_available_without_previous() -> None:
    shift = compare_fatmax_reports(None, {"summary": {"fatmax_power_w": 180.0}}).to_dict()
    assert shift["available"] is False
    assert shift["direction"] == "not_available"


def test_lab_fatmax_report_without_mlss_uses_absolute_width_interpretation() -> None:
    points = [
        GasExchangePoint(power_w=120, vo2_l_min=2.05, vco2_l_min=1.65),
        GasExchangePoint(power_w=160, vo2_l_min=2.45, vco2_l_min=1.95),
        GasExchangePoint(power_w=190, vo2_l_min=2.80, vco2_l_min=2.22),
        GasExchangePoint(power_w=230, vo2_l_min=3.20, vco2_l_min=2.75),
    ]
    report = build_lab_fatmax_report(points, athlete_weight_kg=72)
    base = report["curve"]["fatmax_base"]
    assert base["available"] is True
    assert "compare longitudinally" in base["interpretation"]


def test_lab_fatmax_report_rejects_when_too_many_invalid_gas_points() -> None:
    points = [
        GasExchangePoint(power_w=120, vo2_l_min=0.0, vco2_l_min=1.65),
        GasExchangePoint(power_w=160, vo2_l_min=0.0, vco2_l_min=1.95),
        GasExchangePoint(power_w=190, vo2_l_min=2.80, vco2_l_min=2.22),
    ]
    report = build_lab_fatmax_report(points, athlete_weight_kg=72, mlss_power_w=285)
    assert report["status"] == "insufficient_data"
    assert report["reason"] == "too_few_valid_gas_exchange_points"


def test_model_fatmax_report_derives_mlss_from_fatmax_only() -> None:
    snapshot = {
        "status": "success",
        "fatmax_power_watts": 204.0,
        "map_aerobic_watts": 360.0,
        "estimated_vo2max": 54.0,
    }
    report = build_model_fatmax_report(snapshot, athlete_weight_kg=68)
    assert report["status"] == "success"
    assert report["summary"]["mlss_power_w"] == round(204.0 / 0.68, 1)


def test_fatmax_compare_ignores_non_numeric_summary_values() -> None:
    shift = compare_fatmax_reports(
        {"summary": {"fatmax_power_w": "n/a"}},
        {"summary": {"fatmax_power_w": 180.0}},
    ).to_dict()
    assert shift["available"] is False


def test_lab_base_width_interpretation_scales_with_mlss() -> None:
    points = [
        GasExchangePoint(power_w=120, vo2_l_min=2.05, vco2_l_min=1.65),
        GasExchangePoint(power_w=160, vo2_l_min=2.45, vco2_l_min=1.95),
        GasExchangePoint(power_w=190, vo2_l_min=2.80, vco2_l_min=2.22),
        GasExchangePoint(power_w=230, vo2_l_min=3.20, vco2_l_min=2.75),
        GasExchangePoint(power_w=270, vo2_l_min=3.60, vco2_l_min=3.35),
    ]
    wide = build_lab_fatmax_report(points, athlete_weight_kg=72, mlss_power_w=200)
    interpretation = wide["curve"]["fatmax_base"]["interpretation"]
    assert "Wide base" in interpretation or "Moderate base" in interpretation


def test_fatmax_compare_handles_malformed_report_structures() -> None:
    shift = compare_fatmax_reports({"summary": "bad"}, {"summary": {"fatmax_power_w": 180.0}}).to_dict()
    assert shift["available"] is False
    shift2 = compare_fatmax_reports(
        {"summary": {"fatmax_power_w": 180.0}, "curve": "bad"},
        {"summary": {"fatmax_power_w": 190.0}, "curve": {"fatmax_base": {"width_w": 40.0}}},
    ).to_dict()
    assert shift2["available"] is True
    assert shift2["delta_base_width_w"] is None


def test_fatmax_compare_notes_base_narrowing_without_large_power_shift() -> None:
    previous = {
        "summary": {"fatmax_power_w": 180.0, "mfo_g_min": 0.50},
        "curve": {"fatmax_base": {"width_w": 52.0}},
    }
    current = {
        "summary": {"fatmax_power_w": 182.0, "mfo_g_min": 0.51},
        "curve": {"fatmax_base": {"width_w": 36.0}},
    }
    shift = compare_fatmax_reports(previous, current).to_dict()
    assert shift["direction"] == "stable"
    assert "narrowed" in shift["interpretation"]


def test_fatmax_compare_stable_with_width_notes() -> None:
    previous = {
        "summary": {"fatmax_power_w": 180.0, "mfo_g_min": 0.50},
        "curve": {"fatmax_base": {"width_w": 30.0}},
    }
    current = {
        "summary": {"fatmax_power_w": 182.0, "mfo_g_min": 0.52},
        "curve": {"fatmax_base": {"width_w": 45.0}},
    }
    shift = compare_fatmax_reports(previous, current).to_dict()
    assert shift["direction"] == "stable"
    assert "Base width increased" in shift["interpretation"]
