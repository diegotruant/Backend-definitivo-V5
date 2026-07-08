"""Tests for athlete-level metabolic profile from published aggregate MMP."""

from __future__ import annotations

from engines.core.athlete_context import AthleteContext
from engines.io.activity_metabolic_deprecation import apply_activity_metabolic_deprecation
from engines.io.athlete_activity_report import build_athlete_activity_report
from engines.io.full_activity_bundle import build_full_activity_bundle
from engines.performance.mmp_aggregate import MMP_STATUS_PUBLISHED, evaluate_mmp_readiness
from engines.persistence.metabolic_profile_pipeline import sync_metabolic_profile_after_mmp
from engines.persistence.metabolic_profile_store import InMemoryMetabolicProfileStore
from engines.persistence.mmp_aggregate_store import InMemoryMmpAggregateStore
from engines.physiology.metabolic_profile_calculator import (
    calculate_metabolic_profile_from_mmp,
    should_create_new_profile_version,
)
from tests.pytest_full_activity_bundle_contract import _rich_stream


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


def _athlete_data() -> dict:
    return {"weight_kg": 72.0, "sex": "male", "age": 40}


def _readiness(curve: list[dict], n_activities: int = 8) -> dict:
    readiness = evaluate_mmp_readiness(curve, n_activities)
    readiness["n_activities_included"] = n_activities
    return readiness


def test_calculate_profile_from_published_mmp() -> None:
    curve = _published_curve()
    readiness = _readiness(curve)
    assert readiness["mmp_status"] == MMP_STATUS_PUBLISHED

    profile = calculate_metabolic_profile_from_mmp(curve, _athlete_data(), readiness)
    assert profile["status"] == "success"
    assert profile["map_power_w"] > 0
    assert profile["mlss_power_w"] > 0
    assert profile["vo2max_ml_kg_min"] > 0
    assert profile["vlamax_mmol_l_s"] > 0
    assert profile["fatmax_power_w"] > 0
    assert profile["phenotype_type"] in {"endurance_leaning", "balanced", "glycolytic_leaning"}


def test_skip_profile_when_mmp_collecting() -> None:
    curve = [{"duration_s": 60, "power_w": 400.0}]
    readiness = evaluate_mmp_readiness(curve, 1)
    profile = calculate_metabolic_profile_from_mmp(curve, _athlete_data(), readiness)
    assert profile["status"] == "skipped"
    assert profile["reason"] == "MMP_NOT_PUBLISHED"


def test_should_create_first_profile() -> None:
    new_profile = {"map_power_w": 300, "mlss_power_w": 250, "confidence_tier": "MODERATE"}
    should, reason = should_create_new_profile_version(None, new_profile, [{"duration_s": 60}])
    assert should is True
    assert reason == "first_profile"


def test_should_not_create_without_mmp_changes() -> None:
    latest = {
        "map_power_w": 300.0,
        "mlss_power_w": 250.0,
        "vlamax_mmol_l_s": 0.40,
        "fatmax_power_w": 145.0,
        "apr_w": 500.0,
        "confidence_tier": "MODERATE",
    }
    new = dict(latest)
    should, reason = should_create_new_profile_version(latest, new, [])
    assert should is False
    assert reason == "mmp_not_changed"


def test_should_create_on_map_change() -> None:
    latest = {
        "map_power_w": 300.0,
        "mlss_power_w": 250.0,
        "vlamax_mmol_l_s": 0.40,
        "fatmax_power_w": 145.0,
        "apr_w": 500.0,
        "confidence_tier": "MODERATE",
    }
    new = dict(latest, map_power_w=320.0)
    should, reason = should_create_new_profile_version(latest, new, [{"duration_s": 300, "power_w": 320}])
    assert should is True
    assert reason == "map_changed"


def _seed_published_aggregate(store: InMemoryMmpAggregateStore, athlete_id: str) -> None:
    curve = _published_curve()
    readiness = evaluate_mmp_readiness(curve, 8)
    store.upsert_aggregate(
        athlete_id=athlete_id,
        mmp_curve_json=curve,
        coverage_score=float(readiness["coverage_score"]),
        confidence_tier=str(readiness["confidence_tier"]),
        mmp_status=MMP_STATUS_PUBLISHED,
        n_activities_included=8,
        n_key_durations_covered=int(readiness["n_key_durations_covered"]),
    )


def test_sync_creates_first_profile_version() -> None:
    mmp_store = InMemoryMmpAggregateStore()
    profile_store = InMemoryMetabolicProfileStore()
    athlete_id = "athlete-profile-1"
    _seed_published_aggregate(mmp_store, athlete_id)

    result = sync_metabolic_profile_after_mmp(
        mmp_store,
        profile_store,
        athlete_id=athlete_id,
        athlete_data=_athlete_data(),
        changed_mmp_points=[{"duration_s": 300, "power_w": 330}],
    )
    assert result["status"] == "success"
    assert result["profile_version"] == 1
    active = profile_store.load_latest_active_profile(athlete_id)
    assert active is not None
    assert active["is_active"] is True
    current = profile_store.load_current_profile_view(athlete_id)
    assert current is not None
    assert current["profile_version"] == 1


def test_sync_skips_when_collecting() -> None:
    mmp_store = InMemoryMmpAggregateStore()
    profile_store = InMemoryMetabolicProfileStore()
    athlete_id = "athlete-profile-2"
    curve = [{"duration_s": 60, "power_w": 400.0}]
    readiness = evaluate_mmp_readiness(curve, 1)
    mmp_store.upsert_aggregate(
        athlete_id=athlete_id,
        mmp_curve_json=curve,
        coverage_score=float(readiness["coverage_score"]),
        confidence_tier=str(readiness["confidence_tier"]),
        mmp_status=str(readiness["mmp_status"]),
        n_activities_included=1,
        n_key_durations_covered=int(readiness["n_key_durations_covered"]),
    )
    result = sync_metabolic_profile_after_mmp(
        mmp_store,
        profile_store,
        athlete_id=athlete_id,
        athlete_data=_athlete_data(),
        changed_mmp_points=[{"duration_s": 60, "power_w": 410}],
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "MMP_NOT_PUBLISHED"


def test_pipeline_no_new_version_without_relevant_changes() -> None:
    mmp_store = InMemoryMmpAggregateStore()
    profile_store = InMemoryMetabolicProfileStore()
    athlete_id = "athlete-profile-3"
    _seed_published_aggregate(mmp_store, athlete_id)
    sync_metabolic_profile_after_mmp(
        mmp_store,
        profile_store,
        athlete_id=athlete_id,
        athlete_data=_athlete_data(),
        changed_mmp_points=[{"duration_s": 300, "power_w": 330}],
    )

    second = sync_metabolic_profile_after_mmp(
        mmp_store,
        profile_store,
        athlete_id=athlete_id,
        athlete_data=_athlete_data(),
        changed_mmp_points=[],
    )
    assert second["status"] == "skipped"
    assert second["reason"] == "mmp_not_changed"
    assert len(profile_store.versions) == 1


def test_bundle_marks_activity_metabolic_deprecated() -> None:
    bundle = build_full_activity_bundle(
        _rich_stream(n=3600),
        weight_kg=72.0,
        ftp=260.0,
        context=AthleteContext(),
        file_id="ride.fit",
    )
    assert bundle.get("do_not_use_as_athlete_profile") is True
    snapshot = bundle["workout_summary"]["sections"].get("metabolic_snapshot")
    if snapshot:
        assert snapshot.get("metabolic_snapshot_status") == "deprecated_activity_level_estimate"


def test_athlete_activity_report_single_profile_section() -> None:
    profile = {
        "profile_version": 1,
        "profile_status": "published",
        "confidence_score": 0.82,
        "confidence_tier": "HIGH",
        "vo2max_ml_kg_min": 47.8,
        "map_power_w": 331,
        "mlss_power_w": 250,
        "calculated_at": "2026-07-01T00:00:00Z",
        "valid_from_date": "2026-07-01",
    }
    bundle = build_full_activity_bundle(
        _rich_stream(n=1800),
        weight_kg=72.0,
        ftp=260.0,
        context=AthleteContext(),
        file_id="ride.fit",
    )
    report = build_athlete_activity_report(
        athlete_id="athlete-1",
        activities=[{"activity_id": "a1", "bundle": bundle}],
        active_profile=profile,
        mmp_contributions={"a1": {"contributed": True, "improved_durations": [60]}},
    )
    assert report["athlete_metabolic_profile"]["status"] == "available"
    assert report["athlete_metabolic_profile"]["vo2max_ml_kg_min"] == 47.8
    assert len(report["activities"]) == 1
    assert "vo2max" not in report["activities"][0]
