"""Tests for athlete model unification (phases 2b–6)."""

from __future__ import annotations

from engines.performance.mmp_aggregate import MMP_STATUS_PUBLISHED, evaluate_mmp_readiness
from engines.persistence.metabolic_profile_store import InMemoryMetabolicProfileStore
from engines.persistence.mmp_aggregate_store import InMemoryMmpAggregateStore
from engines.persistence.mmp_unification import aggregate_curve_to_rolling_curve, resolve_canonical_rolling_curve
from engines.persistence.threshold_pipeline import sync_thresholds_after_profile
from engines.persistence.threshold_store import InMemoryThresholdStore
from engines.physiology.athlete_profile_bridge import (
    build_zone_anchors_from_model,
    resolve_active_athlete_model,
    versioned_profile_to_metabolic_snapshot,
)
from engines.physiology.threshold_calculator import estimate_thresholds_from_mmp
from engines.twin_state.athlete_model_sync import sync_twin_athlete_model
from engines.twin_state.metabolic_curves_sync import sync_twin_from_versioned_profile
from engines.twin_state.models import build_twin_state


def _published_curve() -> list[dict]:
    durations = [1, 5, 15, 60, 180, 300, 420, 1200, 1800, 2400, 3600]
    return [
        {
            "duration_s": d,
            "power_w": 1000.0 - d * 0.15,
            "source_activity_id": "act-base",
            "source_file_id": "file-base",
            "activity_date": "2026-06-01",
        }
        for d in durations
    ]


def _seed_published(mmp_store: InMemoryMmpAggregateStore, athlete_id: str) -> None:
    curve = _published_curve()
    readiness = evaluate_mmp_readiness(curve, 8)
    mmp_store.upsert_aggregate(
        athlete_id=athlete_id,
        mmp_curve_json=curve,
        coverage_score=float(readiness["coverage_score"]),
        confidence_tier=str(readiness["confidence_tier"]),
        mmp_status=MMP_STATUS_PUBLISHED,
        n_activities_included=8,
        n_key_durations_covered=int(readiness["n_key_durations_covered"]),
    )


def test_versioned_profile_to_snapshot_for_twin() -> None:
    profile = {
        "profile_version": 2,
        "profile_status": "published",
        "vo2max_ml_kg_min": 48.0,
        "vlamax_mmol_l_s": 0.42,
        "mlss_power_w": 250.0,
        "map_power_w": 330.0,
        "fatmax_power_w": 145.0,
    }
    snapshot = versioned_profile_to_metabolic_snapshot(profile)
    assert snapshot["status"] == "success"
    assert snapshot["source"] == "athlete_metabolic_profile_versions"
    assert snapshot["estimated_vo2max"] == 48.0


def test_sync_twin_from_versioned_profile() -> None:
    twin = build_twin_state({"athlete_id": "a1"})
    profile = {
        "profile_version": 1,
        "vo2max_ml_kg_min": 47.0,
        "vlamax_mmol_l_s": 0.40,
        "mlss_power_w": 245.0,
        "map_power_w": 325.0,
        "fatmax_power_w": 140.0,
        "profile_status": "published",
        "confidence_score": 0.8,
        "confidence_tier": "HIGH",
    }
    synced = sync_twin_from_versioned_profile(twin, profile)
    assert synced["metabolic_snapshot"]["source"] == "athlete_metabolic_profile_versions"
    assert synced["metabolic_metrics"]["vo2max_ml_kg_min"] == 47.0


def test_canonical_mmp_prefers_aggregate() -> None:
    curve = _published_curve()
    aggregate = {"mmp_status": MMP_STATUS_PUBLISHED, "mmp_curve_json": curve}
    legacy = {"60": {"duration_s": 60, "power_w": 300.0}}
    resolved = resolve_canonical_rolling_curve(aggregate_record=aggregate, legacy_rolling_curve=legacy)
    assert resolved["source"] == "athlete_mmp_aggregate"
    assert resolved["curve"]["300"]["power_w"] > legacy["60"]["power_w"]


def test_aggregate_curve_to_rolling_format() -> None:
    rolling = aggregate_curve_to_rolling_curve(_published_curve())
    assert rolling["300"]["source"] == "athlete_mmp_aggregate"


def test_threshold_estimate_and_sync() -> None:
    mmp_store = InMemoryMmpAggregateStore()
    profile_store = InMemoryMetabolicProfileStore()
    threshold_store = InMemoryThresholdStore()
    athlete_id = "athlete-threshold-1"
    _seed_published(mmp_store, athlete_id)

    profile_store.save_metabolic_profile_version(
        athlete_id=athlete_id,
        profile_version=1,
        profile={
            "profile_status": "published",
            "vo2max_ml_kg_min": 47.0,
            "vlamax_mmol_l_s": 0.40,
            "mlss_power_w": 250.0,
            "map_power_w": 330.0,
            "fatmax_power_w": 145.0,
            "confidence_score": 0.8,
            "confidence_tier": "HIGH",
        },
        source_mmp=mmp_store.load_aggregate_record(athlete_id) or {},
        is_active=True,
        creation_reason="first_profile",
    )
    profile_store.update_athlete_current_profile(
        athlete_id=athlete_id,
        active_profile_id=profile_store.versions[0]["id"],
        profile_version=1,
        profile_status="published",
        confidence_score=0.8,
        confidence_tier="HIGH",
    )

    result = sync_thresholds_after_profile(mmp_store, threshold_store, profile_store, athlete_id=athlete_id)
    assert result["status"] == "success"
    assert result["ftp_w"] > 0


def test_zone_anchors_from_model() -> None:
    profile = {"profile_version": 1, "mlss_power_w": 250.0, "map_power_w": 330.0}
    thresholds = {"threshold_version": 1, "ftp_w": 240.0, "lthr_bpm": 168.0, "cp_w": 250.0}
    anchors = build_zone_anchors_from_model(profile, thresholds)
    assert anchors["status"] == "success"
    assert anchors["ftp_w"] == 240.0
    assert anchors["vt2_w"] == 250.0


def test_sync_twin_athlete_model_full() -> None:
    mmp_store = InMemoryMmpAggregateStore()
    profile_store = InMemoryMetabolicProfileStore()
    threshold_store = InMemoryThresholdStore()
    athlete_id = "athlete-model-1"
    _seed_published(mmp_store, athlete_id)

    profile_store.save_metabolic_profile_version(
        athlete_id=athlete_id,
        profile_version=1,
        profile={
            "profile_status": "published",
            "vo2max_ml_kg_min": 47.0,
            "vlamax_mmol_l_s": 0.40,
            "mlss_power_w": 250.0,
            "map_power_w": 330.0,
            "fatmax_power_w": 145.0,
            "confidence_score": 0.8,
            "confidence_tier": "HIGH",
        },
        source_mmp=mmp_store.load_aggregate_record(athlete_id) or {},
        is_active=True,
        creation_reason="first_profile",
    )
    sync_thresholds_after_profile(mmp_store, threshold_store, profile_store, athlete_id=athlete_id)

    twin = build_twin_state({"athlete_id": athlete_id})
    synced = sync_twin_athlete_model(
        twin,
        athlete_id=athlete_id,
        mmp_store=mmp_store,
        profile_store=profile_store,
        threshold_store=threshold_store,
    )
    assert synced["mmp_curve_meta"]["source"] == "athlete_mmp_aggregate"
    assert synced["zone_anchors"]["ftp_w"] > 0
    assert synced["athlete_model"]["metabolic_profile_version"] == 1


def test_coach_ftp_override() -> None:
    thresholds = estimate_thresholds_from_mmp(
        _published_curve(),
        metabolic_profile={"mlss_power_w": 250.0, "map_power_w": 330.0},
        coach_ftp_w=255.0,
        mmp_status=MMP_STATUS_PUBLISHED,
    )
    assert thresholds["ftp_w"] == 255.0
    assert thresholds["source_type"] == "coach_override"


def test_resolve_active_athlete_model() -> None:
    model = resolve_active_athlete_model(
        metabolic_profile={"profile_version": 1, "mlss_power_w": 250.0, "map_power_w": 330.0, "vo2max_ml_kg_min": 47.0, "vlamax_mmol_l_s": 0.4, "fatmax_power_w": 145.0, "profile_status": "published", "confidence_score": 0.8, "confidence_tier": "HIGH"},
        thresholds={"threshold_version": 1, "ftp_w": 240.0},
    )
    assert model["status"] == "success"
    assert model["zone_anchors"]["ftp_w"] == 240.0
