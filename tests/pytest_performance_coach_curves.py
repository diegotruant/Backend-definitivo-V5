"""Coach-facing session performance curves."""

from __future__ import annotations

from engines.performance.performance_coach_curves import (
    build_durability_decay_curve,
    build_post_effort_recovery_curve,
    build_session_fuel_demand_curve,
    build_session_performance_curves,
    build_w_prime_balance_curve,
)


def test_w_prime_balance_curve_exposes_min_balance_anchor() -> None:
    power = [150.0] * 60 + [360.0] * 90 + [140.0] * 120 + [340.0] * 60
    curve = build_w_prime_balance_curve(power, cp_w=280, w_prime_j=18000, dt_s=1.0)
    assert curve["measurement_tier"] == "MODEL_ESTIMATE"
    assert curve["points"]
    assert curve["anchors"][0]["label"] == "Min W' balance"
    assert curve["summary"]["min_balance_pct"] < 100


def test_w_prime_balance_curve_requires_cp_and_w_prime() -> None:
    curve = build_w_prime_balance_curve([200.0] * 120, cp_w=None, w_prime_j=18000)
    assert curve["measurement_tier"] == "INSUFFICIENT_DATA"
    assert curve["points"] == []


def test_durability_decay_curve_uses_hourly_power() -> None:
    power = [220.0] * 3600 + [205.0] * 3600
    curve = build_durability_decay_curve(power, duration_s=len(power), ftp_w=280)
    assert curve["measurement_tier"] == "MODEL_ESTIMATE"
    assert len(curve["points"]) == 2
    assert curve["points"][0]["average_power_w"] > curve["points"][1]["average_power_w"]
    assert curve["points"][0]["pct_ftp"] > 0
    assert curve["anchors"][0]["label"] == "Decay rate"


def test_durability_decay_curve_requires_one_hour() -> None:
    curve = build_durability_decay_curve([200.0] * 600, duration_s=600, ftp_w=280)
    assert curve["measurement_tier"] == "INSUFFICIENT_DATA"
    assert curve["points"] == []


def test_session_fuel_demand_fallback_uses_ftp_anchor() -> None:
    power = [180.0] * 120 + [320.0] * 60
    curve = build_session_fuel_demand_curve(power, ftp_w=280, dt_s=1.0)
    assert curve["measurement_tier"] == "HEURISTIC"
    assert curve["summary"]["carbohydrate_g"] > 0
    assert curve["summary"]["anchor_power_w"] == 280.0
    assert curve["summary"]["time_above_90pct_anchor_s"] > 0


def test_post_effort_recovery_curve_estimates_hours() -> None:
    power = [180.0] * 300 + [330.0] * 60 + [150.0] * 240
    curve = build_post_effort_recovery_curve(
        power,
        cp_w=280,
        w_prime_j=18000,
        ftp_w=280,
        dt_s=1.0,
    )
    assert curve["measurement_tier"] == "HEURISTIC"
    assert curve["summary"]["estimated_recovery_hours"] >= 6
    assert curve["anchors"][0]["severity"] in {"low", "moderate", "high"}
    assert curve["points"][0]["recovery_pct"] == 0.0


def test_session_fuel_demand_fallback_requires_anchor() -> None:
    curve = build_session_fuel_demand_curve([200.0] * 120, ftp_w=None, cp_w=None)
    assert curve["measurement_tier"] == "INSUFFICIENT_DATA"
    assert curve["points"] == []


def test_post_effort_recovery_curve_handles_missing_cp_w_prime() -> None:
    curve = build_post_effort_recovery_curve([200.0] * 600, ftp_w=260, dt_s=1.0)
    assert curve["measurement_tier"] == "HEURISTIC"
    assert curve["summary"]["min_w_prime_balance_pct"] is None


def test_post_effort_recovery_severity_low_for_easy_session() -> None:
    curve = build_post_effort_recovery_curve([150.0] * 600, ftp_w=280)
    assert curve["anchors"][0]["severity"] == "low"


def test_post_effort_recovery_severity_high_for_long_hard_session() -> None:
    power = [280.0] * 7200
    curve = build_post_effort_recovery_curve(power, cp_w=280, w_prime_j=18000, ftp_w=280)
    assert curve["anchors"][0]["severity"] == "high"


def test_post_effort_recovery_severity_moderate_for_sustained_session() -> None:
    power = [240.0] * 3600
    curve = build_post_effort_recovery_curve(power, ftp_w=280)
    assert curve["anchors"][0]["severity"] == "moderate"


def test_post_effort_recovery_adds_penalty_when_w_prime_depleted() -> None:
    power = [150.0] * 60 + [400.0] * 120 + [150.0] * 60
    curve = build_post_effort_recovery_curve(
        power,
        cp_w=280,
        w_prime_j=5000,
        ftp_w=280,
    )
    assert curve["summary"]["min_w_prime_balance_pct"] is not None
    assert curve["summary"]["min_w_prime_balance_pct"] < 40
    assert curve["summary"]["estimated_recovery_hours"] >= 18


def test_build_session_performance_curves_bundle() -> None:
    power = [220.0] * 3600 + [205.0] * 3600
    curves = build_session_performance_curves(
        power_stream=power,
        cp_w=280,
        w_prime_j=18000,
        ftp_w=280,
        dt_s=1.0,
        duration_s=len(power),
    )
    assert curves["w_prime_balance"]["measurement_tier"] == "MODEL_ESTIMATE"
    assert curves["durability_decay"]["measurement_tier"] == "MODEL_ESTIMATE"
    assert curves["session_fuel_demand"]["summary"]["carbohydrate_g"] > 0
    assert curves["post_effort_recovery"]["summary"]["estimated_recovery_hours"] >= 6
