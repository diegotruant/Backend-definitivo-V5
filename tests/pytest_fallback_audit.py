from __future__ import annotations

import pytest

from engines.core.athlete_context import AthleteContext
from engines.core.athlete_weight import resolve_weight_kg
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.neuromuscular_profile import analyze_neuromuscular_profile
from engines.performance.test_protocols import run_test as run_in_person_test


def test_resolve_weight_kg_explicit_is_official() -> None:
    weight, meta = resolve_weight_kg(72.0)
    assert weight == 72.0
    assert meta["wkg_official"] is True
    assert meta["source"] == "explicit"


def test_resolve_weight_kg_default_is_not_official() -> None:
    weight, meta = resolve_weight_kg(None, default=70.0)
    assert weight == 70.0
    assert meta["wkg_official"] is False
    assert "defaulted" in meta["assumptions"][0]


def test_resolve_weight_kg_missing_blocks_wkg() -> None:
    weight, meta = resolve_weight_kg(None)
    assert weight is None
    assert meta["wkg_official"] is False


def test_neuromuscular_profile_without_weight_has_no_wkg() -> None:
    class Stream:
        power = [100, 900, 900, 900, 100]
        cadence = [90, 110, 110, 110, 90]

    out = analyze_neuromuscular_profile(Stream(), weight_kg=None)
    assert out["status"] == "success"
    assert out["summary"]["pmax_wkg"] is None


def test_in_person_wingate_without_weight_has_no_wkg() -> None:
    envelope = {
        "test_type": "wingate",
        "athlete": {},
        "test_data": {"duration_s": 30, "power_stream": [800] * 30},
    }
    out = run_in_person_test(envelope, profiler=MetabolicProfiler(70.0, AthleteContext()))
    assert out["status"] == "success"
    assert out.get("peak_power_wkg") is None


def test_readness_package_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        import engines.readness  # noqa: F401


def test_readiness_canonical_import_works() -> None:
    from engines.readiness.readiness_engine import compute_readiness_today  # noqa: F401
