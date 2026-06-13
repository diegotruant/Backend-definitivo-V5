from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api_app import app
from engines.io.activity_statistics import compute_activity_statistics
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.io.workout_summary import build_workout_summary
from engines.performance.power_engine import normalized_power
from tests.fixtures.synthetic_fit import (
    build_synthetic_fit_bytes,
    parse_synthetic_fit,
    sample_endurance_records,
    write_synthetic_fit,
)

ASSETS = Path(__file__).resolve().parent / "assets"
SYNTHETIC_FIT = ASSETS / "synthetic_ride.fit"


@pytest.fixture(scope="module")
def rich_stream():
    """Parsed FIT-like stream with power, HR, cadence, altitude, speed, temperature."""
    start = datetime(2026, 3, 15, 9, 0, 0)
    records = []
    for i in range(3600):
        records.append(
            {
                "timestamp": start + timedelta(seconds=i),
                "power": 200 + (i % 120) * 0.5,
                "heart_rate": 135 + (i % 60) * 0.2,
                "cadence": 88 + (i % 30) * 0.1,
                "enhanced_altitude": 200.0 + i * 0.05 + (50 if 1200 <= i < 1800 else 0),
                "speed": 8.5 + (0.5 if i % 300 < 60 else 0.0),
                "temperature": 18.0 + (i % 600) * 0.001,
            }
        )
    return parse_fit_records_enhanced(
        records,
        session_dict={"sport": "cycling", "start_time": start, "total_elapsed_s": 3600},
    )


def test_compute_activity_statistics_power_and_hr(rich_stream) -> None:
    out = compute_activity_statistics(rich_stream, weight_kg=72.0, ftp=280.0, lthr=165.0)
    m = out["metrics"]
    assert out["status"] == "success"
    assert m["avg_power_w"] is not None
    assert m["np_w"] is not None
    assert m["max_power_w"] is not None
    assert m["work_kj"] is not None
    assert m["avg_hr_bpm"] is not None
    assert m["max_hr_bpm"] is not None
    assert m["avg_power_w_kg"] == round(m["avg_power_w"] / 72.0, 2)
    assert m["np_w_kg"] == round(m["np_w"] / 72.0, 2)


def test_compute_activity_statistics_altitude_speed_temperature(rich_stream) -> None:
    out = compute_activity_statistics(rich_stream, weight_kg=72.0)
    m = out["metrics"]
    assert m["ascent_m"] is not None and m["ascent_m"] > 0
    assert m["descent_m"] is not None
    assert m["temperature_avg_c"] is not None
    assert m["speed_avg_kmh"] is not None
    assert m["moving_speed_avg_kmh"] is not None
    assert m["avg_cadence_rpm"] is not None


def test_np_matches_power_engine_convention(rich_stream) -> None:
    power = np.array([float(p or 0) for p in rich_stream.power], dtype=float)
    stats = compute_activity_statistics(rich_stream, weight_kg=70.0)["metrics"]
    assert stats["np_w"] == round(normalized_power(power), 1)


def test_build_workout_summary_includes_statistics_page(rich_stream) -> None:
    summary = build_workout_summary(rich_stream, weight_kg=72.0, ftp=280.0, lthr=165.0)
    assert summary["status"] == "success"
    assert "statistics_page" in summary
    assert summary["statistics_page"]["np_w"] is not None
    assert summary["sections"]["statistics"]["status"] == "success"
    assert set(summary["statistics_page"]) >= {
        "avg_power_w",
        "np_w",
        "work_kj",
        "avg_hr_bpm",
    }


def test_synthetic_fit_file_roundtrip(tmp_path) -> None:
    records = sample_endurance_records(duration_s=1200)
    fit_path = write_synthetic_fit(tmp_path / "ride.fit", records)
    raw = fit_path.read_bytes()
    stream = parse_synthetic_fit(raw)
    assert stream.has_power
    assert stream.n_samples > 1000
    stats = compute_activity_statistics(stream, weight_kg=75.0, ftp=260.0)
    assert stats["metrics"]["avg_power_w"] is not None


def test_committed_synthetic_fit_asset() -> None:
    """Regression on a real binary FIT-like file checked into tests/assets/."""
    if not SYNTHETIC_FIT.is_file():
        write_synthetic_fit(SYNTHETIC_FIT, sample_endurance_records(duration_s=1800))
    stream = parse_synthetic_fit(SYNTHETIC_FIT.read_bytes())
    summary = build_workout_summary(stream, weight_kg=72.0, ftp=270.0)
    page = summary["statistics_page"]
    assert page["avg_power_w"] is not None
    assert page["max_power_w"] is not None
    assert page["work_kj"] is not None


def test_ride_summary_http_returns_statistics_page(rich_stream) -> None:
    power = [int(p or 0) for p in rich_stream.power[:600]]
    client = TestClient(app)
    resp = client.post(
        "/ride/summary",
        data={
            "weight_kg": "72",
            "ftp": "280",
            "power_json": json.dumps(power),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    assert "statistics_page" in body
    assert body["statistics_page"]["np_w"] is not None


def test_synthetic_fit_bytes_match_parser_layout() -> None:
    raw = build_synthetic_fit_bytes(sample_endurance_records(300))
    assert raw[:12] == b"\x00" * 12
    stream = parse_synthetic_fit(raw)
    assert stream.has_power
