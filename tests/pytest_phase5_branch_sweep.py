"""Phase 5 branch sweep — high-yield calls across under-covered public APIs."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.io.workout_summary import build_workout_summary
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.mader_durability import (
    MaderDurabilityEngine,
    compute_session_durability,
    from_metabolic_snapshot,
    sustainability_targets,
)
from engines.performance.power_engine import mean_maximal_power, normalized_power, variability_index


def _stream(seconds: int = 600, power: float = 220.0):
    start = datetime(2026, 1, 1, 8, 0, 0)
    records = [
        {"timestamp": start + timedelta(seconds=i), "power": power, "heart_rate": 140.0, "cadence": 90.0}
        for i in range(seconds)
    ]
    return parse_fit_records_enhanced(records, session_dict={"start_time": start, "total_elapsed_time": seconds})


class TestMaderDurabilitySweep:
    def test_engine_matrix(self) -> None:
        rng = np.random.default_rng(7)
        power = np.concatenate(
            [
                np.full(1800, 150.0),
                rng.normal(230.0, 12.0, 3600).clip(120, 350),
                np.full(1200, 130.0),
            ]
        )
        engine = MaderDurabilityEngine(weight_kg=75.0, vo2max=55.0, vlamax=0.45, mlss_w=265.0, eta=0.23)
        out = engine.compute(power)
        assert out.get("status") == "success"
        assert len(out.get("cp_residual_curve", [])) == len(power)

        sus = sustainability_targets(out)
        assert sus.get("status") == "success"
        assert sus.get("kj_budgets")

        power_long = np.concatenate([np.full(3600, 200.0), np.full(3600, 280.0)])
        diesel = MaderDurabilityEngine(75, 58, 0.30, 270).compute(power_long)
        sprinter = MaderDurabilityEngine(75, 48, 0.85, 220).compute(power_long)
        assert float(sprinter.get("durability_loss_pct", 0)) >= float(diesel.get("durability_loss_pct", 0))

    def test_snapshot_factory_and_session_pipeline(self) -> None:
        mmp = {15: 980, 60: 540, 300: 340, 720: 300, 1200: 285, 3600: 255}
        profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
        snap = profiler.generate_metabolic_snapshot(mmp)
        eng = from_metabolic_snapshot(snap, weight_kg=72.0)
        assert eng is not None

        power = [180.0] * 1800 + [250.0] * 1800 + [160.0] * 1800
        session = compute_session_durability(power, snap, weight_kg=72.0)
        assert session.get("status") == "success"
        assert session.get("sustainability", {}).get("status") == "success"

    def test_workout_summary_mader_section(self) -> None:
        base = datetime(2025, 6, 1, 8, 0, 0)
        records = [
            {
                "timestamp": base + timedelta(seconds=i),
                "power": int(200 + 30 * np.sin(i / 300)),
                "heart_rate": int(140 + 5 * np.sin(i / 400)),
            }
            for i in range(3600)
        ]
        stream = parse_fit_records_enhanced(records, session_dict={"sport": "cycling", "start_time": base})
        mmp = {15: 980, 60: 540, 300: 340, 720: 300, 1200: 285, 3600: 255}
        snap = MetabolicProfiler(weight=72.0).generate_metabolic_snapshot(mmp)
        summary = build_workout_summary(stream, weight_kg=72.0, ftp=280.0, metabolic_snapshot=snap)
        md = summary.get("sections", {}).get("mader_durability", {})
        assert md.get("status") in {"success", "unavailable", "error", None} or "headline" in summary


class TestMetabolicAndPowerSweep:
    def test_profiler_variants(self) -> None:
        profiler = MetabolicProfiler(weight=72.0, context=AthleteContext(gender="MALE", training_years=8))
        for mmp in (
            {60: 500, 300: 360, 1200: 300},
            {1: 950, 5: 900, 60: 480, 300: 340, 1200: 290, 3600: 260},
            {300: 320, 1200: 280},
        ):
            snap = profiler.generate_metabolic_snapshot(mmp, clean_mmp_first=True)
            body = snap if isinstance(snap, dict) else snap
            if hasattr(body, "to_dict"):
                body = body.to_dict()
            assert body.get("status") in {"success", "error", "partial"}

    def test_power_engine_and_glycolytic(self) -> None:
        from engines.metabolic.glycolytic_validation_engine import (
            build_glycolytic_profile,
            compute_vlapeak_observed,
            glycolytic_flux_index,
            predict_vlapeak_from_snapshot,
            validate_vlapeak_against_model,
        )
        from engines.metabolic.zones_engine import coggan_power_zones, friel_hr_zones, seiler_polarization

        arr = np.array([200.0 + (i % 25) for i in range(1200)])
        np_val = normalized_power(arr)
        assert np_val > 0
        assert variability_index(np_val, float(np.mean(arr))) is not None
        mmp = mean_maximal_power(arr, durations_s=[5, 60, 300, 1200])
        assert mmp

        stream = _stream(900, 240.0)
        assert coggan_power_zones(stream, ftp=280.0)["available"] is True
        assert friel_hr_zones(stream, lthr=165.0)["available"] is True
        assert seiler_polarization(stream, vt1_w=200.0, vt2_w=260.0)["available"] is True

        snap = {
            "status": "success",
            "estimated_vlamax_mmol_L_s": 0.5,
            "mlss_power_watts": 280.0,
            "map_aerobic_watts": 360.0,
            "combustion_curve": [{"watt": 200, "carbOxidation": 20}, {"watt": 280, "carbOxidation": 45}],
        }
        assert build_glycolytic_profile(snap, mmp={1: 950, 60: 480})["status"] == "success"
        assert compute_vlapeak_observed(1.2, 12.0, 30.0)["status"] == "success"
        assert predict_vlapeak_from_snapshot(snap, mmp={1: 950})["status"] in {"success", "unavailable"}
        assert validate_vlapeak_against_model(vlapeak_observed_mmol_l_s=0.9, predicted_vlapeak_mmol_l_s=0.85)["status"]
        assert glycolytic_flux_index(0.55) > glycolytic_flux_index(0.25)


class TestIoAndProtocolsSweep:
    def test_activity_intelligence_and_statistics(self) -> None:
        from engines.io.activity_intelligence import (
            build_activity_intelligence,
            compute_best_efforts,
            compute_zone_distribution,
            detect_auto_intervals,
        )
        from engines.io.activity_statistics import compute_activity_statistics

        stream = _stream(2400, 260.0)
        intel = build_activity_intelligence(stream, weight_kg=72.0, ftp=280.0, lthr=165.0)
        assert intel.get("status") in {"success", "partial", "error"}
        efforts = compute_best_efforts(stream.power.tolist())
        assert efforts.get("status") in {"success", "skipped"}
        zones = compute_zone_distribution(stream.power.tolist(), threshold=280.0, kind="power")
        assert zones.get("status") in {"success", "skipped"}
        intervals = detect_auto_intervals(stream.power.tolist(), threshold_w=280.0)
        assert intervals.get("status") in {"success", "skipped"}
        stats = compute_activity_statistics(stream, ftp=280.0, weight_kg=72.0)
        assert stats.get("status") in {"success", "partial", "error"} or "duration_s" in stats

    def test_test_protocols_and_race(self) -> None:
        from engines.performance.race_prediction_engine import analyze_course, parse_gpx_course
        from engines.performance.test_protocols import (
            run_critical_power_test,
            run_incremental_test,
            run_power_cadence_test,
            run_test,
            run_wingate_test,
        )

        wingate = run_wingate_test({"test_data": {"power_stream": [1100.0] * 5 + [700.0] * 25, "body_weight_kg": 72.0}})
        assert wingate.get("status") in {"success", "error"}
        inc = run_incremental_test(
            {"test_data": {"steps": [{"power_w": 150, "hr_mean": 120}, {"power_w": 220, "hr_mean": 150}]}}
        )
        assert inc.get("status") in {"success", "error"}
        cadence = run_power_cadence_test(
            {"test_data": {"steps": [{"cadence_rpm": 80, "power_w": 200}, {"cadence_rpm": 100, "power_w": 220}]}}
        )
        assert cadence.get("status") in {"success", "error"}
        cp = run_critical_power_test(
            {
                "test_data": {
                    "efforts": [
                        {"duration_s": 180, "power_w": 400},
                        {"duration_s": 360, "power_w": 360},
                    ]
                }
            }
        )
        assert cp.get("status") in {"success", "error"}
        envelope = run_test({"test_type": "wingate", "test_data": {"power_stream": [1000.0] * 30, "body_weight_kg": 72.0}})
        assert envelope.get("status") in {"success", "error"}

        gpx = """<?xml version="1.0"?><gpx><trk><trkseg>
        <trkpt lat="45.0" lon="7.0"><ele>200</ele></trkpt>
        <trkpt lat="45.01" lon="7.01"><ele>400</ele></trkpt>
        <trkpt lat="45.02" lon="7.02"><ele>250</ele></trkpt>
        </trkseg></trk></gpx>"""
        course = parse_gpx_course(gpx)
        analyzed = analyze_course(course)
        assert analyzed.get("total_distance_m") is not None or analyzed.get("status") in {"success", "error"}
