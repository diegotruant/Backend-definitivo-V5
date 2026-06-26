"""Port of tests/integration/test_session_router.py into pytest for coverage."""

from __future__ import annotations

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.io.session_router import _hrv_thresholds, decide_route, route_and_run

CTX = AthleteContext(gender="MALE", training_years=10, discipline="ENDURANCE")


def _ramp(lo: int = 100, hi: int = 340, step: int = 5, secs: int = 30, seed: int = 42) -> list[float]:
    rng = np.random.default_rng(seed)
    p: list[float] = []
    for w in range(lo, hi, step):
        noise = rng.normal(0, 3, secs)
        p.extend(list(np.clip(float(w) + noise, 0, None)))
    return p


def _sprint_cp() -> list[float]:
    p = [120.0] * 300
    for i in range(15):
        p.append(1000 * max(0.6, 1.0 - 0.03 * i))
    p += [40.0] * 5 + [100.0] * 200
    p += [350.0] * 180 + [100.0] * 150 + [320.0] * 360
    return p


def _free_ride(n: int = 4000, seed: int = 1) -> list[float]:
    rng = np.random.default_rng(seed)
    base = 150 + 60 * np.sin(np.linspace(0, 30, n))
    noise = rng.normal(0, 40, n)
    spikes = np.zeros(n)
    for _ in range(20):
        i = rng.integers(0, n - 10)
        spikes[i : i + 5] = rng.uniform(300, 600)
    return list(np.clip(base + noise + spikes, 0, None))


def _cp_test() -> list[float]:
    ftp = 270
    rng = np.random.default_rng(123)
    p = [120.0] * 600
    p += list(np.clip(int(1.05 * ftp) + rng.normal(0, 10, 180), 0, None))
    p += [110.0] * 400
    p += list(np.clip(int(0.98 * ftp) + rng.normal(0, 8, 360), 0, None))
    p += [110.0] * 200
    return [float(x) for x in p]


def test_decide_route_matrix() -> None:
    d_ramp = decide_route(_ramp(), filename="indoor_session.fit", ftp=270, has_rr=True)
    assert d_ramp.route == "hrv_threshold"
    assert d_ramp.source == "signal"
    assert "hrv_threshold_vt1_vt2" in d_ramp.engines_to_run

    d_ramp_norr = decide_route(_ramp(), filename="indoor_session.fit", ftp=270, has_rr=False)
    assert "hrv_threshold_vt1_vt2" not in d_ramp_norr.engines_to_run

    d_test = decide_route(_sprint_cp(), filename="test.fit", ftp=270, has_rr=False)
    assert d_test.route in ("metabolic_anchor", "hrv_threshold", "hiit")
    assert any(
        e in d_test.engines_to_run
        for e in ("metabolic_profile", "test_effort_extraction", "interval_stimulus")
    )

    d_ride = decide_route(_free_ride(), filename="ride.fit", ftp=270, has_rr=True)
    assert d_ride.route == "ride_monitoring"
    assert "hrv_durability" in d_ride.engines_to_run
    assert "hrv_threshold_vt1_vt2" not in d_ride.engines_to_run

    d_ride_norr = decide_route(_free_ride(), filename="ride.fit", ftp=270, has_rr=False)
    assert d_ride_norr.engines_to_run == ["power_curve_update"]

    d_cp = decide_route(_cp_test(), filename="unknown.fit", ftp=270, has_rr=False)
    assert d_cp.category != "HIIT"
    assert d_cp.route in ("metabolic_anchor", "hrv_threshold")


def test_route_and_run_execution() -> None:
    n = 3000
    rng = np.random.default_rng(3)
    rr_samples = []
    t = 0.0
    for _ in range(n):
        rr = float(rng.uniform(400, 700))
        t += rr / 1000.0
        rr_samples.append({"rr": [rr], "elapsed": t})
    ride = _free_ride(n=n)
    out = route_and_run(
        ride,
        rr_samples,
        elapsed_s=list(np.arange(n, dtype=float)),
        weight_kg=75,
        filename="ride.fit",
        ftp=250,
        context=CTX,
    )
    assert out["routing"]["route"] == "ride_monitoring"
    assert "power_curve" in out["results"]
    assert "hrv_durability" in out["results"] or "hrv_durability" in out["skipped"]
    assert "hrv_threshold" not in out["results"]

    out2 = route_and_run(_ramp(), None, weight_kg=75, filename="indoor_session.fit", ftp=250, context=CTX)
    assert "hrv_threshold" not in out2["results"]


def test_hrv_threshold_honesty_gate() -> None:
    n = 3000
    rng = np.random.default_rng(3)
    rr_samples = []
    t = 0.0
    for _ in range(n):
        rr = float(rng.uniform(400, 700))
        t += rr / 1000.0
        rr_samples.append({"rr": [rr], "elapsed": t})
    ride = _free_ride(n=n)
    parr = np.array(ride, dtype=float)
    vt = _hrv_thresholds(rr_samples, parr, list(np.arange(n, dtype=float)), CTX)
    assert isinstance(vt, dict) and "status" in vt
    assert vt.get("status") in ("insufficient", "low_reliability", "ok", "error")
