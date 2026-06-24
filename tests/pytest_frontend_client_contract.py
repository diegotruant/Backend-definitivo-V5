"""Frontend client ↔ OpenAPI alignment checks (no Node runtime required)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.conftest import EXPECTED_OPENAPI_PATH_COUNT

ROOT = Path(__file__).resolve().parents[1]
CLIENT_TS = ROOT / "frontend" / "src" / "api" / "client.ts"
GENERATED_TS = ROOT / "frontend" / "src" / "api" / "generated" / "schema.ts"
OPENAPI_JSON = ROOT / "openapi" / "openapi.json"


def _extract_client_paths(source: str) -> set[str]:
    return set(re.findall(r"jsonFetch<[^>]*>\(\s*['\"]([^'\"]+)['\"]", source))


def _extract_documented_paths(source: str) -> set[str]:
    return set(re.findall(r"/\*\*\s+(?:GET|POST|PUT|DELETE)\s+(/[^\s*]+)", source))


@pytest.fixture(scope="module")
def openapi_paths() -> set[str]:
    spec = json.loads(OPENAPI_JSON.read_text(encoding="utf-8"))
    return set(spec.get("paths", {}))


@pytest.fixture(scope="module")
def client_source() -> str:
    assert CLIENT_TS.is_file()
    return CLIENT_TS.read_text(encoding="utf-8")


def test_generated_schema_file_exists() -> None:
    assert GENERATED_TS.is_file(), "Run make openapi-frontend"
    text = GENERATED_TS.read_text(encoding="utf-8")
    assert "components" in text or "export interface components" in text


def test_client_exports_key_request_types(client_source: str) -> None:
    for type_name in (
        "TwinStateBuildRequest",
        "InPersonTestRequest",
        "WorkoutValidateRequest",
        "PowerSourceNormalizationRequest",
        "SeasonProjectionRequest",
    ):
        assert f"components['schemas']['{type_name}']" in client_source


def test_client_paths_are_subset_of_openapi(client_source: str, openapi_paths: set[str]) -> None:
    client_paths = _extract_client_paths(client_source)
    assert client_paths, "No jsonFetch paths found in client.ts"
    missing = client_paths - openapi_paths
    assert not missing, f"client.ts paths missing from OpenAPI: {sorted(missing)}"


def test_openapi_paths_are_covered_by_client(client_source: str, openapi_paths: set[str]) -> None:
    client_paths = _extract_client_paths(client_source)
    # Every OpenAPI path must appear in client (health included)
    uncovered = openapi_paths - client_paths
    assert not uncovered, f"OpenAPI paths not in client.ts: {sorted(uncovered)}"


def test_client_documents_all_endpoints(client_source: str, openapi_paths: set[str]) -> None:
    documented = _extract_documented_paths(client_source)
    assert documented == openapi_paths


def test_client_supports_next_and_vite_env_vars(client_source: str) -> None:
    assert "VITE_API_BASE_URL" in client_source
    assert "NEXT_PUBLIC_API_BASE_URL" in client_source


def test_client_exports_api_error_class(client_source: str) -> None:
    assert "export class ApiError" in client_source


def test_client_method_count_matches_openapi_post_get_count(
    client_source: str, openapi_paths: set[str]
) -> None:
    # One jsonFetch call per HTTP operation in client
    fetch_paths = _extract_client_paths(client_source)
    assert len(fetch_paths) == len(openapi_paths) == EXPECTED_OPENAPI_PATH_COUNT
