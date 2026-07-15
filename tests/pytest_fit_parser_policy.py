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


def _parser_tree() -> ast.Module:
    return ast.parse(PARSER.read_text(encoding="utf-8"))


def _function_source(name: str) -> str:
    source = PARSER.read_text(encoding="utf-8")
    function = next(
        node
        for node in _parser_tree().body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    body = ast.get_source_segment(source, function)
    assert body is not None
    return body


def _generic_exception_handler_functions() -> list[str]:
    functions: list[str] = []
    for node in _parser_tree().body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.ExceptHandler):
                continue
            if isinstance(child.type, ast.Name) and child.type.id == "Exception":
                functions.append(node.name)
    return functions


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

    with pytest.raises(RuntimeError, match="fitparse backend is not available"):
        fit_parser._extract_messages_with_fitparse(b"not-a-fit", check_crc=True)


def test_extract_messages_prefers_fitdecode_before_fitparse() -> None:
    body = _function_source("_extract_messages")

    fitdecode_call = body.index("_extract_messages_with_fitdecode")
    fitparse_call = body.index("_extract_messages_with_fitparse")
    assert fitdecode_call < fitparse_call
    assert "FITDECODE_AVAILABLE" in body
    assert "FITPARSE_FALLBACK_AVAILABLE" in body
    assert "FITPARSE_AVAILABLE" in body
    assert "_run_decoder_boundary" in body


def test_public_parser_guard_uses_general_parser_availability() -> None:
    body = _function_source("parse_fit_file_enhanced")
    assert "FIT_PARSER_AVAILABLE" in body
    assert "FIT_BACKEND_AVAILABLE" in body


def test_only_decoder_boundary_has_a_generic_exception_catch() -> None:
    assert _generic_exception_handler_functions() == ["_run_decoder_boundary"]


def test_public_parser_consumes_only_typed_decoder_errors() -> None:
    body = _function_source("parse_fit_file_enhanced")
    assert "FitDecoderError" in body
    assert "_run_decoder_boundary" in body
    assert "except Exception" not in body
    assert "FitParseHeaderError" not in body
    assert "FitParseEOFError" not in body
    assert "FitParseCRCError" not in body
    assert "FitParseLibError" not in body


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (RuntimeError("not a FIT file"), "INVALID_HEADER"),
        (fit_parser.FitParseEOFError(), "TRUNCATED"),
        (fit_parser.FitParseCRCError(), "CRC_MISMATCH"),
        (fit_parser.FitParseLibError("bad record stream"), "MALFORMED_RECORDS"),
        (RuntimeError("undocumented decoder failure"), "UNKNOWN"),
    ],
)
def test_decoder_exception_reason_mapping(error: Exception, reason: str) -> None:
    typed = fit_parser._decoder_error_from_exception(error, backend="test")
    assert typed.reason == reason
    assert typed.backend == "test"
    assert typed.detail == str(error)


@pytest.mark.parametrize(
    "fatal_error",
    [MemoryError("oom"), RecursionError("deep")],
)
def test_decoder_boundary_does_not_hide_fatal_errors(
    fatal_error: Exception,
) -> None:
    def _explode(_payload: bytes, *, check_crc: bool):
        raise fatal_error

    with pytest.raises(type(fatal_error)):
        fit_parser._run_decoder_boundary(
            _explode,
            b"payload",
            check_crc=True,
            backend="fitdecode",
        )


def test_unknown_fitdecode_error_is_typed_when_no_fallback_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(_payload: bytes, *, check_crc: bool):
        raise RuntimeError("undocumented fitdecode failure")

    monkeypatch.setattr(fit_parser, "FITDECODE_AVAILABLE", True)
    monkeypatch.setattr(fit_parser, "FITPARSE_FALLBACK_AVAILABLE", False)
    monkeypatch.setattr(fit_parser, "FITPARSE_AVAILABLE", False)
    monkeypatch.setattr(fit_parser, "_extract_messages_with_fitdecode", _explode)

    with pytest.raises(fit_parser.FitDecoderError) as exc:
        fit_parser._extract_messages(b"payload", check_crc=True)

    assert exc.value.backend == "fitdecode"
    assert exc.value.reason == "UNKNOWN"
    assert isinstance(exc.value.__cause__, RuntimeError)


def test_unknown_fitdecode_error_does_not_use_the_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def _explode(_payload: bytes, *, check_crc: bool):
        calls.append("fitdecode")
        raise RuntimeError("undocumented fitdecode failure")

    def _fallback(_payload: bytes, *, check_crc: bool):
        calls.append("fitparse")
        return ([{"power": 250}], [], [], [], [])

    monkeypatch.setattr(fit_parser, "FITDECODE_AVAILABLE", True)
    monkeypatch.setattr(fit_parser, "FITPARSE_FALLBACK_AVAILABLE", True)
    monkeypatch.setattr(fit_parser, "FITPARSE_AVAILABLE", True)
    monkeypatch.setattr(fit_parser, "_extract_messages_with_fitdecode", _explode)
    monkeypatch.setattr(fit_parser, "_extract_messages_with_fitparse", _fallback)

    with pytest.raises(fit_parser.FitDecoderError) as exc:
        fit_parser._extract_messages(b"payload", check_crc=True)

    assert exc.value.backend == "fitdecode"
    assert exc.value.reason == "UNKNOWN"
    assert calls == ["fitdecode"]


def test_fallback_error_is_also_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _primary(_payload: bytes, *, check_crc: bool):
        raise fit_parser.FitParseError("primary parse failure")

    def _fallback(_payload: bytes, *, check_crc: bool):
        raise ValueError("undocumented fallback failure")

    monkeypatch.setattr(fit_parser, "FITDECODE_AVAILABLE", True)
    monkeypatch.setattr(fit_parser, "FITPARSE_FALLBACK_AVAILABLE", True)
    monkeypatch.setattr(fit_parser, "FITPARSE_AVAILABLE", True)
    monkeypatch.setattr(fit_parser, "_extract_messages_with_fitdecode", _primary)
    monkeypatch.setattr(fit_parser, "_extract_messages_with_fitparse", _fallback)

    with pytest.raises(fit_parser.FitDecoderError) as exc:
        fit_parser._extract_messages(b"payload", check_crc=True)

    assert exc.value.backend == "fitparse"
    assert exc.value.reason == "UNKNOWN"
    assert isinstance(exc.value.__cause__, ValueError)


def test_policy_declares_fitdecode_canonical_and_go_non_official() -> None:
    policy = POLICY.read_text(encoding="utf-8").lower()
    assert "fitdecode" in policy
    assert "parser fit canonico" in policy
    assert "fitparse_fallback_available" in policy
    assert "fit_parser_available" in policy
    assert "fitdecodererror" in policy
    assert "_run_decoder_boundary" in policy
    assert "unico `except exception`" in policy
    assert "non è previsto un parser fit go nel percorso ufficiale" in policy
