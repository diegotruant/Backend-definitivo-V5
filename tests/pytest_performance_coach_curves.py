"""Coach-facing session performance curves."""

from __future__ import annotations

from engines.performance.performance_coach_curves import (
    build_durability_decay_curve,
    build_w_prime_balance_curve,
)


def test_w_prime_balance_curve_exposes_min_balance_anchor() -> None:
    power = [150.0] * 60 + [360.0] * 90 + [140.0] * 120 + [340.0] * 60
    curve = build_w_prime_balance_curve(power, cp_w=280, w_prime_j=18000, dt_s=1.0)
    assert curve["measurement_tier"] == "MODEL_ESTIMATE"
    assert curve["points"]
    assert curve["anchors"][0]["label"] == "Min W' balance"
    assert curve["summary"]["min_balance_pct"] < 100


def test_durability_decay_curve_uses_hourly_power() -> None:
    power = [220.0] * 3600 + [205.0] * 3600
    curve = build_durability_decay_curve(power, duration_s=len(power), ftp_w=280)
    assert curve["measurement_tier"] == "MODEL_ESTIMATE"
    assert len(curve["points"]) == 2
    assert curve["points"][0]["average_power_w"] > curve["points"][1]["average_power_w"]
    assert curve["anchors"][0]["label"] == "Decay rate"
