from __future__ import annotations

import numpy as np
import pytest
from pathlib import Path

from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import ActivityStreamEnhanced, parse_fit_file_enhanced
from engines.io.full_activity_bundle import (
    _component,
    _entry,
    _has,
    _hrv_for_charts,
    _path,
    _status,
    _valid,
    _zones_for_charts,
    build_full_activity_bundle,
)


class _BadArray:
    def __array__(self, dtype=None):
        raise TypeError("bad array")


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
        "durability_index",
        "durability_prescription",
        "np_drift",
        "hourly_decay_curve",
        "tte_sustainability",
        "metabolic_flexibility",
        "pedaling_balance",
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
    assert manifest["durability_index"]["status"] == "skipped"
    assert manifest["durability_index"]["reason"] == "insufficient_duration"
    assert manifest["durability_prescription"]["status"] == "skipped"
    assert manifest["np_drift"]["status"] == "success"
    assert manifest["hourly_decay_curve"]["status"] == "success"
    assert manifest["pedaling_balance"]["status"] == "success"
    assert bundle["manifest_summary"]["release_blockers"] == 0

    zone_chart = bundle["activity_charts"]["time_in_power_zone"]
    assert zone_chart.get("available") is True, zone_chart.get("reason")
    assert zone_chart.get("type") == "bar"
    assert zone_chart["series"][0]["data"]


def test_full_activity_bundle_durability_succeeds_on_long_enough_ride() -> None:
    stream = _rich_stream(n=7500)
    bundle = build_full_activity_bundle(
        stream, weight_kg=72.0, ftp=260.0, lthr=172.0, context=AthleteContext(),
    )
    manifest = _manifest(bundle)
    assert manifest["durability_index"]["status"] == "success"
    assert bundle["durability_index"]["durability_index"] > 0
    assert manifest["durability_prescription"]["status"] == "success"
    assert bundle["durability_prescription"]["focus"]


def test_full_activity_bundle_metabolic_flexibility_uses_snapshot() -> None:
    stream = _rich_stream()
    snapshot = {"status": "success", "fatmax_power_watts": 180.0, "mlss_power_watts": 250.0}
    bundle = build_full_activity_bundle(
        stream, weight_kg=72.0, ftp=260.0, context=AthleteContext(), metabolic_snapshot=snapshot,
    )
    manifest = _manifest(bundle)
    assert manifest["metabolic_flexibility"]["status"] == "success"
    assert bundle["metabolic_flexibility"]["mfi"] > 0

    bundle_no_snapshot = build_full_activity_bundle(
        _rich_stream(), weight_kg=72.0, ftp=260.0, context=AthleteContext(),
    )
    assert _manifest(bundle_no_snapshot)["metabolic_flexibility"]["status"] == "partial"


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


def test_manifest_status_and_component_helpers_cover_error_paths() -> None:
    assert _status(None) == ("skipped", "NO_OUTPUT")
    assert _status({"available": False, "reason": "missing"}) == ("skipped", "missing")
    assert _status({"status": "error", "error": "boom"}) == ("error", "boom")
    assert _status({"status": "failed", "reason": "bad"}) == ("error", "bad")
    assert _status({"status": "skipped", "reason": "nope"}) == ("skipped", "nope")
    assert _status({"status": "unavailable"}) == ("skipped", "unavailable")
    assert _status({"status": "partial"}) == ("partial", "PARTIAL_OUTPUT")
    assert _status({"status": "insufficient_duration"}) == ("skipped", "insufficient_duration")
    assert _status({"status": "ok"}) == ("success", None)
    assert _status({"some": "payload"}) == ("success", None)
    assert _status({}) == ("skipped", "EMPTY_OUTPUT")
    assert _status([]) == ("skipped", "EMPTY_OUTPUT")
    assert _status([1]) == ("success", None)
    assert _status("x") == ("success", None)

    value, row = _component("ok_engine", "out.path", lambda: {"status": "success"})
    assert value["status"] == "success"
    assert row == {"engine": "ok_engine", "status": "success", "output_path": "out.path"}

    value, row = _component("bad_engine", "out.path", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert value["status"] == "error"
    assert row["status"] == "error"
    assert row["reason"] == "boom"


def test_manifest_signal_detection_and_release_blocker_paths() -> None:
    stream = _rich_stream(n=120)
    assert _valid([np.nan, 3.0], min_value=1.0, max_value=5.0)
    assert not _valid(None)
    assert not _valid(_BadArray())
    assert not _valid([0.5], min_value=1.0)
    assert not _valid([9.0], max_value=5.0)

    metabolic = {"status": "success"}
    for signal in [
        "power",
        "heart_rate",
        "rr",
        "cadence",
        "altitude",
        "core_temperature",
        "ambient_temperature",
        "metabolic_snapshot",
    ]:
        assert _has(stream, signal, metabolic), signal
    assert not _has(stream, "unknown", metabolic)
    assert not _has(stream, "metabolic_snapshot", {"status": "error"})

    payload = {"a": {"b": {"c": 1}}}
    assert _path(payload, "a.b.c") == 1
    assert _path(payload, "a.x") is None
    assert _path({"a": 1}, "a.b") is None

    skipped = _entry("thermal", "missing.path", None, ("core_temperature",), stream, metabolic)
    assert skipped["status"] == "partial"
    assert skipped["reason"] == "REQUIRED_SIGNAL_PRESENT_OUTPUT_NOT_EXPOSED"
    assert skipped["attention"] == "release_blocker"

    stream.has_core_sensor = False
    missing = _entry("thermal", "missing.path", None, ("core_temperature",), stream, metabolic)
    assert missing["status"] == "skipped"
    assert missing["reason"] == "MISSING_REQUIRED_SIGNALS"
    assert missing["missing_signals"] == ["core_temperature"]


def test_chart_extractors_for_summary_shapes() -> None:
    coggan = {
        "available": True,
        "zones": [{"name": "Z1", "low": 0, "high": 150}],
    }
    assert _zones_for_charts({"sections": {"zones": {"coggan_power": coggan}}}) == coggan["zones"]
    assert _zones_for_charts({"sections": {"zones": {"metabolic_power": coggan}}}) == coggan["zones"]
    assert _zones_for_charts({"sections": {"zones": {"power_zones": [{"name": "Z1"}]}}}) == [{"name": "Z1"}]
    assert _zones_for_charts({"sections": {"zones": {"power_zones": {"zones": [{"name": "Z2"}]}}}}) == [{"name": "Z2"}]
    assert _zones_for_charts({"sections": {"zones": {"power_zones": {"time_in_zone": [{"name": "Z3"}]}}}}) == [{"name": "Z3"}]
    assert _zones_for_charts({"sections": {"zones": {"power_zones": {"distribution": [{"name": "Z4"}]}}}}) == [{"name": "Z4"}]
    assert _zones_for_charts({"sections": {"zones": {"coggan_power": {"available": False, "zones": [{"name": "Z9"}]}}}}) == []
    assert _zones_for_charts({"sections": {"zones": {}}}) == []

    assert _hrv_for_charts({"sections": {"hrv": {"available": True, "time_in_intensity": {}}}}) == {
        "available": True,
        "time_in_intensity": {},
    }
    assert _hrv_for_charts({"sections": {"hrv": {"available": False}}}) is None
    assert _hrv_for_charts({"sections": {}}) is None


def test_full_activity_bundle_tolerates_malformed_critical_power(monkeypatch: pytest.MonkeyPatch) -> None:
    from engines.io.workout_summary import build_workout_summary

    base = build_workout_summary(_rich_stream(n=120), weight_kg=72.0, ftp=260.0, lthr=172.0)

    def fake_summary(*_args, **_kwargs):
        out = dict(base)
        sections = dict(out.get("sections") or {})
        power = dict(sections.get("power") or {})
        power["critical_power"] = "not-a-dict"
        sections["power"] = power
        out["sections"] = sections
        return out

    monkeypatch.setattr("engines.io.full_activity_bundle.build_workout_summary", fake_summary)
    bundle = build_full_activity_bundle(
        _rich_stream(n=120),
        weight_kg=72.0,
        ftp=260.0,
        lthr=172.0,
        context=AthleteContext(),
    )
    assert bundle["status"] in {"success", "partial"}
    assert bundle["activity_intelligence"]["status"] == "success"


def test_full_activity_bundle_counts_release_blockers(monkeypatch: pytest.MonkeyPatch) -> None:
    from engines.io.workout_summary import build_workout_summary

    base = build_workout_summary(_rich_stream(n=120), weight_kg=72.0, ftp=260.0, lthr=172.0)

    def fake_summary(*_args, **_kwargs):
        out = dict(base)
        sections = dict(out.get("sections") or {})
        sections.pop("thermal", None)
        out["sections"] = sections
        return out

    monkeypatch.setattr("engines.io.full_activity_bundle.build_workout_summary", fake_summary)
    bundle = build_full_activity_bundle(
        _rich_stream(n=120),
        weight_kg=72.0,
        ftp=260.0,
        lthr=172.0,
        context=AthleteContext(),
    )
    assert bundle["manifest_summary"]["release_blockers"] >= 1
    assert bundle["status"] == "partial"


def test_activity_charts_legacy_dict_and_forward_fill_helpers() -> None:
    from engines.io.activity_charts import (
        _forward_fill_nan,
        chart_cadence,
        chart_heart_rate,
        chart_power,
        chart_time_in_intensity,
    )

    assert _forward_fill_nan(np.array([]), default_val=5.0).size == 0
    chart = chart_time_in_intensity({"time_in_intensity": {"fat_min": 12.0, "carb_min": 28.0}})
    assert chart["type"] == "bar"
    assert chart["series"][0]["data"] == [12.0, 28.0]

    class NoSignals:
        time = [0.0, 1.0, 2.0]
        power = None
        heart_rate = None
        cadence = None

    assert chart_power(NoSignals())["available"] is False
    assert chart_heart_rate(NoSignals())["available"] is False
    assert chart_cadence(NoSignals())["available"] is False


def test_activity_intelligence_chart_and_decoupling_edge_paths() -> None:
    from engines.io.activity_intelligence import build_chart_series, compute_cardiac_decoupling
    from engines.io.fit_parser import ActivityStreamEnhanced

    empty = ActivityStreamEnhanced(n_samples=0, sport="cycling", total_elapsed_s=0.0)
    assert build_chart_series(empty)["reason"] == "empty_stream"

    class MismatchPower:
        n_samples = 100
        elapsed_s = np.arange(100, dtype=np.float32)
        power = np.array([200.0] * 10, dtype=np.float32)
        heart_rate = np.full(100, 140.0, dtype=np.float32)

    chart = build_chart_series(MismatchPower())
    assert chart["status"] == "success"
    assert "power_w" not in chart["series"]

    sparse = _rich_stream(n=1500)
    sparse.power = np.where(np.arange(1500) % 20 == 0, 200.0, 0.0).astype(np.float32)
    sparse.heart_rate = np.full(1500, 140.0, dtype=np.float32)
    skipped = compute_cardiac_decoupling(sparse, min_duration_s=1200)
    assert skipped["reason"] == "insufficient_valid_samples"

    uneven = _rich_stream(n=1500)
    uneven.power = np.concatenate(
        [np.full(700, 220.0, dtype=np.float32), np.zeros(800, dtype=np.float32)]
    )
    uneven.heart_rate = np.full(1500, 140.0, dtype=np.float32)
    halves = compute_cardiac_decoupling(uneven, min_duration_s=1200)
    assert halves["reason"] == "insufficient_halves"


def test_manual_load_and_progression_levels_invalid_inputs() -> None:
    from engines.load.manual_load import calculate_manual_load
    from engines.workouts.progression_levels import compute_progression_levels

    bad_rpe = calculate_manual_load(duration_min=30, rpe="not-a-number")
    assert bad_rpe["input"]["rpe"] == 0.0

    profile = {"ftp": 250, "weight_kg": 70}
    history = [{"target_zone": "threshold", "compliance_score": "bad"}]
    out = compute_progression_levels(profile, workout_history=history)
    assert out["status"] == "success"


def test_data_quality_report_none_values_and_gps_channels() -> None:
    from engines.io.data_quality_report import _series_quality, build_data_quality_report
    from engines.io.fit_parser import ActivityStreamEnhanced

    assert _series_quality(None, measured=True)["notes"] == ["missing_signal"]

    stream = ActivityStreamEnhanced(n_samples=3, sport="cycling", total_elapsed_s=3.0)
    stream.power = np.array([200.0, 210.0, 205.0], dtype=np.float32)
    stream.heart_rate = np.array([130.0, 135.0, 140.0], dtype=np.float32)
    stream.cadence = np.array([90.0, 91.0, 92.0], dtype=np.float32)
    stream.lat = np.array([45.0, 45.1, 45.2], dtype=np.float64)
    stream.lon = np.array([9.0, 9.1, 9.2], dtype=np.float64)
    report = build_data_quality_report(stream)
    assert "latitude" in report["available_signals"]
    assert "longitude" in report["available_signals"]


FIT_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "fit"

POWER_FIT_CASES = [
    "minimal_power_hr_lap_hrv",
    "garmin_power_hr",
    "garmin_rr_hrv",
    "wahoo_power_cadence",
    "indoor_trainer_erg",
    "zwift_virtual",
]


@pytest.mark.parametrize("stem", POWER_FIT_CASES)
def test_full_activity_bundle_time_in_power_zone_on_real_fit(stem: str) -> None:
    """E2E: workout_summary zones use coggan_power keys; bundle charts must wire them."""
    fit_path = FIT_ASSET_DIR / f"{stem}.fit"
    if not fit_path.exists():
        pytest.skip(f"missing FIT asset: {fit_path.name}")

    stream = parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
    if not getattr(stream, "has_power", False):
        pytest.skip(f"{stem} has no power stream")

    bundle = build_full_activity_bundle(
        stream,
        weight_kg=72.0,
        ftp=250.0,
        lthr=170.0,
        context=AthleteContext(),
        file_id=f"{stem}.fit",
    )
    zones_section = ((bundle["workout_summary"].get("sections") or {}).get("zones") or {})
    coggan = zones_section.get("coggan_power") or {}
    assert coggan.get("available") is True, coggan.get("reason")

    zone_chart = bundle["activity_charts"]["time_in_power_zone"]
    assert zone_chart.get("available") is True, zone_chart.get("reason")
    assert zone_chart.get("type") == "bar"
    assert sum(zone_chart["series"][0]["data"]) > 0


def test_full_activity_bundle_time_in_power_zone_unavailable_without_power_fit() -> None:
    fit_path = FIT_ASSET_DIR / "no_power_hr_only.fit"
    if not fit_path.exists():
        pytest.skip("missing FIT asset")

    stream = parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
    bundle = build_full_activity_bundle(
        stream,
        weight_kg=72.0,
        ftp=250.0,
        lthr=170.0,
        context=AthleteContext(),
        file_id="no_power_hr_only.fit",
    )
    zone_chart = bundle["activity_charts"]["time_in_power_zone"]
    assert zone_chart.get("available") is False
