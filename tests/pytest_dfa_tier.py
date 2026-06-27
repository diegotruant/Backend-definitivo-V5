"""DFA-α₁ outputs must be tier EXPERIMENTAL everywhere."""

from __future__ import annotations

from engines.core.tiers import Tier, tier_for
from engines.io.session_router import _hrv_durability
from engines.io.workout_summary import build_workout_summary
from engines.recovery.cardiac_engine import cross_validate_thresholds
from engines.recovery.hrv_engine import calculate_dfa_alpha1, detect_thresholds_from_activity
from tests.fixtures.synthetic_fit import build_synthetic_fit_bytes, parse_synthetic_fit


def test_hrv_engine_tier_registry_is_experimental() -> None:
    assert tier_for("hrv_engine") == Tier.EXPERIMENTAL


def test_calculate_dfa_alpha1_attaches_experimental_tier() -> None:
    out = calculate_dfa_alpha1([820.0] * 80)
    assert out["tier"] == "EXPERIMENTAL"
    assert out["tier_explanation"]


def test_detect_thresholds_api_contract_is_experimental() -> None:
    rr_samples = [{"elapsed": float(i * 10), "rr": [820.0 - i * 0.5] * 25} for i in range(60)]
    out = detect_thresholds_from_activity(rr_samples)
    assert out["api_contract"]["tier"] == "EXPERIMENTAL"
    assert out["tier"] == "EXPERIMENTAL"


def test_workout_summary_hrv_section_is_experimental() -> None:
    raw = build_synthetic_fit_bytes(
        [
            (1_735_689_600 + i * 60, 220, 140 + (i % 3), 120)
            for i in range(30)
        ]
    )
    stream = parse_synthetic_fit(raw)
    summary = build_workout_summary(stream, weight_kg=75.0, ftp=250.0)
    hrv = summary.get("sections", {}).get("hrv") or {}
    if hrv.get("available"):
        assert hrv["tier"] == "EXPERIMENTAL"


def test_session_router_hrv_helpers_expose_experimental_tier() -> None:
    rr_samples = [{"elapsed": float(i * 10), "rr": [820.0] * 20} for i in range(40)]
    durability = _hrv_durability(rr_samples, elapsed_s=None, ctx=None)
    if durability.get("status") == "ok":
        assert durability["tier"] == "EXPERIMENTAL"


def test_cardiac_cross_validation_tags_dfa_fields_experimental() -> None:
    import numpy as np

    t = np.arange(0, 600, 1.0)
    p = np.full(600, 220.0)
    h = np.linspace(140, 155, 600)
    timeline = [
        {"timestamp": 60.0, "status": "AEROBIC", "alpha1_smoothed": 0.92},
        {"timestamp": 180.0, "status": "MIXED", "alpha1_smoothed": 0.72},
        {"timestamp": 300.0, "status": "ANAEROBIC", "alpha1_smoothed": 0.55},
    ]
    out = cross_validate_thresholds(t, p, h, metabolic_snapshot=None, hrv_timeline=timeline)
    assert out.get("dfa_alpha1_tier") == "EXPERIMENTAL"
