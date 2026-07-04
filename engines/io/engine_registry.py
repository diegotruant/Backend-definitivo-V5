"""
Engine orchestration registry — single source of truth (Phase 1: description only).

WHAT THIS IS
------------
Across the backend there are several independent post-parse orchestration
paths, and historically each hardcoded its own list of which engines to run,
with no shared registry. That is exactly how bugs like "interval_stimulus was
decided but never executed" happened: four lists that don't talk to each
other, so a gap in one is invisible.

This module is the first step toward fixing that: a declarative description of
the engines the *session_router* path can run. In this phase it changes NO
runtime behavior — nothing imports it to make decisions yet. It exists so
that:

  1. There is one place a human can read to understand the session_router
     wiring, instead of cross-referencing decide_route() against
     route_and_run() by eye.
  2. A test (tests/pytest_engine_registry_contract.py) can assert this
     description stays true to the code. If someone adds an engine branch to
     route_and_run() or a routing key to decide_route() and forgets the
     other side, the test fails against this registry.

Later phases will make route_and_run() *read* from this registry instead of
carrying its own inline branches, one engine at a time, with the full suite
green after each. Until then, treat this as documentation that is validated
by tests rather than left to rot.

IMPORTANT — routing key vs output key
-------------------------------------
The key decide_route() puts in engines_to_run is NOT always the key the
result is stored under. Two cases differ today and the registry records both:

    routing_key                 -> output_key
    "hrv_threshold_vt1_vt2"     -> "hrv_threshold"
    "test_effort_extraction"    -> "test_proposal"

Do not "simplify" these to match without also changing route_and_run() and
every caller/test that reads the output key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class EngineSpec:
    """One engine the session_router path knows how to run."""

    routing_key: str
    output_key: str
    skip_key: str
    required_signals: Tuple[str, ...] = field(default_factory=tuple)
    description: str = ""


SESSION_ROUTER_ENGINES: Tuple[EngineSpec, ...] = (
    EngineSpec(
        routing_key="hrv_threshold_vt1_vt2",
        output_key="hrv_threshold",
        skip_key="hrv_threshold",
        required_signals=("rr",),
        description="VT1/VT2 in watts from DFA-alpha1 vs power. Ramp-like tests with RR only.",
    ),
    EngineSpec(
        routing_key="hrv_durability",
        output_key="hrv_durability",
        skip_key="hrv_durability",
        required_signals=("rr",),
        description="HRV durability / time-in-zone from RR. Rides and structured tests with RR.",
    ),
    EngineSpec(
        routing_key="test_effort_extraction",
        output_key="test_proposal",
        skip_key="test_effort_extraction",
        required_signals=("power",),
        description="Extract a structured test proposal (sprint->VLamax, CP->aerobic) from efforts.",
    ),
    EngineSpec(
        routing_key="metabolic_profile",
        output_key="metabolic_snapshot",
        skip_key="metabolic_profile",
        required_signals=("power",),
        description="Full metabolic snapshot via MetabolicProfiler over the power curve.",
    ),
    EngineSpec(
        routing_key="mader_durability",
        output_key="mader_durability",
        skip_key="mader_durability",
        required_signals=("power", "metabolic_profile"),
        description="Mader CP-residual mechanistic durability. Needs an existing metabolic snapshot.",
    ),
    EngineSpec(
        routing_key="interval_stimulus",
        output_key="interval_stimulus",
        skip_key="interval_stimulus",
        required_signals=("power", "ftp"),
        description="Interval time-in-zone stimulus vector. HIIT sessions; needs ftp for zones.",
    ),
    EngineSpec(
        routing_key="power_curve_update",
        output_key="power_curve",
        skip_key="power_curve_update",
        required_signals=("power",),
        description="Update the athlete power-duration curve from this ride.",
    ),
)


def session_router_routing_keys() -> List[str]:
    return [spec.routing_key for spec in SESSION_ROUTER_ENGINES]


def session_router_by_routing_key() -> Dict[str, EngineSpec]:
    return {spec.routing_key: spec for spec in SESSION_ROUTER_ENGINES}


def session_router_output_keys() -> Dict[str, str]:
    return {spec.routing_key: spec.output_key for spec in SESSION_ROUTER_ENGINES}
