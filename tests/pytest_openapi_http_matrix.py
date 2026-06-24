"""Full OpenAPI HTTP matrix — every documented path must not 500."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api_app import app
from tests._hardening_utils import assert_json_safe
from tests.conftest import EXPECTED_OPENAPI_PATH_COUNT, assert_http_json
from tests.openapi_matrix_support import (
    ApiOperation,
    invalid_json_payload,
    iter_operations,
    json_payload_for_operation,
    load_openapi,
    multipart_request_for_operation,
)

client = TestClient(app)

OPERATIONS = iter_operations()


def _op_id(op: ApiOperation) -> str:
    return f"{op.method} {op.path}"


@pytest.fixture(scope="module")
def openapi_spec() -> dict:
    return load_openapi()


def test_openapi_matrix_covers_all_documented_paths() -> None:
    assert len(OPERATIONS) == EXPECTED_OPENAPI_PATH_COUNT


@pytest.mark.parametrize("operation", OPERATIONS, ids=_op_id)
def test_openapi_matrix_valid_request_never_returns_500(
    operation: ApiOperation,
    openapi_spec: dict,
) -> None:
    if operation.method == "GET":
        response = client.get(operation.path)
    elif operation.multipart_schema is not None:
        data, files = multipart_request_for_operation(operation)
        response = client.post(operation.path, data=data, files=files or None)
    elif operation.json_schema is not None:
        payload = json_payload_for_operation(operation, openapi_spec)
        response = client.request(operation.method, operation.path, json=payload)
    else:
        pytest.fail(f"operation has no request strategy: {operation}")

    assert response.status_code != 500, response.text
    assert response.status_code < 600, (operation.path, response.status_code, response.text)

    if response.status_code == 200:
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            assert_http_json(response)
        else:
            assert response.content, f"empty 200 body for {operation.path}"


@pytest.mark.parametrize(
    "operation",
    [op for op in OPERATIONS if op.json_schema is not None],
    ids=_op_id,
)
def test_openapi_matrix_invalid_json_never_returns_500(
    operation: ApiOperation,
) -> None:
    """Malformed/minimal JSON must not crash the server; 4xx is preferred but 200 is allowed."""
    payload = invalid_json_payload(operation)
    response = client.request(operation.method, operation.path, json=payload)
    assert response.status_code != 500, response.text
    assert response.status_code < 600, (
        operation.path,
        response.status_code,
        response.text,
    )
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        assert_json_safe(response.json())
    elif response.status_code == 200:
        assert response.content, f"empty 200 body for {operation.path}"
