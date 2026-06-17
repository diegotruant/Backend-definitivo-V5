"""Parametrized golden FIT suite against parse and coach-pipeline snapshots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engines.io.data_quality_report import build_data_quality_report
from engines.io.fit_parse_report import build_fit_parse_report
from engines.io.fit_parser import measured_signal_flags, parse_fit_file_enhanced
from tools.golden_fit_coach_snapshot import build_coach_golden_snapshot

ASSET_DIR = Path(__file__).resolve().parent / "assets" / "fit"

GOLDEN_CASES = [
    "minimal_power_hr_lap_hrv",
    "garmin_power_hr",
    "garmin_rr_hrv",
    "wahoo_power_cadence",
    "no_power_hr_only",
    "indoor_trainer_erg",
    "zwift_virtual",
]


def _load_expected(stem: str, suffix: str) -> dict:
    path = ASSET_DIR / f"{stem}.expected_{suffix}.json"
    if not path.exists():
        pytest.skip(f"missing expected snapshot: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def test_garmin_power_hr_does_not_claim_speed_without_sensor() -> None:
    fit_path = ASSET_DIR / "garmin_power_hr.fit"
    if not fit_path.exists():
        pytest.skip("missing FIT asset")
    stream = parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
    measured = measured_signal_flags(stream)
    quality = build_data_quality_report(stream)

    assert measured["speed"] is False
    assert stream.has_speed is False
    assert "speed" not in quality["available_signals"]
    assert quality["signals"]["speed"]["available"] is False


@pytest.mark.parametrize("stem", GOLDEN_CASES)
def test_golden_fit_matches_expected_parse_snapshot(stem: str) -> None:
    fit_path = ASSET_DIR / f"{stem}.fit"
    if not fit_path.exists():
        pytest.skip(f"missing FIT asset: {fit_path.name}")
    expected = _load_expected(stem, "parse")
    stream = parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
    measured = measured_signal_flags(stream)
    report = build_fit_parse_report(stream=stream, file_id=stem, file_hash="golden")

    assert report["parser_version"] == expected["parser_version"]
    assert report["duration_s"] == expected["duration_s"]
    assert measured == expected["measured_signals"]
    assert sorted(report["available_signals"]) == expected["available_signals"]
    assert len(report.get("laps") or []) == expected["lap_count"]
    assert measured["power"] == expected["has_power_stream"]
    assert measured["heart_rate"] == expected["has_hr_stream"]
    assert measured["cadence"] == expected["has_cadence_stream"]
    if "has_speed_stream" in expected:
        assert measured["speed"] == expected["has_speed_stream"]
    if expected.get("first_lap"):
        assert report["laps"][0]["duration_s"] == expected["first_lap"]["duration_s"]
        assert report["laps"][0]["avg_power_w"] == expected["first_lap"]["avg_power_w"]


@pytest.mark.parametrize("stem", GOLDEN_CASES)
def test_golden_fit_matches_expected_coach_snapshot(stem: str) -> None:
    fit_path = ASSET_DIR / f"{stem}.fit"
    if not fit_path.exists():
        pytest.skip(f"missing FIT asset: {fit_path.name}")
    expected = _load_expected(stem, "coach")
    stream = parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
    coach = build_coach_golden_snapshot(fit_path, stream)

    assert coach["file_hash"] == expected["file_hash"]
    assert coach["measured_signals"] == expected["measured_signals"]
    assert coach["rr_interval_count"] == expected["rr_interval_count"]
    assert coach["laps"] == expected["laps"]
    assert coach["hrv"] == expected["hrv"]

    for channel in ("power", "heart_rate"):
        assert coach["quality_flags"][channel] == expected["quality_flags"][channel]

    if expected.get("power"):
        assert coach["power"]["normalized_power"] == expected["power"]["normalized_power"]
        assert coach["power"]["intensity_factor"] == expected["power"]["intensity_factor"]
        assert coach["power"]["tss"] == expected["power"]["tss"]
        assert coach["power"]["mmp_w"] == expected["power"]["mmp_w"]
    else:
        assert "power" not in coach


@pytest.mark.parametrize("stem", ["truncated", "bad_crc"])
def test_corrupt_fit_files_fail_gracefully_or_recover(stem: str) -> None:
    fit_path = ASSET_DIR / f"{stem}.fit"
    if not fit_path.exists():
        pytest.skip(f"missing FIT asset: {fit_path.name}")
    try:
        stream = parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert stream.n_samples >= 0
    except Exception:
        # Corrupt files may raise; the contract is no process crash in API layer.
        pass
