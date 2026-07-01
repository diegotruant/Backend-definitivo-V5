"""Core scientific-verification gates for the stateless backend.

These tests intentionally focus on model behavior rather than transport, auth,
frontend generation, or persistence. They verify invariants that should remain
true across refactors: physiological monotonicity, bounded outputs, explicit
model metadata, and chart-envelope safety.
"""

from __future__ import annotations

import pytest

from api.chart_schemas import validate_chart_envelope
from engines.io.chart_registry import build_chart_config, get_chart_registry
from engines.performance.training_variability_engine import (
    calculate_acwr,
    calculate_monotony_strain,
)
from engines.readiness.readiness_engine import (
    compute_load_risk,
    compute_readiness_today,
    update_load_state,
)
from tests.chart_output_quality import minimal_chart_payloads
from tests.product_quality import assert_finite_json_tree, assert_no_null_in_named_lists


_STABLE_LOAD_STATE = {
    "acute_load": 48.0,
    "chronic_load": 55.0,
    "load_balance": 7.0,
    "ewma_tracking_started_at": "2026-04-01",
    "load_sessions_count": 12,
}

_HIGH_RISK_LOAD_STATE = {
    "acute_load": 95.0,
    "chronic_load": 55.0,
    "load_balance": -40.0,
    "ewma_tracking_started_at": "2026-04-01",
    "load_sessions_count": 12,
}


@pytest.mark.parametrize("session_load", [0.0, 25.0, 75.0, 150.0])
def test_load_state_update_is_bounded_and_explicit(session_load: float) -> None:
    """EWMA load updates must remain finite, non-negative, and self-describing."""
    body = update_load_state(_STABLE_LOAD_STATE, session_load)

    assert body["status"] == "success"
    assert body["acute_load"] >= 0
    assert body["chronic_load"] >= 0
    assert body["session_load"] == session_load
    assert body["ewma_trust_level"] in {"cold", "warming", "stable"}
    assert_finite_json_tree(body, path="load_state_update")
    assert_no_null_in_named_lists(body, path="load_state_update")


def test_readiness_decreases_when_recovery_signals_worsen() -> None:
    """Worse HRV/sleep/subjective inputs should not improve readiness."""
    good = compute_readiness_today(
        load_state=_STABLE_LOAD_STATE,
        hrv_status={"score": 0.9},
        sleep_status={"score": 0.9},
        subjective={"score": 0.9},
    )
    poor = compute_readiness_today(
        load_state=_STABLE_LOAD_STATE,
        hrv_status={"score": 0.25},
        sleep_status={"score": 0.35},
        subjective={"score": 0.3},
    )

    assert good["readiness_score"] > poor["readiness_score"]
    assert good["components"]["hrv"] > poor["components"]["hrv"]
    assert good["components"]["sleep"] > poor["components"]["sleep"]
    assert good["components"]["subjective"] > poor["components"]["subjective"]


@pytest.mark.parametrize(
    "load_state, expected_risk",
    [
        (_STABLE_LOAD_STATE, "low"),
        (_HIGH_RISK_LOAD_STATE, "high"),
    ],
)
def test_load_risk_matches_physiological_load_ratio(load_state: dict, expected_risk: str) -> None:
    body = compute_load_risk(load_state)

    assert body["status"] == "success"
    assert body["risk"] == expected_risk
    assert 0 < body["acute_chronic_ratio"] < 10
    assert body["model_metadata"]["confidence_score"] > 0
    assert_finite_json_tree(body, path="load_risk")


def test_high_load_risk_penalizes_readiness_and_adds_warning() -> None:
    normal = compute_readiness_today(load_state=_STABLE_LOAD_STATE)
    overloaded = compute_readiness_today(load_state=_HIGH_RISK_LOAD_STATE)

    assert overloaded["load_risk"] == "high"
    assert "high_load_risk" in overloaded["warnings"]
    assert overloaded["readiness_score"] < normal["readiness_score"]


def test_acwr_is_monotonic_with_acute_load_when_chronic_load_is_fixed() -> None:
    low = calculate_acwr(atl=40.0, ctl=60.0)
    high = calculate_acwr(atl=90.0, ctl=60.0)

    assert low["status"] == "success"
    assert high["status"] == "success"
    assert low["acwr"] < high["acwr"]
    assert low["risk_level"] != high["risk_level"] or high["acwr"] >= 1.0
    assert_finite_json_tree(low, path="acwr_low")
    assert_finite_json_tree(high, path="acwr_high")


def test_monotony_strain_increases_with_less_variable_training_load() -> None:
    variable_week = calculate_monotony_strain([30, 95, 20, 110, 35, 100, 25])
    monotonous_week = calculate_monotony_strain([70, 72, 71, 70, 73, 71, 72])

    assert variable_week["status"] == "success"
    assert monotonous_week["status"] == "success"
    assert monotonous_week["monotony"] > variable_week["monotony"]
    assert monotonous_week["strain"] > 0
    assert_finite_json_tree(variable_week, path="monotony_variable")
    assert_finite_json_tree(monotonous_week, path="monotony_stable")


@pytest.mark.parametrize("chart_type", sorted(get_chart_registry().keys()))
def test_every_chart_config_has_safe_contract_metadata(chart_type: str) -> None:
    """Every chart builder must return a valid, finite, non-null chart envelope."""
    payloads = minimal_chart_payloads()
    assert chart_type in payloads, f"missing minimal scientific fixture for chart {chart_type}"

    body = build_chart_config(chart_type, payloads[chart_type])
    validated = validate_chart_envelope(body)

    assert validated["status"] == "success"
    assert validated["chart_type"] == chart_type
    assert validated["config"]["schema_version"] == "chart_config.v1"
    assert validated["config"].get("series", []) is not None
    assert_finite_json_tree(validated, path=f"chart.{chart_type}")
    assert_no_null_in_named_lists(validated, path=f"chart.{chart_type}")
