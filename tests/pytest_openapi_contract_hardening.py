"""Phase 2 contract hardening — success on valid curated payloads, 4xx on semantic garbage."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api_app import app
from tests.conftest import assert_http_engine_json
from tests.openapi_matrix_support import (
    CURATED_ALLOWED_STATUSES,
    RESPONSE_CONTRACTS,
    STRICT_SUCCESS_OPERATIONS,
    iter_operations,
    json_payload_for_operation,
    load_openapi,
)

client = TestClient(app)
SPEC = load_openapi()


@pytest.mark.parametrize("operation_id", sorted(STRICT_SUCCESS_OPERATIONS))
def test_curated_payload_returns_allowed_status(operation_id: str) -> None:
    operation = next(op for op in iter_operations(SPEC) if op.operation_id == operation_id)
    assert operation.json_schema is not None, operation_id
    payload = json_payload_for_operation(operation, SPEC)
    response = client.request(operation.method, operation.path, json=payload)
    assert response.status_code == 200, response.text
    allowed = CURATED_ALLOWED_STATUSES.get(operation_id, frozenset({"success"}))
    assert_http_engine_json(response, allowed_statuses=allowed)


@pytest.mark.parametrize("operation_id", sorted(RESPONSE_CONTRACTS.keys()))
def test_response_contract_required_keys(operation_id: str) -> None:
    operation = next(op for op in iter_operations(SPEC) if op.operation_id == operation_id)
    payload = json_payload_for_operation(operation, SPEC)
    response = client.request(operation.method, operation.path, json=payload)
    allowed = CURATED_ALLOWED_STATUSES.get(operation_id, frozenset({"success", "partial"}))
    body = assert_http_engine_json(response, allowed_statuses=allowed)
    missing = [key for key in RESPONSE_CONTRACTS[operation_id] if key not in body]
    assert not missing, (operation_id, missing, list(body.keys())[:20])
