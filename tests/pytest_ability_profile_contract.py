from __future__ import annotations

from engines.performance.ability_profile import build_ability_profile


def test_ability_profile_exposes_raw_wkg_alias_when_weight_is_available() -> None:
    profile = {
        "weight_kg": 72.0,
        "mmp": {
            "5": 1000,
            "60": 520,
            "300": 380,
            "1200": 310,
            "3600": 250,
        },
    }

    out = build_ability_profile(profile)

    assert out["status"] == "success"
    assert out["raw_wkg"] == out["derived_w_kg"]
    assert out["raw_wkg"]["5s"] == round(1000 / 72.0, 2)
    assert out["raw_wkg"]["1200s"] == round(310 / 72.0, 2)
    assert out["model_metadata"]["missing_inputs"] == []


def test_ability_profile_hides_wkg_without_body_mass() -> None:
    profile = {
        "mmp": {
            "5": 1000,
            "60": 520,
            "300": 380,
            "1200": 310,
        },
    }

    out = build_ability_profile(profile)

    assert out["status"] == "success"
    assert out["raw_wkg"] == out["derived_w_kg"]
    assert all(value is None for value in out["raw_wkg"].values())
    assert "weight_kg" in out["model_metadata"]["missing_inputs"]
    assert "wkg_metrics_hidden_without_body_mass" in out["model_metadata"]["assumptions"]
