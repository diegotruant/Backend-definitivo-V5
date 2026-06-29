"""TwinState metabolic curves sync — product contracts."""

from __future__ import annotations

from engines.twin_state import (
    PROFILE_CURVE_IDS,
    build_twin_state,
    sync_lactate_state_from_steps,
    sync_twin_after_profile_refresh,
    update_twin_state_from_ride,
)
from engines.twin_state.metabolic_curves_sync import ingest_worker_hook_points


def _snapshot() -> dict:
    return {
        "status": "success",
        "fatmax_power_watts": 185.0,
        "mlss_power_watts": 282.0,
        "map_aerobic_watts": 392.0,
        "estimated_vo2max": 58.0,
        "estimated_vlamax_mmol_L_s": 0.42,
        "combustion_curve": [
            {"watt": 120, "fat_oxidation_g_min_est": 0.4, "carbohydrate_oxidation_g_min_est": 0.2},
            {"watt": 220, "fat_oxidation_g_min_est": 0.3, "carbohydrate_oxidation_g_min_est": 0.8},
            {"watt": 320, "fat_oxidation_g_min_est": 0.1, "carbohydrate_oxidation_g_min_est": 1.4},
        ],
    }


def _athlete_payload() -> dict:
    return {
        "athlete_id": "athlete-42",
        "athlete_profile": {
            "athlete_id": "athlete-42",
            "weight_kg": 72.0,
            "gender": "MALE",
            "training_years": 10,
            "discipline": "ROAD",
        },
        "metabolic_snapshot": _snapshot(),
        "rolling_power_curve": {"curve": {"60": 480, "300": 340}},
        "load_state": {"acute_load": 40.0, "chronic_load": 55.0},
    }


def test_build_twin_state_auto_populates_profile_metabolic_curves() -> None:
    twin = build_twin_state(_athlete_payload())
    curves = twin["metabolic_curves"]
    assert curves["schema_version"] == "metabolic_curves.v1"
    assert "vo2_demand" in curves["available_curves"]
    assert "substrate_oxidation" in curves["available_curves"]
    assert curves["curves"]["vo2_demand"]["points"]
    assert curves["curves"]["vo2_demand"]["measurement_tier"] == "MODEL_ESTIMATE"


def test_build_twin_state_can_skip_metabolic_curves_sync() -> None:
    twin = build_twin_state({**_athlete_payload(), "skip_metabolic_curves_sync": True})
    assert twin.get("metabolic_curves") == {}


def test_update_from_ride_refreshes_curves_when_snapshot_supplied() -> None:
    base = build_twin_state(_athlete_payload())
    refreshed = dict(_snapshot())
    refreshed["estimated_vo2max"] = 61.0

    updated = update_twin_state_from_ride(
        base,
        ingest_result={"curve": base["rolling_power_curve"], "profile_should_refresh": True},
        metabolic_snapshot=refreshed,
    )
    assert updated["metabolic_snapshot"]["estimated_vo2max"] == 61.0
    vo2_points = updated["metabolic_curves"]["curves"]["vo2_demand"]["points"]
    assert vo2_points
    assert any(
        e.get("type") == "ride_ingested" and e.get("metabolic_curves_synced")
        for e in updated["event_log"][-3:]
    )


def test_sync_lactate_state_from_steps_populates_lactate_state() -> None:
    twin = build_twin_state(_athlete_payload())
    steps = [
        {"power_w": 160, "lactate_mmol": 1.5},
        {"power_w": 220, "lactate_mmol": 2.4},
        {"power_w": 280, "lactate_mmol": 4.1},
        {"power_w": 320, "lactate_mmol": 7.0},
    ]
    updated = sync_lactate_state_from_steps(twin, steps)
    assert updated["lactate_state"]["schema_version"] == "lactate_state.v1"
    assert updated["lactate_state"]["measurement_tier"] == "LAB_MEASURED"
    assert updated["metabolic_curves"]["curves"]["lactate"]["points"]


def test_sync_twin_after_profile_refresh_includes_profile_curve_ids() -> None:
    twin = build_twin_state({**_athlete_payload(), "skip_metabolic_curves_sync": True})
    synced = sync_twin_after_profile_refresh(twin, _snapshot())
    available = set(synced["metabolic_curves"]["available_curves"])
    assert set(PROFILE_CURVE_IDS).issubset(available)


def test_ingest_worker_hook_points_documents_orchestration() -> None:
    hooks = ingest_worker_hook_points()
    assert hooks["curves_schema"] == "metabolic_curves.v1"
    assert hooks["lactate_schema"] == "lactate_state.v1"
    assert "sync_twin_after_profile_refresh" in hooks["after_profile_refresh"]
