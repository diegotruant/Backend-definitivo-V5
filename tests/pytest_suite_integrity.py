"""Meta-tests: the suite itself must not hide failures."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.conftest import EXPECTED_OPENAPI_PATH_COUNT, OPENAPI_JSON

TESTS_DIR = Path(__file__).resolve().parent


def _pytest_modules() -> list[Path]:
    return sorted(TESTS_DIR.glob("pytest_*.py"))


def test_no_xfail_markers_in_pytest_modules() -> None:
    violations: list[str] = []
    for path in _pytest_modules():
        text = path.read_text(encoding="utf-8")
        if re.search(r"@pytest\.mark\.xfail\b", text) or re.search(r"pytest\.mark\.xfail\(", text):
            violations.append(path.name)
    assert not violations, (
        "xfail masks real failures — fix the code or tighten the assertion instead:\n"
        + "\n".join(f"  - {name}" for name in violations)
    )


def test_no_bare_pass_in_except_handlers() -> None:
  """Bare ``except: pass`` in tests swallows regressions."""
  violations: list[str] = []
  for path in _pytest_modules():
      tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
      for node in ast.walk(tree):
          if not isinstance(node, ast.ExceptHandler):
              continue
          if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
              violations.append(f"{path.name}:{node.lineno}")
  assert not violations, (
      "replace bare except/pass with explicit expected exception or outcome:\n"
      + "\n".join(f"  - {item}" for item in violations)
  )


def test_openapi_path_count_is_exact_not_fuzzy() -> None:
    assert OPENAPI_JSON.is_file(), "run make openapi-frontend"
    assert EXPECTED_OPENAPI_PATH_COUNT == len(json_load_paths()), (
        "update tests/conftest.py by regenerating openapi/openapi.json"
    )
    # Guard against fuzzy >= 100 checks creeping back in contract tests.
    fuzzy = []
    for path in _pytest_modules():
        if path.name == "pytest_suite_integrity.py":
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"len\([^)]*paths[^)]*\)\s*>=\s*100", text):
            fuzzy.append(path.name)
    assert not fuzzy, (
        "use EXPECTED_OPENAPI_PATH_COUNT from tests.conftest instead of >= 100:\n"
        + "\n".join(f"  - {name}" for name in fuzzy)
    )


def json_load_paths() -> dict:
    import json

    return json.loads(OPENAPI_JSON.read_text(encoding="utf-8")).get("paths", {})
