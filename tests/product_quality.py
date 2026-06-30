"""Product-quality assertions shared across API, chart, and engine gates."""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, Iterable, Optional

from api.chart_schemas import validate_chart_envelope
from tests.conftest import FORBIDDEN_ENGINE_STATUSES

# Lists the frontend iterates — must never contain null placeholders.
_NAMED_LIST_KEYS = frozenset({
    "series",
    "steps",
    "comparisons",
    "warnings",
    "chart_hints",
    "states",
    "segments",
    "pacing_plan",
})

SemanticValidator = Callable[[Dict[str, Any]], None]


def assert_finite_json_tree(value: Any, *, path: str = "root") -> None:
    """Reject NaN/Inf anywhere in a JSON tree (wire-unsafe values)."""
    if isinstance(value, float):
        assert math.isfinite(value), f"non-finite float at {path}"
        return
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            assert_finite_json_tree(item, path=child)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_finite_json_tree(item, path=f"{path}[{index}]")


def assert_no_null_in_named_lists(value: Any, *, path: str = "root") -> None:
    """Named list fields must not contain null entries (frontend iteration safety)."""
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if key in _NAMED_LIST_KEYS and isinstance(item, list):
                assert None not in item, f"null entry in {child}"
            assert_no_null_in_named_lists(item, path=child)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_null_in_named_lists(item, path=f"{path}[{index}]")


def assert_engine_success_body(body: Dict[str, Any], *, context: str = "") -> None:
    prefix = f"{context}: " if context else ""
    assert isinstance(body, dict) and body, f"{prefix}empty response body"
    status = body.get("status")
    if status is not None:
        status_str = str(status)
        assert status_str not in FORBIDDEN_ENGINE_STATUSES, f"{prefix}forbidden status {status_str!r}: {body}"


def _assert_readiness_score(body: Dict[str, Any]) -> None:
    score = body["readiness_score"]
    assert isinstance(score, int), "readiness_score must be int"
    assert 0 <= score <= 100


def _assert_twin_state(body: Dict[str, Any]) -> None:
    assert body.get("schema_version") == "twin_state.v1"


def _assert_chart_envelope(body: Dict[str, Any]) -> None:
    validate_chart_envelope(body)


def _assert_acwr(body: Dict[str, Any]) -> None:
    if body.get("status") == "success":
        assert isinstance(body.get("acwr"), (int, float))


def _assert_health(body: Dict[str, Any]) -> None:
    assert body.get("status") == "ok"
    assert body.get("version")


def _assert_dashboard(body: Dict[str, Any]) -> None:
    assert body.get("schema_version") == "dashboard_snapshot.v1"


def _assert_chart_types(body: Dict[str, Any]) -> None:
    assert body.get("total", 0) >= 1


SEMANTIC_BY_OPERATION: Dict[str, SemanticValidator] = {
    "healthCheck": _assert_health,
    "readinessToday": _assert_readiness_score,
    "twinStateBuild": _assert_twin_state,
    "twinStateValidate": _assert_twin_state,
    "twinStateUpdateFromRide": _assert_twin_state,
    "twinStateUpdateFromWorkout": _assert_twin_state,
    "metaChartConfig": _assert_chart_envelope,
    "loadAcwr": _assert_acwr,
    "dashboardAthleteSnapshot": _assert_dashboard,
    "metaChartTypes": _assert_chart_types,
}


def assert_product_response(
    body: Dict[str, Any],
    *,
    operation_id: str,
    allowed_statuses: Optional[Iterable[str]] = None,
) -> None:
    """Universal product gate for a successful API JSON body."""
    assert isinstance(body, dict) and body, f"{operation_id}: empty body"
    status = body.get("status")
    if status is not None:
        if allowed_statuses is not None:
            assert str(status) in frozenset(allowed_statuses), f"{operation_id}: status {status!r}"
        else:
            assert_engine_success_body(body, context=operation_id)
    assert_finite_json_tree(body, path=operation_id)
    assert_no_null_in_named_lists(body, path=operation_id)
    validator = SEMANTIC_BY_OPERATION.get(operation_id)
    if validator is not None:
        validator(body)
