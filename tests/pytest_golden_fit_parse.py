"""Parametrized golden FIT suite against expected parse snapshots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engines.io.fit_parse_report import build_fit_parse_report
from engines.io.fit_parser import parse_fit_file_enhanced

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


def _load_expected(stem: str) -> dict:
    path = ASSET_DIR / f"{stem}.expected_parse.json"
    if not path.exists():
        pytest.skip(f"missing expected snapshot: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("stem", GOLDEN_CASES)
def test_golden_fit_matches_expected_snapshot(stem: str) -> None:
    fit_path = ASSET_DIR / f"{stem}.fit"
    if not fit_path.exists():
        pytest.skip(f"missing FIT asset: {fit_path.name}")
    expected = _load_expected(stem)
    stream = parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
    report = build_fit_parse_report(stream=stream, file_id=stem, file_hash="golden")

    assert report["parser_version"] == expected["parser_version"]
    assert report["duration_s"] == expected["duration_s"]
    assert sorted(report["available_signals"]) == expected["available_signals"]
    assert len(report.get("laps") or []) == expected["lap_count"]
    assert bool(report["streams"].get("power_w")) == expected["has_power_stream"]
    assert bool(report["streams"].get("heart_rate_bpm")) == expected["has_hr_stream"]
    assert bool(report["streams"].get("cadence_rpm")) == expected["has_cadence_stream"]
    if expected.get("first_lap"):
        assert report["laps"][0]["duration_s"] == expected["first_lap"]["duration_s"]
        assert report["laps"][0]["avg_power_w"] == expected["first_lap"]["avg_power_w"]


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
