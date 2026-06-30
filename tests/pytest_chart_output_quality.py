"""Chart output quality gate — every registry type with minimal required payload."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api_app import app
from engines.io.chart_registry import get_chart_registry
from tests.chart_output_quality import build_and_validate_chart, minimal_chart_payloads
from tests.conftest import assert_http_engine_json

client = TestClient(app)

_PAYLOADS = minimal_chart_payloads()
_REGISTRY = get_chart_registry()
_ALL_CHART_TYPES = sorted(_REGISTRY.keys())


def test_minimal_payloads_cover_entire_registry() -> None:
    missing = set(_REGISTRY.keys()) - set(_PAYLOADS.keys())
    assert not missing, f"Add minimal payloads for: {sorted(missing)}"
    assert len(_PAYLOADS) == len(_REGISTRY)


@pytest.mark.parametrize("chart_type", _ALL_CHART_TYPES)
def test_chart_builds_with_minimal_payload(chart_type: str) -> None:
    build_and_validate_chart(chart_type, _PAYLOADS[chart_type])


@pytest.mark.parametrize("chart_type", _ALL_CHART_TYPES)
def test_meta_chart_config_http_minimal_payload(chart_type: str) -> None:
    response = client.post(
        "/meta/chart-config",
        json={"chart_type": chart_type, "payload": _PAYLOADS[chart_type]},
    )
    body = assert_http_engine_json(response)
    assert body["chart_type"] == chart_type
    assert body["config"]["type"]
