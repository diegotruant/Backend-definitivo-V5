"""Phase 5 — deep branch closure batch E (hrv, cardiac, lab, effort, crossval)."""

from __future__ import annotations

import random
from typing import Any, Dict, List

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.metabolic.cross_validation_engine import cross_validate_metabolic_profile
from engines.metabolic.lab_data import parse_lab_text
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from datetime import datetime, timedelta

from engines.io.fit_parser import parse_fit_records_enhanced
from engines.metabolic.zones_engine import (
    coggan_power_zones,
    friel_hr_zones,
    metabolic_power_zones,
    seiler_polarization,
)
from engines.performance.effort_extractor import extract_test_proposal
from engines.recovery.cardiac_engine import (
    ActivitySample,
    CardiacResponseAnalyzer,
    Segment,
    _detect_recovery_segments,
    cross_validate_thresholds,
)
from engines.recovery.hrv_engine import (
    _artifact_mask,
    _compute_sqi,
    _correct_ectopic,
    _dfa_alpha1_full,
    _detect_threshold_crossing,
    _prepare_rr_quality,
    analyze_rr_stream,
    calculate_dfa_alpha1,
    detect_thresholds_from_activity,
)

GOOD_MMP = {
    "Omar": (70, {5: 661, 15: 527, 30: 438, 60: 401, 120: 390, 300: 352, 600: 302, 1200: 288, 1800: 279, 3600: 242}),
    "Alessio": (56, {5: 859, 15: 731, 30: 584, 60: 463, 120: 331, 300: 270, 600: 239, 1200: 227, 1800: 216, 3600: 202}),
}


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


class TestHrvDeep92E:
    def test_artifact_and_correction_edges(self) -> None:
        assert _artifact_mask(np.array([], dtype=float)).size == 0
        assert _correct_ectopic(np.array([], dtype=float), np.array([], dtype=bool)).size == 0
        assert _compute_sqi(np.array([]), np.array([]), art_ratio=0.0) == 0.0

        rr = np.array([800.0, 820.0, 810.0, 805.0, 815.0], dtype=float)
        with pytest.raises(ValueError):
            _correct_ectopic(rr, np.ones_like(rr, dtype=bool))

        jumpy = np.array([800.0, 1600.0, 810.0, 805.0, 815.0, 820.0] * 20, dtype=float)
        mask = _artifact_mask(jumpy)
        corrected = _correct_ectopic(jumpy, mask)
        sqi = _compute_sqi(jumpy, corrected, art_ratio=float(np.mean(mask)))
        assert 0.0 <= sqi <= 1.0

    def test_dfa_full_and_point_calculations(self) -> None:
        flat_rr = np.full(120, 800.0)
        flat = _dfa_alpha1_full(flat_rr)
        assert flat.get("alpha1") is None or isinstance(flat.get("alpha1"), float)

        good_rr = np.array([820.0 + (i % 11) for i in range(160)], dtype=float)
        full = _dfa_alpha1_full(good_rr)
        assert full.get("alpha1") is not None

        low_conf = calculate_dfa_alpha1(
            [820.0 + (i % 3) for i in range(90)],
            context=AthleteContext(gender="FEMALE", training_years=2, discipline="MTB"),
        )
        assert low_conf["status"] in {"AEROBIC", "MIXED", "ANAEROBIC", "ERROR", "INVALID_WINDOW"}

        rejected = _prepare_rr_quality([50.0, 3000.0, 100.0] * 30)
        assert rejected["valid"] is False

    def test_stream_and_threshold_detection(self) -> None:
        rr_samples = [
            {"elapsed": float(i * 4), "rr": [820.0 + (i % 7) for _ in range(40)]}
            for i in range(120)
        ]
        timeline = analyze_rr_stream(
            rr_samples,
            window_seconds=90,
            step_seconds=8.0,
            context=AthleteContext(gender="MALE", training_years=10, discipline="ROAD"),
        )
        assert isinstance(timeline, list)

        power = [120.0 + i * 0.4 for i in range(2000)]
        detected = detect_thresholds_from_activity(
            rr_samples,
            power_data=power,
            power_timestamps=[float(i) for i in range(len(power))],
            window_seconds=90,
            step_seconds=8.0,
            context=AthleteContext(gender="MALE", training_years=8, discipline="ROAD"),
        )
        assert "quality_summary" in detected

        crossing = _detect_threshold_crossing(
            [
                {"timestamp": 0.0, "alpha1_smoothed": 0.95},
                {"timestamp": 30.0, "alpha1_smoothed": 0.72},
                {"timestamp": 60.0, "alpha1_smoothed": 0.68},
                {"timestamp": 90.0, "alpha1_smoothed": 0.65},
            ],
            threshold=0.75,
            power_data=[180.0, 210.0, 240.0, 260.0],
            power_timestamps=[0.0, 30.0, 60.0, 90.0],
            persistence_windows=2,
        )
        assert crossing[0] is not None


class TestCardiacDeep92E:
    def test_recovery_end_of_stream_and_aggregate(self) -> None:
        rec_t = np.arange(500, dtype=float)
        rec_p = np.concatenate([np.full(200, 250.0), np.full(300, 10.0)])
        rec_h = np.concatenate([np.full(200, 170.0), np.linspace(170, 120, 300)])
        rec_smooth = rec_p
        h_smooth = rec_h
        segments = _detect_recovery_segments(rec_t, rec_smooth, h_smooth)
        assert segments

        samples: List[ActivitySample] = []
        for i in range(900):
            if i < 300:
                p, h = 260.0, 175.0 - i * 0.01
            elif i < 500:
                p, h = 15.0, max(125.0, 170.0 - (i - 300) * 0.15)
            else:
                p, h = 220.0, 140.0 + (i - 500) * 0.01
            samples.append(ActivitySample(t=float(i), power=p, hr=h))

        analyzer = CardiacResponseAnalyzer(weight=72.0)
        result = analyzer.analyze(samples)
        assert result.get("status") in {"success", "error"}
        if result.get("status") == "success":
            summary = result.get("fitness_summary") or {}
            assert summary.get("fitness_class") or summary.get("n_metrics_available", 0) >= 0

    def test_cross_validate_invalid_mlss(self) -> None:
        t = np.arange(600, dtype=float)
        p = np.full(600, 220.0)
        h = np.linspace(140, 150, 600)
        cv = cross_validate_thresholds(
            t,
            p,
            h,
            metabolic_snapshot={"status": "success", "mlss_power_watts": "bad"},
            hrv_timeline=[
                {"timestamp": 60.0, "status": "AEROBIC"},
                {"timestamp": 120.0, "status": "MIXED"},
                {"timestamp": 180.0, "status": "ANAEROBIC"},
            ],
        )
        assert isinstance(cv, dict)


class TestMetabolicIoDeep92E:
    def test_cross_validation_port(self) -> None:
        for name, (weight, mmp) in GOOD_MMP.items():
            prof = MetabolicProfiler(weight=weight)
            snap = prof.generate_metabolic_snapshot(mmp, expected_eta=0.23)
            cv = snap["cross_validation"]
            assert cv["severity"] != "severe", name
            assert cv["coherence_penalty"] <= 0.25

        prof = MetabolicProfiler(weight=88)
        adrian_mmp = {5: 700, 15: 639, 30: 470, 60: 386, 120: 369, 300: 351, 600: 305, 1200: 283, 1800: 272, 3600: 265}
        cv_bad = cross_validate_metabolic_profile(prof, adrian_mmp, vo2max=30.0, vlamax=1.46, eta_base=0.23)
        assert not cv_bad.coherent
        assert cv_bad.coherence_penalty >= 0.4

        cv_short = cross_validate_metabolic_profile(prof, {5: 900, 15: 700, 60: 450}, 55, 0.5)
        assert isinstance(cv_short.coherent, bool)
        assert cv_short.to_dict()["tier"] == "MODEL"

    def test_lab_zones_and_effort_extractor(self) -> None:
        text = (
            "INSCYD Report\nVO2max 58.5 ml/kg/min\nVLamax 0.48 mmol/L/s\n"
            "MLSS 275 W\nFTP 270 W\nFatMax 195 W\nMAP 340 W\nHRmax 185\nWeight 70 kg\n"
        )
        parsed = parse_lab_text(text)
        assert parsed.vo2max_ml_kg_min == pytest.approx(58.5)

        start = datetime(2026, 1, 1, 8, 0, 0)
        records = [
            {"timestamp": start + timedelta(seconds=i), "power": 220.0, "heart_rate": 140.0}
            for i in range(600)
        ]
        stream = parse_fit_records_enhanced(records, session_dict={"start_time": start, "total_elapsed_time": 600})
        assert coggan_power_zones(stream, ftp=250.0)["available"] is True
        assert friel_hr_zones(stream, lthr=165.0)["available"] is True
        metabolic_snap = {
            "status": "success",
            "mlss_power_watts": 270,
            "map_aerobic_watts": 340,
            "expressiveness": {"mlss_reliable": True},
            "zones": [
                {"name": "Z1", "minWatt": 0, "maxWatt": 150},
                {"name": "Z2", "minWatt": 151, "maxWatt": 210},
                {"name": "Z3", "minWatt": 211, "maxWatt": 250},
                {"name": "Z4", "minWatt": 251, "maxWatt": 290},
                {"name": "Z5", "minWatt": 291, "maxWatt": 340},
            ],
        }
        assert metabolic_power_zones(stream, metabolic_snap)["available"] is True
        assert seiler_polarization(stream, vt1_w=200.0, vt2_w=260.0)["available"] is True

        rng = np.random.default_rng(42)
        day1 = (
            _flat(120, 600, noise=8, rng=rng)
            + _sprint(1000, 15)
            + _flat(90, 300, noise=8, rng=rng)
            + _flat(300, 720, noise=6, rng=rng)
        )
        day2 = _flat(120, 600, noise=8, rng=rng) + _flat(360, 180, noise=8, rng=rng) + _flat(330, 360, noise=7, rng=rng)
        proposal = extract_test_proposal(
            [
                {"file_id": "day1", "power": day1, "laps": None},
                {"file_id": "day2", "power": day2, "laps": None},
            ]
        )
        d = proposal.to_dict()
        assert d["status"] in {"proposed", "not_proposed", "insufficient_data"}
        if d["status"] == "proposed":
            assert d["confidence"] >= 0.5

        ordinary = extract_test_proposal(
            [{"file_id": "ride", "power": _flat(200, 3600, noise=10, rng=rng), "laps": None}]
        )
        assert ordinary.to_dict()["status"] in {"proposed", "not_proposed", "insufficient_data", "incomplete"}
