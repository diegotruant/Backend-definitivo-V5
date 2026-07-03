from __future__ import annotations

import numpy as np

from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import ActivityStreamEnhanced
from engines.io.full_activity_bundle import build_full_activity_bundle


def _rich_stream(n: int = 3600) -> ActivityStreamEnhanced:
    stream = ActivityStreamEnhanced(n_samples=n, sport="cycling", total_elapsed_s=float(n))
    stream.elapsed_s = np.arange(n, dtype=np.float32)
    stream.power = (220 + 25 * np.sin(np.arange(n) / 90.0)).astype(np.float32)
    stream.heart_rate = (132 + np.linspace(0, 14, n)).astype(np.float32)
    stream.cadence = (88 + 4 * np.sin(np.arange(n) / 30.0)).astype(np.float32)
    stream.distance_m = np.linspace(0, 36_000, n, dtype=np.float32)
    stream.altitude_m = np.linspace(180, 620, n, dtype=np.float32)
    stream.ambient_temp = np.full(n, 28.0, dtype=np.float32)
    stream.skin_temp = np.linspace(33.0, 35.0, n, dtype=np.float32)
    stream.core_body_temp = np.linspace(37.1, 38.7, n, dtype=np.float32)
    stream.has_core_sensor = True
    stream.rr_intervals = [[float(800 + 20 * np.sin(i / 11.0))] for i in range(n)]
    return stream


def _manifest(bundle):
    return {row["engine"]: row for row in bundle["engine_manifest"]}


def test_full_activity_bundle_runs_summary_intelligence_charts_and_manifest() -> None:
    bundle = build_full_activity_bundle(
        _rich_stream(),
        weight_kg=72.0,
        ftp=260.0,
        lthr=172.0,
        context=AthleteContext(),
        hrv_step_seconds=10.0,
        hrv_max_windows=500,
        file_id="synthetic.fit",
    )

    assert bundle["status"] == "success"
    assert bundle["workout_summary"]["status"] == "success"
    assert bundle["activity_intelligence"]["status"] == "success"
    assert bundle["activity_charts"]["_metadata"]["available_charts_count"] >= 5
    assert bundle["physiology_outputs"]["status"] == "success"
    assert "thermal" in bundle["physiology_outputs"]["exposed_keys"]
    assert "thermal_context" in bundle["physiology_outputs"]["exposed_keys"]

    manifest = _manifest(bundle)
    for engine in [
        "parse_report",
        "data_quality_report",
        "workout_summary",
        "activity_intelligence",
        "activity_charts",
        "power",
        "zones",
        "classification",
        "hrv",
        "cardiac",
        "statistics",
        "best_efforts_power",
        "cardiac_decoupling",
        "thermal_context",
        "physiology_outputs",
        "physiology_hrv",
        "physiology_cardiac",
        "physiology_thermal",
        "physiology_thermal_context",
        "physiology_thermal_adjusted_durability",
        "chart_power",
        "chart_heart_rate",
        "chart_thermal",
    ]:
        assert engine in manifest, engine
        assert manifest[engine]["status"] in {"success", "skipped", "partial", "error"}
        assert "output_path" in manifest[engine]

    assert manifest["power"]["status"] == "success"
    assert manifest["hrv"]["status"] == "success"
    assert manifest["cardiac"]["status"] == "success"
    assert manifest["thermal"]["status"] == "success"
    assert manifest["physiology_thermal"]["status"] == "success"
    assert manifest["chart_thermal"]["status"] == "success"
    assert bundle["manifest_summary"]["release_blockers"] == 0


def test_full_activity_bundle_never_hides_missing_optional_engines() -> None:
    stream = _rich_stream()
    stream.rr_intervals = [[] for _ in range(stream.n_samples)]
    stream.has_core_sensor = False
    stream.core_body_temp[:] = np.nan

    bundle = build_full_activity_bundle(
        stream,
        weight_kg=72.0,
        ftp=260.0,
        lthr=172.0,
        context=AthleteContext(),
    )
    manifest = _manifest(bundle)

    assert "hrv" in manifest
    assert manifest["hrv"]["status"] == "skipped"
    assert "rr" in manifest["hrv"].get("missing_signals", [])
    assert "thermal" in manifest
    assert manifest["thermal"]["status"] == "skipped"
    assert "core_temperature" in manifest["thermal"].get("missing_signals", [])
    assert "physiology_thermal" in manifest
    assert manifest["physiology_thermal"]["status"] == "skipped"
    assert "core_temperature" in manifest["physiology_thermal"].get("missing_signals", [])
    assert bundle["manifest_summary"]["total_engines"] == len(bundle["engine_manifest"])
