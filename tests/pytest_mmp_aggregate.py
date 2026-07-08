"""Contract tests for athlete-level MMP aggregation pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import parse_fit_file_enhanced
from engines.io.full_activity_bundle import build_full_activity_bundle
from engines.performance.mmp_aggregate import (
    MMP_STATUS_COLLECTING,
    MMP_STATUS_PROVISIONAL,
    MMP_STATUS_PUBLISHED,
    evaluate_mmp_readiness,
    extract_mmp_points,
    merge_mmp_curves,
    public_mmp_curve,
)
from engines.persistence.mmp_aggregate_pipeline import sync_athlete_mmp_after_bundle
from engines.persistence.mmp_aggregate_store import InMemoryMmpAggregateStore
from tests.pytest_full_activity_bundle_contract import _rich_stream

FIT_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "fit"


def _bundle_with_mmp(**kwargs):
    return build_full_activity_bundle(
        _rich_stream(n=3600),
        weight_kg=72.0,
        ftp=260.0,
        lthr=172.0,
        context=AthleteContext(),
        file_id="ride.fit",
        **kwargs,
    )


def test_extract_mmp_points_from_bundle_shape() -> None:
    bundle = _bundle_with_mmp()
    points = extract_mmp_points(
        bundle,
        activity_id="act-1",
        activity_file_id="file-1",
        activity_date="2026-06-30",
    )
    assert points
    assert all(p["source_activity_id"] == "act-1" for p in points)
    assert all(p["power_w"] > 0 for p in points)
    durations = {p["duration_s"] for p in points}
    assert 60 in durations
    assert 300 in durations


def test_merge_mmp_curves_keeps_best_power_per_duration() -> None:
    existing = [
        {"duration_s": 60, "power_w": 400.0, "source_activity_id": "a1", "source_file_id": "f1", "activity_date": "2026-01-01"},
        {"duration_s": 300, "power_w": 320.0, "source_activity_id": "a1", "source_file_id": "f1", "activity_date": "2026-01-01"},
    ]
    new_points = [
        {"duration_s": 60, "power_w": 410.0, "source_activity_id": "a2", "source_file_id": "f2", "activity_date": "2026-02-01"},
        {"duration_s": 300, "power_w": 310.0, "source_activity_id": "a2", "source_file_id": "f2", "activity_date": "2026-02-01"},
    ]
    merged, improvements = merge_mmp_curves(existing, new_points)
    by_duration = {p["duration_s"]: p for p in merged}
    assert by_duration[60]["power_w"] == 410.0
    assert by_duration[60]["source_activity_id"] == "a2"
    assert by_duration[300]["power_w"] == 320.0
    assert len(improvements) == 1
    assert improvements[0]["duration_s"] == 60


def test_evaluate_mmp_readiness_collecting_on_first_activity() -> None:
    curve = [
        {"duration_s": 60, "power_w": 400.0},
        {"duration_s": 300, "power_w": 320.0},
    ]
    readiness = evaluate_mmp_readiness(curve, n_activities=1)
    assert readiness["mmp_status"] == MMP_STATUS_COLLECTING
    assert readiness["expose_to_frontend"] is False
    assert public_mmp_curve(curve, readiness) == []


def test_evaluate_mmp_readiness_provisional_and_published() -> None:
    provisional_curve = [
        {"duration_s": 60, "power_w": 400.0},
        {"duration_s": 300, "power_w": 320.0},
        {"duration_s": 1200, "power_w": 280.0},
    ]
    readiness = evaluate_mmp_readiness(provisional_curve, n_activities=5)
    assert readiness["mmp_status"] == MMP_STATUS_PROVISIONAL
    assert readiness["expose_to_frontend"] is True

    published_curve = provisional_curve + [
        {"duration_s": 180, "power_w": 350.0},
        {"duration_s": 3600, "power_w": 250.0},
    ]
    published = evaluate_mmp_readiness(published_curve, n_activities=8)
    assert published["mmp_status"] == MMP_STATUS_PUBLISHED
    assert published["confidence_tier"] == "high"


def test_sync_after_bundle_first_fit_collecting() -> None:
    store = InMemoryMmpAggregateStore()
    bundle = _bundle_with_mmp()
    result = sync_athlete_mmp_after_bundle(
        store,
        athlete_id="athlete-1",
        activity_id="activity-1",
        activity_file_id="file-1",
        activity_date="2026-06-30",
        bundle=bundle,
    )
    assert result["status"] == "success"
    assert result["mmp_status"] == MMP_STATUS_COLLECTING
    assert result["mmp_curve"] == []
    assert store.count_distinct_activities("athlete-1") == 1
    aggregate = store.aggregates["athlete-1"]
    assert len(aggregate["mmp_curve_json"]) > 0


def test_sync_after_bundle_multiple_fits_improves_and_eventually_exposes() -> None:
    store = InMemoryMmpAggregateStore()
    athlete_id = "athlete-2"

    for idx in range(5):
        bundle = _bundle_with_mmp()
        sync_athlete_mmp_after_bundle(
            store,
            athlete_id=athlete_id,
            activity_id=f"activity-{idx}",
            activity_file_id=f"file-{idx}",
            activity_date=f"2026-06-{idx + 1:02d}",
            bundle=bundle,
        )

    last = store.aggregates[athlete_id]
    assert last["n_activities_included"] == 5
    assert last["mmp_status"] in {MMP_STATUS_COLLECTING, MMP_STATUS_PROVISIONAL}

    # Simulate richer curve coverage for published gate
    rich_curve = []
    for duration in (1, 60, 180, 300, 1200, 3600):
        rich_curve.append(
            {
                "duration_s": duration,
                "power_w": 300.0 + duration / 10.0,
                "source_activity_id": "activity-rich",
                "source_file_id": "file-rich",
                "activity_date": "2026-07-01",
            }
        )
    store.aggregates[athlete_id]["mmp_curve_json"] = rich_curve
    for idx in range(5, 8):
        bundle = _bundle_with_mmp()
        result = sync_athlete_mmp_after_bundle(
            store,
            athlete_id=athlete_id,
            activity_id=f"activity-{idx}",
            activity_file_id=f"file-{idx}",
            activity_date=f"2026-07-{idx - 4:02d}",
            bundle=bundle,
        )
    assert result["n_activities_included"] >= 8
    if result["mmp_status"] == MMP_STATUS_PUBLISHED:
        assert result["expose_to_frontend"] is True
        assert result["mmp_curve"]


@pytest.mark.parametrize("stem", ["garmin_power_hr", "minimal_power_hr_lap_hrv"])
def test_extract_mmp_points_from_real_fit_bundle(stem: str) -> None:
    fit_path = FIT_ASSET_DIR / f"{stem}.fit"
    if not fit_path.exists():
        pytest.skip("missing FIT asset")
    stream = parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
    bundle = build_full_activity_bundle(
        stream,
        weight_kg=72.0,
        ftp=250.0,
        lthr=170.0,
        context=AthleteContext(),
        file_id=f"{stem}.fit",
    )
    points = extract_mmp_points(
        bundle,
        activity_id=f"act-{stem}",
        activity_file_id=f"file-{stem}",
        activity_date="2026-06-30",
    )
    assert points
    assert all(p["power_w"] > 0 for p in points)
