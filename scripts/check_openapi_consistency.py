#!/usr/bin/env python3
"""Fail when committed API documentation or generated TypeScript drifts from OpenAPI."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "openapi" / "openapi.json"
README_PATH = ROOT / "README.md"
API_INDEX_PATH = ROOT / "docs" / "API_ENDPOINT_INDEX.md"
TS_SCHEMA_PATH = ROOT / "frontend" / "src" / "api" / "generated" / "schema.ts"

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}

# Existing frontend codegen debt, tracked in GitHub issue #14. Any new drift still
# fails the gate. Once codegen adds this path, the stale exception also fails so
# this entry must be removed in the same PR.
KNOWN_TYPESCRIPT_MISSING_PATHS = {"/ride/full-bundle"}


def fail(message: str) -> NoReturn:
    print(f"OpenAPI consistency check failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_text(path: Path) -> str:
    if not path.is_file():
        fail(f"missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def load_openapi() -> dict[str, object]:
    try:
        payload = json.loads(read_text(OPENAPI_PATH))
    except json.JSONDecodeError as exc:
        fail(f"{OPENAPI_PATH.relative_to(ROOT)} is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        fail("OpenAPI root must be a JSON object")
    return payload


def extract_openapi_paths(schema: dict[str, object]) -> set[str]:
    raw_paths = schema.get("paths")
    if not isinstance(raw_paths, dict):
        fail("OpenAPI document does not contain a valid paths object")
    paths = {path for path in raw_paths if isinstance(path, str)}
    if len(paths) != len(raw_paths):
        fail("OpenAPI paths contains a non-string key")
    return paths


def extract_index_paths(text: str) -> set[str]:
    pattern = re.compile(
        r"^\|\s*(?:GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD|TRACE)\s*"
        r"\|\s*`([^`]+)`\s*\|",
        re.MULTILINE,
    )
    return set(pattern.findall(text))


def extract_typescript_paths(text: str) -> set[str]:
    pattern = re.compile(r'^\s{4}"(/[^"]+)": \{$', re.MULTILINE)
    return set(pattern.findall(text))


def check_documented_counts(path_count: int, readme: str, api_index: str) -> None:
    count_patterns = {
        "README OpenAPI paths": re.compile(r"(\d+)\s+OpenAPI paths?"),
        "README documented endpoints": re.compile(r"(\d+)\s+documented endpoints"),
        "README all endpoints": re.compile(r"All\s+(\d+)\s+endpoints"),
        "README OpenAPI endpoints": re.compile(r"(\d+)\s+OpenAPI endpoints"),
        "API index canonical inventory": re.compile(r"Canonical inventory of \*\*(\d+) HTTP paths\*\*"),
    }

    for label, pattern in count_patterns.items():
        source = api_index if label.startswith("API index") else readme
        matches = [int(value) for value in pattern.findall(source)]
        if not matches:
            fail(f"could not find {label}")
        wrong = sorted({value for value in matches if value != path_count})
        if wrong:
            fail(f"{label} reports {wrong}, but OpenAPI contains {path_count} paths")


def check_versions(schema: dict[str, object], readme: str, api_index: str) -> str:
    info = schema.get("info")
    version = info.get("version") if isinstance(info, dict) else None
    if not isinstance(version, str) or not version:
        fail("OpenAPI info.version is missing")

    readme_match = re.search(r"Current version:\s*\*\*([^*]+)\*\*", readme)
    index_match = re.search(r"^# API endpoint index — Digital Twin API ([^\s]+)", api_index, re.MULTILINE)
    if not readme_match:
        fail("README current version marker is missing")
    if not index_match:
        fail("API endpoint index version marker is missing")

    documented = {
        "README": readme_match.group(1).strip(),
        "API endpoint index": index_match.group(1).strip(),
    }
    mismatches = {name: value for name, value in documented.items() if value != version}
    if mismatches:
        fail(f"version mismatch against OpenAPI {version}: {mismatches}")
    return version


def compare_path_sets(label: str, expected: set[str], actual: set[str]) -> None:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"extra={extra}")
        fail(f"{label} path inventory differs from OpenAPI: {'; '.join(details)}")


def compare_typescript_paths(expected: set[str], actual: set[str]) -> None:
    missing = expected - actual
    extra = actual - expected
    unexpected_missing = sorted(missing - KNOWN_TYPESCRIPT_MISSING_PATHS)
    stale_exceptions = sorted(KNOWN_TYPESCRIPT_MISSING_PATHS - missing)

    if unexpected_missing or extra or stale_exceptions:
        details: list[str] = []
        if unexpected_missing:
            details.append(f"unexpected_missing={unexpected_missing}")
        if extra:
            details.append(f"extra={sorted(extra)}")
        if stale_exceptions:
            details.append(f"remove_resolved_exceptions={stale_exceptions}")
        fail(f"generated TypeScript schema path inventory differs from OpenAPI: {'; '.join(details)}")

    if missing:
        print(
            "OpenAPI consistency warning: known TypeScript codegen debt "
            f"tracked in issue #14: {sorted(missing)}",
            file=sys.stderr,
        )


def count_operations(schema: dict[str, object]) -> int:
    raw_paths = schema.get("paths")
    assert isinstance(raw_paths, dict)
    return sum(
        1
        for path_item in raw_paths.values()
        if isinstance(path_item, dict)
        for method in path_item
        if isinstance(method, str) and method.lower() in HTTP_METHODS
    )


def main() -> None:
    schema = load_openapi()
    openapi_paths = extract_openapi_paths(schema)
    readme = read_text(README_PATH)
    api_index = read_text(API_INDEX_PATH)
    ts_schema = read_text(TS_SCHEMA_PATH)

    check_documented_counts(len(openapi_paths), readme, api_index)
    version = check_versions(schema, readme, api_index)
    compare_path_sets("API endpoint index", openapi_paths, extract_index_paths(api_index))
    compare_typescript_paths(openapi_paths, extract_typescript_paths(ts_schema))

    print(
        "OpenAPI consistency check passed: "
        f"version={version}, paths={len(openapi_paths)}, operations={count_operations(schema)}"
    )


if __name__ == "__main__":
    main()
