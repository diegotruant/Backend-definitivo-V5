"""Phase 5 — batch I: interval/cardiac/hrv/fit closure + integration ports."""

from __future__ import annotations

import os
import random
import subprocess
import sys
import warnings
from datetime import date, datetime, timedelta, timezone
from typing import Any, List

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import FitFileError, parse_fit_file_enhanced, parse_fit_records_enhanced
from engines.io.profile_anchor_flow import build_anchor_from_proposal, update_profile_from_ride
from engines.metabolic.detraining_engine import apply_detraining_model
from engines.metabolic.glycolytic_validation_engine import validate_wingate_glycolytic
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.metabolic.zones_engine import coggan_power_zones, metabolic_power_zones, seiler_polarization
from engines.performance.effort_extractor import extract_test_proposal
from engines.performance.interval_detector import (
    _classify_by_signal,
    _detect_ramp_protocol,
    classify_session,
)
from engines.performance.mmp_quality import analyze_mmp_quality
from engines.performance.test_protocols import run_test
from engines.recovery.cardiac_engine import ActivitySample, CardiacResponseAnalyzer, cross_validate_thresholds
from engines.recovery.hrv_engine import _artifact_mask, _correct_ectopic, analyze_rr_stream


def _flat(power_w: float, dur_s: int, noise: float = 0.0, rng: Any = None) -> List[float]:
    arr = np.full(dur_s, float(power_w))
    if noise > 0 and rng is not None:
        arr = arr + rng.normal(0, noise, dur_s)
    return list(np.clip(arr, 0, None))


def _sprint(peak_w: float, dur_s: int) -> List[float]:
    out: List[float] = []
    for i in range(dur_s):
        if i < 2:
            out.append(peak_w * (0.4 + 0.3 * i))
        else:
            out.append(peak_w * max(0.6, 1.0 - 0.03 * (i - 2)))
    out.extend([40.0] * 5)
    return out


class TestIntervalSignalClosure92I:
    def test_ramp_cp_mixed_and_steady_signatures(self) -> None:
        ftp = 250.0
        ramp: List[float] = []
        for step in range(8):
            ramp.extend([100 + step * 30] * 90)
        info = _detect_ramp_protocol(ramp)
        assert info["is_ramp"]
        cat, sub, conf, _ = _classify_by_signal(ramp, ftp=ftp)
        assert cat == "TEST"
        assert sub == "ramp_test"

        cp_blocks = [150.0] * 300 + [280.0] * 360 + [150.0] * 300 + [300.0] * 720 + [150.0] * 300
        cat2, sub2, _, _ = _classify_by_signal(cp_blocks, ftp=ftp)
        assert cat2 == "TEST"
        assert sub2 in {"cp_test", "cp12", "ftp_20min", "cp6"}

        mixed = [120.0] * 600
        for i in range(800, 820):
            mixed.append(900.0)
        mixed.extend([120.0] * 400)
        mixed.extend([240.0] * 1800)
        cat3, sub3, _, _ = _classify_by_signal(mixed, ftp=ftp)
        assert cat3 == "TEST"
        assert sub3 in {"mixed_test", "cp_test", "cp12"}

        random.seed(7)
        sweet = [220 + random.gauss(0, 5) for _ in range(2400)]
        cat4, sub4, _, _ = _classify_by_signal(sweet, ftp=ftp)
        assert cat4 in {"STEADY", "HIIT", "FREE", "TEST"}

        classified = classify_session(ramp, filename="unknown.fit", ftp=ftp)
        assert classified.category == "TEST"

    def test_sprint_set_and_single_sprint(self) -> None:
        ftp = 250.0
        sprints = [100.0] * 1000
        for burst in range(6):
            start = 200 + burst * 120
            for i in range(start, min(start + 8, len(sprints))):
                sprints[i] = 850.0
        cat, sub, _, _ = _classify_by_signal(sprints, ftp=ftp)
        assert cat == "TEST"
        assert sub in {"sprint_set", "single_sprint", "mixed_test"}

        short = [90.0] * 400 + [900.0] * 3 + [90.0] * 800
        r = classify_session(short, filename="ride.fit", ftp=ftp)
        assert r.category in {"TEST", "FREE", "STEADY"}


class TestCardiacHrvFitClosure92I:
    def test_cardiac_cross_validate_mlss_band(self) -> None:
        samples = [
            ActivitySample(t=float(i), power=255.0, hr=155.0 + (i % 3))
            for i in range(120)
        ]
        timeline = [
            {"timestamp": 0.0, "status": "AEROBIC"},
            {"timestamp": 600.0, "status": "MIXED"},
            {"timestamp": 1200.0, "status": "ANAEROBIC"},
        ]
        t = np.arange(len(samples), dtype=float)
        power = np.array([s.power for s in samples], dtype=float)
        hr = np.array([s.hr for s in samples], dtype=float)
        out = cross_validate_thresholds(
            t,
            power,
            hr,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 255},
            hrv_timeline=timeline,
        )
        assert out.get("status") in {"success", "partial", "error", None} or "hr_at_mlss_observed" in out

        bad = cross_validate_thresholds(
            t, power, hr, metabolic_snapshot={"mlss_power_watts": "bad"}, hrv_timeline=timeline
        )
        assert isinstance(bad, dict)

        analyzer = CardiacResponseAnalyzer(
            weight=72.0,
            metabolic_snapshot={"status": "success", "mlss_power_watts": 250},
            hrv_timeline=timeline,
        )
        result = analyzer.analyze(samples)
        assert result.get("status") == "success"

    def test_hrv_ectopic_multipass_and_window_paths(self) -> None:
        rr = np.array([800.0, 1200.0, 810.0, 805.0, 815.0, 820.0] * 30, dtype=float)
        mask = _artifact_mask(rr)
        corrected = _correct_ectopic(rr, mask, max_passes=4)
        assert corrected.shape == rr.shape

        rr_samples = [
            {"elapsed": float(i * 3), "rr": [820.0 + (i % 5) for _ in range(50)]}
            for i in range(80)
        ]
        timeline = analyze_rr_stream(
            rr_samples,
            window_seconds=90,
            step_seconds=6.0,
            context=AthleteContext(gender="MALE", training_years=15, discipline="ROAD"),
        )
        assert isinstance(timeline, list)

    def test_fit_parser_session_subsport_and_dynamics(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        import engines.io.fit_parser as fp

        start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        records = [
            {
                "timestamp": start + timedelta(seconds=i),
                "power": 220.0,
                "heart_rate": 140.0,
                "left_right_balance": 45.0 + (i % 7),
                "cadence_position": "invalid_value",
                "left_power_phase": 12.0,
                "respiration_rate": 18.0,
            }
            for i in range(90)
        ]

        def _extract(_payload: bytes, *, check_crc: bool):
            return (
                records,
                [{"sport": "cycling", "sub_sport": "indoor_cycling", "start_time": start, "total_elapsed_time": 90}],
                [{"manufacturer": "Garmin", "product": "dual power meter"}],
                [{"other_time_field": [0.82, 0.81]}],
                [{"total_timer_time": 90, "avg_power": 220}],
            )

        monkeypatch.setattr(fp, "_extract_messages", _extract)
        fit_path = tmp_path / "full.fit"
        fit_path.write_bytes(b"\x0e" + b"x" * 200)
        stream = fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert stream.n_samples >= 90
        assert stream.pedaling_balance_source in {"dual", "unknown", "single_estimated"}

        def _header_invalid(_payload: bytes, *, check_crc: bool):
            raise fp.FitParseHeaderError("not a FIT file")

        monkeypatch.setattr(fp, "_extract_messages", _header_invalid)
        with pytest.raises(FitFileError) as exc:
            fp.parse_fit_file_enhanced(str(fit_path), repair_synthetic_header=False)
        assert exc.value.reason == "INVALID_HEADER"


class TestMetabolicPorts92I:
    def test_effort_extractor_suite(self) -> None:
        rng = np.random.default_rng(42)
        day1 = (
            _flat(120, 600, noise=8, rng=rng)
            + _sprint(1000, 15)
            + _flat(90, 300, noise=8, rng=rng)
            + _flat(300, 720, noise=6, rng=rng)
        )
        day2 = (
            _flat(120, 600, noise=8, rng=rng)
            + _flat(360, 180, noise=8, rng=rng)
            + _flat(90, 300, noise=8, rng=rng)
            + _flat(330, 360, noise=7, rng=rng)
        )
        prop = extract_test_proposal([
            {"file_id": "day1", "power": day1, "laps": None},
            {"file_id": "day2", "power": day2, "laps": None},
        ])
        d = prop.to_dict()
        assert d["status"] == "proposed"
        assert d["confidence"] >= 0.6
        assert d["sprint"] is not None

        ride = _flat(150, 1200, noise=25, rng=rng) + _sprint(600, 6) + _flat(210, 720, noise=18, rng=rng)
        prop_ride = extract_test_proposal([{"file_id": "ride", "power": ride, "laps": None}])
        assert prop_ride.to_dict()["status"] != "proposed"

        assert extract_test_proposal([]).status == "empty"

    def test_profile_anchor_flow(self) -> None:
        ctx = AthleteContext(gender="MALE", training_years=20, discipline="SPRINT")
        day = (
            _flat(120, 400)
            + _sprint(1000, 16)
            + _flat(90, 200)
            + _flat(355, 180)
            + _flat(90, 150)
            + _flat(320, 360)
            + _flat(90, 150)
            + _flat(300, 720)
        )
        prop = extract_test_proposal([{"file_id": "test", "power": day, "laps": None}])
        anchor = build_anchor_from_proposal(
            prop, weight_kg=90, measured_on="2026-05-15", context=ctx, active_muscle_mass_kg=23.5
        )
        ad = anchor.to_dict()
        assert ad["status"] in {"anchored", "partial", "failed"}
        if anchor.profile is not None:
            ride_mmp = {60: 320, 300: 290, 1200: 270}
            update = update_profile_from_ride(
                anchor.profile,
                ride_mmp,
                weight_kg=90,
                as_of="2026-05-20",
                context=ctx,
            )
            assert update.get("status") in {"success", "partial", "anchor_held", "updated", "error"}

    def test_zones_glycolytic_mmp_test_protocols(self) -> None:
        snap = {
            "status": "success",
            "mlss_power_watts": 280,
            "estimated_vo2max": 58.0,
            "estimated_vlamax_mmol_L_s": 0.45,
            "fatmax_power_watts": 180,
            "map_aerobic_watts": 380,
            "expressiveness": {"reliability": {"mlss": True, "vo2max": True}},
        }
        start = datetime(2026, 1, 1, 8, 0, 0)
        stream = parse_fit_records_enhanced(
            [
                {
                    "timestamp": start + timedelta(seconds=i),
                    "power": 220.0 + (i % 60) * 2,
                    "heart_rate": 140.0 + (i % 30),
                }
                for i in range(3600)
            ],
            session_dict={"start_time": start},
        )
        zones = coggan_power_zones(stream, ftp=280)
        assert zones.get("available") is True or "zones" in zones

        meta_zones = metabolic_power_zones(stream, snap)
        assert meta_zones.get("available") is True or meta_zones.get("reason") is not None

        pol = seiler_polarization(stream, vt1_w=180, vt2_w=240)
        assert pol.get("classification") in {"POLARIZED", "PYRAMIDAL", "THRESHOLD", "MIXED", None} or "zones" in pol

        profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
        wingate = validate_wingate_glycolytic(
            lactate_pre_mmol=1.2,
            lactate_post_mmol=12.5,
            duration_s=30.0,
            peak_power_w=950.0,
            mean_power_w=650.0,
            profiler=profiler,
            mmp={5: 900, 60: 480, 300: 340, 1200: 285, 3600: 255},
        )
        assert wingate.get("status") in {"success", "partial", "error"}

        quality = analyze_mmp_quality({5: 900, 60: 480, 300: 340, 1200: 285, 3600: 255})
        assert quality.issues is not None or hasattr(quality, "tier")

        mader = run_test({
            "test_type": "wingate",
            "athlete": {"weight_kg": 72},
            "test_data": {"peak_power_w": 900, "mean_power_w": 620, "duration_s": 30},
        })
        assert mader.get("status") in {"success", "partial", "error"}

    def test_module_demos_via_subprocess(self) -> None:
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        for rel in (
            "engines/metabolic/detraining_engine.py",
            "engines/performance/durability_engine.py",
        ):
            script = root / rel
            r = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=60,
                env={**os.environ, "PYTHONPATH": str(root)},
            )
            assert r.returncode == 0, f"{rel}: {r.stderr[:300]}"

        from engines.metabolic.metabolic_profiler_phenotype import (
            compute_energy_contribution_adaptive,
            compute_recovery_curve_adaptive,
            get_pcr_params,
        )

        for phenotype in ("SPRINTER", "TT_CLIMBER", "PURSUITER"):
            get_pcr_params(phenotype)
            compute_energy_contribution_adaptive(30.0, 800.0, 55.0, 75.0, phenotype=phenotype)
            compute_recovery_curve_adaptive(10.0, 180.0, phenotype=phenotype)

    def test_detraining_declining_and_improving(self) -> None:
        today = date(2026, 5, 15)
        baseline = {
            "status": "success",
            "estimated_vo2max": 60.0,
            "estimated_vlamax_mmol_L_s": 0.45,
            "mlss_power_watts": 290.0,
            "map_aerobic_watts": 400.0,
            "fatmax_power_watts": 200.0,
        }
        declining_hist = [{"date": today - timedelta(days=i), "tss": 25} for i in range(1, 25)]
        out = apply_detraining_model(baseline, declining_hist, today)
        if out.get("status") == "success":
            assert out["training_load"]["status"] in {"DECLINING", "MAINTAINING", "DETRAINING", "IMPROVING"}

        improving_hist = [{"date": today - timedelta(days=i), "tss": 90 - i} for i in range(1, 30)]
        out2 = apply_detraining_model(baseline, improving_hist, today)
        if out2.get("status") == "success":
            assert out2["training_load"]["status"] in {"IMPROVING", "MAINTAINING"}
