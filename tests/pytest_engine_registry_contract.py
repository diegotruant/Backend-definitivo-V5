"""
The engine registry (engines/io/engine_registry.py) must stay true to the
actual session_router code.
"""

from __future__ import annotations

import ast
from pathlib import Path

from engines.io.engine_registry import (
    SESSION_ROUTER_ENGINES,
    session_router_routing_keys,
)

ROOT = Path(__file__).resolve().parents[1]
SESSION_ROUTER = ROOT / "engines" / "io" / "session_router.py"


def _functions() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(SESSION_ROUTER.read_text(encoding="utf-8"), filename=str(SESSION_ROUTER))
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _routing_keys_from_decide_route() -> set[str]:
    fn = _functions()["decide_route"]
    keys: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            if any(isinstance(t, ast.Name) and t.id == "engines" for t in node.targets):
                keys.update(
                    e.value for e in node.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
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
            keys.add(node.args[0].value)
    return keys


def test_registry_routing_keys_match_decide_route() -> None:
    registry_keys = set(session_router_routing_keys())
    code_keys = _routing_keys_from_decide_route()
    missing_from_registry = code_keys - registry_keys
    missing_from_code = registry_keys - code_keys
    assert not missing_from_registry, (
        "decide_route() can emit these routing keys but the registry omits them:\n"
        + "\n".join(f"  - {k}" for k in sorted(missing_from_registry))
    )
    assert not missing_from_code, (
        "the registry lists these routing keys but decide_route() never emits them:\n"
        + "\n".join(f"  - {k}" for k in sorted(missing_from_code))
    )


def test_registry_skip_keys_match_route_and_run() -> None:
    for spec in SESSION_ROUTER_ENGINES:
        assert spec.skip_key in {spec.routing_key, spec.output_key}, (
            f"{spec.routing_key}: skip_key {spec.skip_key!r} is neither the "
            f"routing key nor the output key {spec.output_key!r}"
        )


def test_registry_output_keys_are_wellformed() -> None:
    outputs = [spec.output_key for spec in SESSION_ROUTER_ENGINES]
    assert all(outputs), "every output_key must be non-empty"
    dupes = {k for k in outputs if outputs.count(k) > 1}
    assert not dupes, f"duplicate output_key in registry: {sorted(dupes)}"


def test_registry_every_routing_key_is_executed() -> None:
    from engines.io.session_router import _EXECUTORS

    registry_keys = set(session_router_routing_keys())
    executor_keys = set(_EXECUTORS)
    not_executed = registry_keys - executor_keys
    orphan = executor_keys - registry_keys
    assert not not_executed, (
        "these registry routing keys have no executor in session_router._EXECUTORS:\n"
        + "\n".join(f"  - {k}" for k in sorted(not_executed))
    )
    assert not orphan, (
        "session_router._EXECUTORS has executors for keys not in the registry:\n"
        + "\n".join(f"  - {k}" for k in sorted(orphan))
    )


def test_registry_routing_keys_unique() -> None:
    keys = session_router_routing_keys()
    dupes = {k for k in keys if keys.count(k) > 1}
    assert not dupes, f"duplicate routing_key in registry: {sorted(dupes)}"


def test_registry_specs_are_wellformed() -> None:
    for spec in SESSION_ROUTER_ENGINES:
        assert spec.routing_key, "routing_key must be non-empty"
        assert spec.output_key, f"output_key must be non-empty for {spec.routing_key}"
        assert spec.description, f"description must be non-empty for {spec.routing_key}"
        assert isinstance(spec.required_signals, tuple), spec.routing_key
