"""Contract tests for the canonical FIT parser policy."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PARSER = ROOT / "engines" / "io" / "fit_parser.py"
POLICY = ROOT / "docs" / "FIT_PARSER_POLICY.md"


def _runtime_dependencies() -> list[str]:
    payload = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return list(payload["project"]["dependencies"])


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


def test_extract_messages_prefers_fitdecode_before_fitparse() -> None:
    source = PARSER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_extract_messages"
    )
    body = ast.get_source_segment(source, function)
    assert body is not None

    fitdecode_call = body.index("_extract_messages_with_fitdecode")
    fitparse_call = body.index("_extract_messages_with_fitparse")
    assert fitdecode_call < fitparse_call
    assert "FITDECODE_AVAILABLE" in body


def test_policy_declares_fitdecode_canonical_and_go_non_official() -> None:
    policy = POLICY.read_text(encoding="utf-8").lower()
    assert "fitdecode" in policy
    assert "parser fit canonico" in policy
    assert "non è previsto un parser fit go nel percorso ufficiale" in policy
