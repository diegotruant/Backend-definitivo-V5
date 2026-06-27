"""FATmax explainability and lab smoothing tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_app import app
from engines.metabolic.fatmax_engine import (
    GasExchangePoint,
    _smooth_lab_fat_curve,
    build_lab_fatmax_report,
)
from engines.recovery.explainability_engine import (
    ConfidenceLevel,
    calculate_fatmax_confidence,
    generate_fatmax_narrative,
)

client = TestClient(app)


def _lab_points() -> list[GasExchangePoint]:
    return [
        GasExchangePoint(power_w=120, vo2_l_min=2.05, vco2_l_min=1.65),
        GasExchangePoint(power_w=160, vo2_l_min=2.45, vco2_l_min=1.95),
        GasExchangePoint(power_w=190, vo2_l_min=2.80, vco2_l_min=2.22),
        GasExchangePoint(power_w=230, vo2_l_min=3.20, vco2_l_min=2.75),
        GasExchangePoint(power_w=270, vo2_l_min=3.60, vco2_l_min=3.35),
    ]


def test_smooth_lab_fat_curve_skips_when_too_few_points() -> None:
    curve = [{"power_w": 120.0, "fat_g_min": 0.5}]
    _, meta = _smooth_lab_fat_curve(curve)
    assert meta["applied"] is False


def test_fatmax_confidence_for_model_report_with_anchors() -> None:
    score = calculate_fatmax_confidence(
        {
            "status": "success",
            "measurement_tier": "MODEL_ESTIMATE",
            "confidence_score": 0.81,
            "mfo_is_model_proxy": True,
            "summary": {
                "fatmax_power_w": 188.0,
                "estimated_vo2max": 58.0,
                "estimated_vlamax_mmol_L_s": 0.44,
            },
            "warnings": [{"type": "rer_mismatch"}],
            "limitations": [],
        }
    )
    assert score.confidence_level in {ConfidenceLevel.HIGH, ConfidenceLevel.MODERATE}
    assert any("VO2max" in factor for factor in score.factors)
    assert any("warning" in lim.lower() for lim in score.limitations)


def test_fatmax_confidence_for_insufficient_report() -> None:
    score = calculate_fatmax_confidence({"measurement_tier": "INSUFFICIENT_DATA", "confidence_score": 0.0})
    assert score.confidence_level == ConfidenceLevel.VERY_LOW
    assert score.limitations


def test_fatmax_narrative_includes_longitudinal_shift_block() -> None:
    text = generate_fatmax_narrative(
        {
            "status": "success",
            "measurement_tier": "LAB_MEASURED",
            "confidence_score": 0.88,
            "summary": {"fatmax_power_w": 180.0, "mfo_g_min": 0.55, "mfo_tier": "measured_from_vo2_vco2"},
            "shift": {"available": True, "interpretation": "FATmax shifted toward higher power."},
            "limitations": [],
        }
    )
    assert "Longitudinal shift" in text


def test_lab_curve_smoothing_metadata_and_raw_values() -> None:
    report = build_lab_fatmax_report(_lab_points(), athlete_weight_kg=72, mlss_power_w=285)
    smoothing = report["curve"]["smoothing"]
    assert smoothing["applied"] is True
    assert smoothing["method"] == "centered_moving_average"
    points = report["curve"]["points"]
    assert all("fat_g_min_raw" in point for point in points)
    assert any(point["fat_g_min"] != point["fat_g_min_raw"] for point in points)


def test_fatmax_confidence_for_lab_report() -> None:
    report = build_lab_fatmax_report(_lab_points(), athlete_weight_kg=72, mlss_power_w=285)
    score = calculate_fatmax_confidence(report)
    assert score.metric_name == "FATmax"
    assert score.confidence_pct > 50
    assert any("gas-exchange" in factor.lower() for factor in score.factors)


def test_fatmax_narrative_for_model_report() -> None:
    report = {
        "status": "success",
        "measurement_tier": "MODEL_ESTIMATE",
        "confidence_score": 0.72,
        "mfo_is_model_proxy": True,
        "fatmax_interpretation": "Model estimate only.",
        "summary": {
            "fatmax_power_w": 185.0,
            "mfo_g_min": 0.58,
            "mfo_tier": "estimated_model_proxy_not_gas_exchange",
            "fatmax_pct_mlss": 0.66,
        },
        "curve": {
            "fatmax_base": {
                "available": True,
                "lower_w": 140.0,
                "upper_w": 210.0,
                "width_w": 70.0,
                "interpretation": "Wide base",
            },
            "carbohydrate_crossover": {
                "power_w": 230.0,
                "method": "model_proxy_fraction",
            },
        },
        "coach_interpretation": {
            "primary_goal": "maintain_or_right_shift",
            "message": "Shift FATmax upward while keeping base width.",
        },
        "limitations": ["MFO g/min is estimated."],
    }
    text = generate_fatmax_narrative(report)
    assert "FATmax Assessment" in text
    assert "MODEL_ESTIMATE" in text
    assert "model proxy" in text.lower() or "Model estimate" in text


def test_fatmax_narrative_endpoint() -> None:
    report = build_lab_fatmax_report(_lab_points(), athlete_weight_kg=72, mlss_power_w=285)
    response = client.post("/explainability/fatmax-narrative", json={"report": report})
    assert response.status_code == 200
    body = response.json()
    assert "narrative" in body
    assert "LAB_MEASURED" in body["narrative"]


def test_fatmax_confidence_endpoint() -> None:
    report = build_lab_fatmax_report(_lab_points(), athlete_weight_kg=72, mlss_power_w=285)
    response = client.post("/explainability/fatmax-confidence", json={"report": report})
    assert response.status_code == 200
    body = response.json()
    assert body["measurement_tier"] == "LAB_MEASURED"
    assert body["confidence_level"] in {"HIGH", "MODERATE", "VERY_HIGH"}


def test_fatmax_narrative_for_compare_shift() -> None:
    text = generate_fatmax_narrative(
        {
            "schema_version": "fatmax_shift.v1",
            "shift": {
                "available": True,
                "direction": "right_shift",
                "delta_fatmax_w": 12.0,
                "delta_mfo_g_min": 0.04,
                "delta_base_width_w": 8.0,
                "interpretation": "FATmax shifted toward higher power.",
            },
        }
    )
    assert "FATmax Comparison" in text
    assert "right_shift" in text
    assert "Δ MFO" in text


def test_fatmax_narrative_compare_unavailable() -> None:
    text = generate_fatmax_narrative({"schema_version": "fatmax_shift.v1", "shift": {"available": False}})
    assert "Comparison unavailable" in text


def test_fatmax_confidence_lab_with_three_steps_warns_about_coverage() -> None:
    report = build_lab_fatmax_report(
        [
            GasExchangePoint(power_w=120, vo2_l_min=2.05, vco2_l_min=1.65),
            GasExchangePoint(power_w=160, vo2_l_min=2.45, vco2_l_min=1.95),
            GasExchangePoint(power_w=190, vo2_l_min=2.80, vco2_l_min=2.22),
        ],
        athlete_weight_kg=72,
        mlss_power_w=285,
    )
    score = calculate_fatmax_confidence(report)
    assert any("3 valid" in limitation for limitation in score.limitations)


def test_fatmax_confidence_very_high_for_strong_lab_report() -> None:
    score = calculate_fatmax_confidence(build_lab_fatmax_report(_lab_points(), athlete_weight_kg=72, mlss_power_w=285))
    assert score.confidence_pct >= 80


def test_fatmax_narrative_uses_low_confidence_marker() -> None:
    text = generate_fatmax_narrative(
        {
            "status": "success",
            "measurement_tier": "MODEL_ESTIMATE",
            "confidence_score": 0.42,
            "summary": {"fatmax_power_w": 170.0, "mfo_g_min": 0.40, "mfo_tier": "estimated_model_proxy_not_gas_exchange"},
            "limitations": ["MFO g/min is estimated."],
        }
    )
    assert "FATmax Assessment" in text
    assert "Low" in text or "Very Low" in text


def test_fatmax_confidence_maps_high_scores() -> None:
    score = calculate_fatmax_confidence(
        {
            "status": "success",
            "measurement_tier": "LAB_MEASURED",
            "confidence_score": 0.92,
            "curve": {"points": [{"power_w": 1}, {"power_w": 2}, {"power_w": 3}, {"power_w": 4}, {"power_w": 5}]},
            "limitations": [],
        }
    )
    assert score.confidence_level.name in {"HIGH", "VERY_HIGH"}


def test_fatmax_narrative_for_failed_report() -> None:
    text = generate_fatmax_narrative({"status": "insufficient_data", "reason": "too_few_points"})
    assert "Unavailable" in text
    assert "too_few_points" in text
