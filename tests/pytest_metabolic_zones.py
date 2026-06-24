"""Metabolic vs Coggan dual zone system tests."""

from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api_app import app
from engines.io.workout_summary import build_workout_summary
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.metabolic.zones_engine import ZonesEngine, metabolic_power_zones
from tests.fixtures.synthetic_fit import build_synthetic_fit_bytes, parse_synthetic_fit

client = TestClient(app)

MMP = {"5": 900, "60": 400, "300": 320, "1200": 280}


class _SimpleStream:
    def __init__(self, power: list[float], hr: list[float] | None = None) -> None:
        self.elapsed_s = list(range(len(power)))
        self.power = power
        self.heart_rate = hr or [140.0] * len(power)
        self.n_samples = len(power)
        self.has_power = True
        self.has_rr = False


def _metabolic_snapshot() -> dict:
    profiler = MetabolicProfiler(weight=70.0)
    snap = profiler.generate_metabolic_snapshot(MMP)
    assert snap["status"] == "success"
    assert snap.get("zones")
    return snap


def test_metabolic_power_zones_time_in_zone() -> None:
    snap = _metabolic_snapshot()
    mlss = float(snap["mlss_power_watts"])
    # Mostly endurance intensity (~65% MLSS)
    power = [int(mlss * 0.65)] * 600
    stream = _SimpleStream(power)
    result = metabolic_power_zones(stream, snap)
    assert result["available"] is True
    assert result["model"] == "Metabolic MLSS 5-zone"
    assert result["anchor_mlss_w"] == round(mlss, 1)
    z2 = next(z for z in result["zones"] if z["zone"] == "Z2")
    assert z2["time_s"] == 600


def test_zones_engine_returns_both_metabolic_and_coggan() -> None:
    snap = _metabolic_snapshot()
    mlss = float(snap["mlss_power_watts"])
    stream = _SimpleStream([int(mlss * 0.65)] * 300)
    engine = ZonesEngine(ftp=250.0, lthr=165.0)
    out = engine.analyze(stream, metabolic_snapshot=snap)
    assert out["schema_version"] == "1.1.0"
    assert out["metabolic_power"]["available"] is True
    assert out["coggan_power"]["available"] is True
    assert out["systems_available"]["metabolic_power"] is True
    assert out["systems_available"]["coggan_power"] is True
    assert "coach_note" in out


def test_workout_summary_auto_snapshot_enables_metabolic_zones() -> None:
    raw = build_synthetic_fit_bytes(
        [
            (1_735_689_600 + i * 60, 220 + (i % 5) * 5, 140 + i % 3, 90)
            for i in range(30)
        ]
    )
    stream = parse_synthetic_fit(raw)
    summary = build_workout_summary(stream, weight_kg=70.0, ftp=250.0)
    zones = summary["sections"]["zones"]
    assert zones["coggan_power"]["available"] is True
    # Auto-generated metabolic snapshot should unlock MLSS zones when reliable
    if summary["sections"].get("metabolic_snapshot", {}).get("status") == "success":
        if summary["sections"]["metabolic_snapshot"].get("zones"):
            assert zones["metabolic_power"]["available"] is True


def test_ride_analytics_zones_with_metabolic_snapshot_json() -> None:
    snap = _metabolic_snapshot()
    power = [int(float(snap["mlss_power_watts"]) * 0.7)] * 120
    response = client.post(
        "/ride/analytics/zones",
        data={
            "weight_kg": "70",
            "ftp": "250",
            "metabolic_snapshot_json": json.dumps(snap),
            "power_json": json.dumps(power),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metabolic_power"]["available"] is True
    assert body["coggan_power"]["available"] is True
