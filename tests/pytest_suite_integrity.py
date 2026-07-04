"""Meta-tests: the suite itself must not hide failures."""

from __future__ import annotations

import ast
import re
from pathlib import Path

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
                if node.module == "engines" or base_module in LEGACY_FLAT_MODULES:
                    violations.append(f"{rel}:{node.lineno}: from {node.module} import ...")
    assert not violations, (
        "production code must use fully-qualified package imports, e.g. "
        "from engines.metabolic.metabolic_profiler_phenotype import ...:\n"
        + "\n".join(f"  - {item}" for item in violations)
    )


def _module_name_for(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _collect_import_targets(path: Path, mod_name: str, is_init: bool) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pkg_parts = mod_name.split(".") if is_init else mod_name.split(".")[:-1]
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 else pkg_parts
                targets.add(".".join(base + ([node.module] if node.module else [])))
            elif node.module:
                targets.add(node.module)
    return {t for t in targets if t.startswith("engines") or t.startswith("api")}


def test_no_new_unreachable_engine_modules() -> None:
    ALLOWED_UNREACHABLE = {
        "engines.core.audit": "dev/audit script (maps the package for refactor planning), not a product engine",
        "engines.performance.mader_residual_mlp": "ML residual-correction layer for Mader; not wired in by design",
        "engines.performance.neural_ode": "compatibility alias for mader_residual_mlp, same status",
        "engines.twin_state.serialization": "confirmed frontend/DB use, not backend-internal",
    }

    files = [p for p in (ROOT / "engines").rglob("*.py") if "__pycache__" not in p.parts]
    files += [p for p in (ROOT / "api").rglob("*.py") if "__pycache__" not in p.parts]
    if (ROOT / "api_app.py").is_file():
        files.append(ROOT / "api_app.py")

    modules = {_module_name_for(p): p for p in files}
    graph = {
        mod: _collect_import_targets(path, mod, path.name == "__init__.py")
        for mod, path in modules.items()
    }

    def expand(target: str) -> set[str]:
        if target in modules:
            return {target}
        return {m for m in modules if m.startswith(target + ".")}

    seen: set[str] = set()
    stack = [m for m in modules if m == "api_app" or m.startswith("api.")]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for target in graph.get(cur, set()):
            stack.extend(expand(target) - seen)

    non_init_engines = {m for m in modules if m.startswith("engines.") and modules[m].name != "__init__.py"}
    unreachable = non_init_engines - seen

    unexpected = unreachable - set(ALLOWED_UNREACHABLE)
    stale = set(ALLOWED_UNREACHABLE) - unreachable
    assert not unexpected, (
        "these engine modules are never imported from api/:\n"
        + "\n".join(f"  - {m}" for m in sorted(unexpected))
    )
    assert not stale, (
        "these are listed as known-unreachable but are now wired in:\n"
        + "\n".join(f"  - {m}" for m in sorted(stale))
    )


def test_session_router_declared_engines_have_execution_branches() -> None:
    path = ROOT / "engines" / "io" / "session_router.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    decide_fn = functions["decide_route"]

    declared: set[str] = set()
    for node in ast.walk(decide_fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "engines" in targets:
                declared.update(
                    elt.value for elt in node.value.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "engines"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            declared.add(node.args[0].value)

    from engines.io.session_router import _EXECUTORS

    missing = declared - set(_EXECUTORS)
    assert not missing, (
        "decide_route() can put these into engines_to_run, but session_router "
        "has no executor for them:\n"
        + "\n".join(f"  - {name}" for name in sorted(missing))
    )


def test_doc_numeric_claims_match_live_codebase() -> None:
    import json
    from engines.io.chart_registry import list_chart_types

    openapi = json.loads((ROOT / "openapi" / "openapi.json").read_text(encoding="utf-8"))
    live_paths = len(openapi.get("paths", {}))
    live_charts = list_chart_types()["total"]

    EXCLUDE = {"RELEASE_NOTES", "DEVELOPER_ONBOARDING"}

    doc_files = list((ROOT / "docs").glob("*.md")) + [
        ROOT / "README.md",
        ROOT / "DEVELOPMENT_TEAM_HANDOFF.md",
    ]

    path_re = re.compile(r"\b(\d+)\s+(?:OpenAPI paths|documented endpoints|HTTP paths|paths total|endpoints total)")
    chart_re = re.compile(r"\b(\d+)\s+chart types?\b")

    path_violations: list[str] = []
    chart_violations: list[str] = []

    for f in doc_files:
        if any(excl in f.name for excl in EXCLUDE):
            continue
        text = f.read_text(encoding="utf-8")
        for m in path_re.finditer(text):
            claimed = int(m.group(1))
            if claimed != live_paths:
                path_violations.append(f"{f.name}: claims {claimed}, live={live_paths}")
        for m in chart_re.finditer(text):
            claimed = int(m.group(1))
            if claimed != live_charts:
                chart_violations.append(f"{f.name}: claims {claimed}, live={live_charts}")

    assert not path_violations, (
        f"Stale OpenAPI path counts in docs (live={live_paths}):\n"
        + "\n".join(f"  - {v}" for v in path_violations)
    )
    assert not chart_violations, (
        f"Stale chart type counts in docs (live={live_charts}):\n"
        + "\n".join(f"  - {v}" for v in chart_violations)
    )


def json_load_paths() -> dict:
    import json

    return json.loads(OPENAPI_JSON.read_text(encoding="utf-8")).get("paths", {})
