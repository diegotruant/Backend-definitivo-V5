"""Golden FIT parse regression tests using committed real FIT binaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from engines.io.fit_parser import FIT_PARSER_VERSION, parse_fit_file_enhanced

ASSET = Path(__file__).resolve().parent / "assets" / "fit" / "minimal_power_hr_lap_hrv.fit"


@pytest.mark.skipif(not ASSET.exists(), reason="golden FIT asset missing")
def test_golden_fit_roundtrip_via_fitdecode_path() -> None:
    stream = parse_fit_file_enhanced(str(ASSET), repair_synthetic_header=False)
    assert stream.n_samples >= 60
    assert stream.has_power
    assert stream.has_heart_rate
    assert len(stream.laps) == 1
    assert stream.laps[0]["duration_s"] == 120
    assert stream.laps[0]["avg_power_w"] == 226
    assert stream.data_provenance["source"] == "fit_file"
    assert "power" in stream.data_provenance["measured_signals"]
    assert stream.data_provenance.get("synthetic_signals") == []


@pytest.mark.skipif(not ASSET.exists(), reason="golden FIT asset missing")
def test_golden_fit_hrv_messages_do_not_crash_parser() -> None:
    stream = parse_fit_file_enhanced(str(ASSET), repair_synthetic_header=False)
    # HRV may or may not map into per-second RR buckets depending on timing;
    # the contract here is that dedicated HRV messages never crash parsing.
    assert FIT_PARSER_VERSION
