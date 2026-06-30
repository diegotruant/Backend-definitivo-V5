"""API product-quality gate — every OpenAPI path with realistic minimal payload."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api_app import app
from tests.conftest import EXPECTED_OPENAPI_PATH_COUNT
from tests.openapi_matrix_support import (
    ApiOperation,
    iter_operations,
    json_payload_for_operation,
    load_openapi,
    multipart_request_for_operation,
)
from tests.product_quality import assert_product_response

client = TestClient(app)
OPERATIONS = iter_operations()


def _op_id(op: ApiOperation) -> str:
    return f"{op.method} {op.path}"


@pytest.fixture(scope="module")
def openapi_spec() -> dict:
    return load_openapi()


def test_product_quality_covers_all_documented_paths() -> None:
    assert len(OPERATIONS) == EXPECTED_OPENAPI_PATH_COUNT


@pytest.mark.parametrize("operation", OPERATIONS, ids=_op_id)
def test_api_product_quality_valid_payload(operation: ApiOperation, openapi_spec: dict) -> None:
    """Each documented endpoint must return 200 JSON that passes product invariants."""
    if operation.method == "GET":
        response = client.get(operation.path)
    elif operation.multipart_schema is not None:
        data, files = multipart_request_for_operation(operation)
        response = client.post(operation.path, data=data, files=files or None)
    elif operation.json_schema is not None:
        payload = json_payload_for_operation(operation, openapi_spec)
        response = client.request(operation.method, operation.path, json=payload)
    else:
        pytest.fail(f"no request strategy for {operation}")

    assert response.status_code == 200, (
        f"{operation.operation_id} returned {response.status_code}: {response.text[:500]}"
    )
    content_type = response.headers.get("content-type", "")
    assert "application/json" in content_type, f"{operation.operation_id}: expected JSON, got {content_type}"
    body = response.json()
    assert isinstance(body, dict), f"{operation.operation_id}: body must be object"
    assert_product_response(body, operation_id=operation.operation_id)
