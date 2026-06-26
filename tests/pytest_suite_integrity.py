"""Meta-tests: the suite itself must not hide failures."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.conftest import EXPECTED_OPENAPI_PATH_COUNT, OPENAPI_JSON

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent

LEGACY_FLAT_MODULES = frozenset(
    {
        "analysis",
        "athlete_context",
        "athlete_physiological_prior",
        "audit",
        "data_quality_engine",
        "metric_contracts",
        "tiers",
        "bayesian_profiler",
        "coggan_classifier",
        "cross_validation_engine",
        "detraining_engine",
        "lab_data",
        "lactate_validation_engine",
        "metabolic_current",
        "metabolic_flexibility_engine",
        "metabolic_kalman",
        "metabolic_profiler",
        "metabolic_profiler_phenotype",
        "zones_engine",
        "durability_engine",
        "efforts_analyzer",
        "interval_detector",
        "mader_durability",
        "mader_residual_mlp",
        "mmp_aggregator",
        "mmp_quality",
        "neural_ode",
        "power_engine",
        "race_prediction_engine",
        "test_protocols",
        "training_variability_engine",
        "w_prime_balance_engine",
        "cardiac_engine",
        "explainability_engine",
        "hrv_engine",
        "pedaling_balance",
        "thermal_engine",
        "activity_charts",
        "activity_intelligence",
        "fit_parser",
        "session_router",
        "workout_summary",
    }
)


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


def test_production_code_does_not_use_flat_legacy_imports() -> None:
    """Production code must import via engines.<subpackage> to work outside pytest."""
    violations: list[str] = []
    for root_name in ("api", "engines"):
        for path in sorted((ROOT / root_name).rglob("*.py")):
            rel = path.relative_to(ROOT)
            if rel.as_posix() == "engines/__init__.py":
                continue  # compatibility facade registers legacy aliases intentionally
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.module is None:
                    continue
                base_module = node.module.split(".", 1)[0]
                if base_module in LEGACY_FLAT_MODULES:
                    violations.append(f"{rel}:{node.lineno}: from {node.module} import ...")
    assert not violations, (
        "production code must use fully-qualified package imports, e.g. "
        "from engines.metabolic.metabolic_profiler_phenotype import ...:\n"
        + "\n".join(f"  - {item}" for item in violations)
    )


def json_load_paths() -> dict:
    import json

    return json.loads(OPENAPI_JSON.read_text(encoding="utf-8")).get("paths", {})
