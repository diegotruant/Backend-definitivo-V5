from __future__ import annotations

import ast
from pathlib import Path

import pytest

from engines.io.data_quality_report import _quality_flags, _series_quality
from engines.io.fit_parse_report import _series_or_none


class _ArrayFailure:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def __array__(self, *args: object, **kwargs: object) -> object:
        raise self.error


@pytest.mark.parametrize("error", [TypeError("bad type"), ValueError("bad value"), OverflowError()])
def test_fit_parse_report_degrades_expected_conversion_errors(error: BaseException) -> None:
    assert _series_or_none(_ArrayFailure(error), n_samples=10) is None


def test_fit_parse_report_does_not_hide_system_errors() -> None:
    with pytest.raises(MemoryError):
        _series_or_none(_ArrayFailure(MemoryError()), n_samples=10)


@pytest.mark.parametrize("error", [TypeError("bad type"), ValueError("bad value"), OverflowError()])
def test_data_quality_degrades_expected_conversion_errors(error: BaseException) -> None:
    result = _series_quality(_ArrayFailure(error), measured=True)
    assert result["available"] is False
    assert result["notes"] == ["unreadable_signal"]
    assert _quality_flags(_ArrayFailure(error)) == {"available": False}


def test_data_quality_does_not_hide_system_errors() -> None:
    with pytest.raises(MemoryError):
        _series_quality(_ArrayFailure(MemoryError()), measured=True)
    with pytest.raises(MemoryError):
        _quality_flags(_ArrayFailure(MemoryError()))


def test_fit_reporting_modules_have_no_broad_exception_handlers() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative_path in (
        "engines/io/fit_parse_report.py",
        "engines/io/data_quality_report.py",
    ):
        tree = ast.parse((root / relative_path).read_text(encoding="utf-8"))
        broad_handlers = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler)
            and isinstance(node.type, ast.Name)
            and node.type.id in {"Exception", "BaseException"}
        ]
        assert not broad_handlers, f"broad exception handler found in {relative_path}"
