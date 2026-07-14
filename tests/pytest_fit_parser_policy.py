"""Contract tests for the canonical FIT parser policy."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

from engines.io import fit_parser


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PARSER = ROOT / "engines" / "io" / "fit_parser.py"
POLICY = ROOT / "docs" / "FIT_PARSER_POLICY.md"


def _runtime_dependencies() -> list[str]:
    payload = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return list(payload["project"]["dependencies"])


def _function_source(name: str) -> str:
    source = PARSER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    body = ast.get_source_segment(source, function)
    assert body is not None
    return body


def test_fitdecode_is_the_runtime_parser_dependency() -> None:
    dependencies = _runtime_dependencies()
    assert any(dep.startswith("fitdecode") for dep in dependencies)


def test_fitparse_remains_only_as_the_temporary_runtime_fallback() -> None:
    dependencies = _runtime_dependencies()
    assert any(dep.startswith("fitparse") for dep in dependencies)

    policy = POLICY.read_text(encoding="utf-8").lower()
    assert "fitparse" in policy
    assert "fallback legacy" in policy
    assert "temporaneamente" in policy


def test_backend_capability_flags_have_distinct_semantics() -> None:
    assert fit_parser.FITPARSE_FALLBACK_AVAILABLE is fit_parser.FITPARSE_AVAILABLE
    assert fit_parser.FIT_PARSER_AVAILABLE is (
        fit_parser.FITDECODE_AVAILABLE or fit_parser.FITPARSE_FALLBACK_AVAILABLE
    )
    assert fit_parser.FIT_BACKEND_AVAILABLE is fit_parser.FIT_PARSER_AVAILABLE


def test_fitparse_boundary_checks_real_fallback_availability_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fit_parser, "FITPARSE_FALLBACK_AVAILABLE", False)

    with pytest.raises(RuntimeError, match="fitparse fallback backend is not available"):
        fit_parser._extract_messages_with_fitparse(b"not-a-fit", check_crc=True)


def test_extract_messages_prefers_fitdecode_before_fitparse() -> None:
    body = _function_source("_extract_messages")

    fitdecode_call = body.index("_extract_messages_with_fitdecode")
    fitparse_call = body.index("_extract_messages_with_fitparse")
    assert fitdecode_call < fitparse_call
    assert "FITDECODE_AVAILABLE" in body
    assert "FITPARSE_FALLBACK_AVAILABLE" in body
    assert "FITPARSE_AVAILABLE" not in body


def test_public_parser_guard_uses_general_parser_availability() -> None:
    body = _function_source("parse_fit_file_enhanced")
    assert "FIT_PARSER_AVAILABLE" in body
    assert "if not FIT_BACKEND_AVAILABLE" not in body


def test_policy_declares_fitdecode_canonical_and_go_non_official() -> None:
    policy = POLICY.read_text(encoding="utf-8").lower()
    assert "fitdecode" in policy
    assert "parser fit canonico" in policy
    assert "fitparse_fallback_available" in policy
    assert "fit_parser_available" in policy
    assert "non è previsto un parser fit go nel percorso ufficiale" in policy
