"""Engine entry-point fixtures for product-quality gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, List

from tests.product_quality import assert_engine_success_body, assert_finite_json_tree, assert_no_null_in_named_lists

EngineCheck = Callable[[Dict[str, Any]], None]


def _check_readiness_score(body: Dict[str, Any]) -> None:
    assert 0 <= body["readiness_score"] <= 100


def _check_load_state(body: Dict[str, Any]) -> None:
    assert body["acute_load"] > 0


def _check_load_risk(body: Dict[str, Any]) -> None:
    assert body["risk"] in {"low", "moderate", "high", "detraining"}


def _check_acwr(body: Dict[str, Any]) -> None:
    assert body["status"] == "success" and body["acwr"] > 0


def _check_monotony(body: Dict[str, Any]) -> None:
    assert body["monotony"] is not None


def _check_eddington(body: Dict[str, Any]) -> None:
    assert body["eddington_number"] >= 1


def _check_twin(body: Dict[str, Any]) -> None:
    assert body.get("schema_version") == "twin_state.v1"


def _check_mmp_series(body: Dict[str, Any]) -> None:
    assert None not in body.get("series", []) and len(body["series"]) == 1


def _check_chart_type(expected: str) -> EngineCheck:
    def _inner(body: Dict[str, Any]) -> None:
        assert body["chart_type"] == expected

    return _inner


def _check_checkin(body: Dict[str, Any]) -> None:
    assert "psychological_support_flag" in body


def _check_constraints(body: Dict[str, Any]) -> None:
    assert "adaptation" in body


def _check_manual_load(body: Dict[str, Any]) -> None:
    assert body["load"]["training_load_equivalent"] > 0


@dataclass(frozen=True)
class EngineQualityCase:
    case_id: str
    runner: Callable[[], Dict[str, Any]]
    check: EngineCheck | None = None


def _run(case: EngineQualityCase) -> Dict[str, Any]:
    body = case.runner()
    assert_engine_success_body(body, context=case.case_id)
    assert_finite_json_tree(body, path=case.case_id)
    assert_no_null_in_named_lists(body, path=case.case_id)
    if case.check is not None:
        case.check(body)
    return body


def engine_quality_cases() -> List[EngineQualityCase]:
    from engines.io.chart_builder import chart_power_duration_curve
    from engines.io.chart_registry import build_chart_config
    from engines.performance.consistency_engine import calculate_eddington_number
    from engines.performance.training_variability_engine import calculate_acwr, calculate_monotony_strain
    from engines.readiness.readiness_engine import compute_load_risk, compute_readiness_today, update_load_state
    from engines.twin_state.models import build_twin_state
    from tests.chart_output_quality import minimal_chart_payloads

    load_state = {"acute_load": 55.0, "chronic_load": 48.0, "load_balance": -7.0}

    cases: List[EngineQualityCase] = [
        EngineQualityCase(
            "readiness_today_minimal",
            lambda: compute_readiness_today(load_state=load_state),
            _check_readiness_score,
        ),
        EngineQualityCase(
            "load_state_update",
            lambda: update_load_state(load_state, 65.0),
            _check_load_state,
        ),
        EngineQualityCase(
            "load_risk",
            lambda: compute_load_risk(load_state, planned_load=20.0),
            _check_load_risk,
        ),
        EngineQualityCase(
            "acwr",
            lambda: calculate_acwr(65.0, 50.0),
            _check_acwr,
        ),
        EngineQualityCase(
            "monotony_strain",
            lambda: calculate_monotony_strain([80, 65, 90, 75, 100, 60, 85]),
            _check_monotony,
        ),
        EngineQualityCase(
            "eddington",
            lambda: calculate_eddington_number([2.5, 3.0, 4.0, 5.0, 3.5, 4.5, 5.5]),
            _check_eddington,
        ),
        EngineQualityCase(
            "twin_state_build",
            lambda: build_twin_state({"athlete_id": "eq_1", "weight_kg": 72, "ftp_w": 250, "cp_w": 260}),
            _check_twin,
        ),
        EngineQualityCase(
            "chart_mmp_minimal_no_null_series",
            lambda: chart_power_duration_curve({60: 400, 300: 320, 1200: 280}),
            _check_mmp_series,
        ),
    ]

    for chart_type, payload in minimal_chart_payloads().items():
        cases.append(
            EngineQualityCase(
                f"chart_registry_{chart_type}",
                lambda ct=chart_type, pl=payload: build_chart_config(ct, pl),
                _check_chart_type(chart_type),
            )
        )

    from engines.coach.checkin_engine import process_checkin
    from engines.coach.constraints_engine import evaluate_constraints
    from engines.load.manual_load import calculate_manual_load

    cases.extend([
        EngineQualityCase(
            "coach_checkin",
            lambda: process_checkin(stress=5, motivation=7, perceived_fatigue=4),
            _check_checkin,
        ),
        EngineQualityCase(
            "coach_constraints",
            lambda: evaluate_constraints(constraints={"travel_week": False, "available_days": ["mon", "wed", "sat"]}),
            _check_constraints,
        ),
        EngineQualityCase(
            "manual_load",
            lambda: calculate_manual_load(duration_min=60, rpe=7),
            _check_manual_load,
        ),
    ])

    return cases


ENGINE_CASES = engine_quality_cases()
