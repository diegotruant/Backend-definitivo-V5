"""OpenAPI contract drift checks — committed spec must match live FastAPI export."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api_app import app

ROOT = Path(__file__).resolve().parents[1]
COMMITTED_SPEC = ROOT / "openapi" / "openapi.json"

client = TestClient(app)


def _path_methods(spec: dict) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path, item in spec.get("paths", {}).items():
        out[path] = {m.lower() for m in item if m in {"get", "post", "put", "patch", "delete"}}
    return out


@pytest.fixture(scope="module")
def live_openapi() -> dict:
    return app.openapi()


@pytest.fixture(scope="module")
def committed_openapi() -> dict:
    assert COMMITTED_SPEC.is_file(), "openapi/openapi.json missing — run make openapi"
    return json.loads(COMMITTED_SPEC.read_text(encoding="utf-8"))


def test_committed_openapi_paths_match_live_export(
    live_openapi: dict, committed_openapi: dict
) -> None:
    live_paths = _path_methods(live_openapi)
    committed_paths = _path_methods(committed_openapi)
    assert live_paths == committed_paths, (
        "OpenAPI drift: run `make openapi-frontend` and commit openapi/openapi.json"
    )


def test_openapi_documents_all_public_routes(live_openapi: dict) -> None:
    assert len(live_openapi.get("paths", {})) == 24
    assert "/health" in live_openapi["paths"]
    assert "/twin/state/build" in live_openapi["paths"]
    assert "/test/in-person" in live_openapi["paths"]


def test_live_openapi_endpoint_matches_committed(live_openapi: dict) -> None:
    """Runtime GET /openapi.json must equal the exported document."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    runtime_paths = _path_methods(resp.json())
    assert runtime_paths == _path_methods(live_openapi)


def test_key_request_schemas_are_present(committed_openapi: dict) -> None:
    schemas = committed_openapi.get("components", {}).get("schemas", {})
    required = {
        "TwinStateBuildRequest",
        "TwinStateDocument",
        "WorkoutDefinitionInput",
        "InPersonTestRequest",
        "PowerSourceNormalizationRequest",
        "SeasonProjectionRequest",
    }
    missing = required - set(schemas)
    assert not missing, f"Missing OpenAPI schemas: {sorted(missing)}"


def test_operation_ids_are_unique(committed_openapi: dict) -> None:
    seen: set[str] = set()
    for path_item in committed_openapi.get("paths", {}).values():
        for method, op in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            op_id = op.get("operationId")
            assert op_id, f"Missing operationId on {method}"
            assert op_id not in seen, f"Duplicate operationId: {op_id}"
            seen.add(op_id)


def test_frontend_codegen_hints_in_spec(committed_openapi: dict) -> None:
    info = committed_openapi.get("info", {})
    codegen = info.get("x-codegen", {})
    env_vars = codegen.get("frontend_env_vars", [])
    assert "VITE_API_BASE_URL" in env_vars
    assert "NEXT_PUBLIC_API_BASE_URL" in env_vars


def test_export_script_regenerates_identical_spec() -> None:
    """scripts/export_openapi.py must be idempotent."""
    before = COMMITTED_SPEC.read_text(encoding="utf-8")
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_openapi.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    after = COMMITTED_SPEC.read_text(encoding="utf-8")
    # Normalise trailing newline only
    assert before.rstrip() == after.rstrip()
