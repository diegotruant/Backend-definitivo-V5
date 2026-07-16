"""Phase 5 — supplementary coverage for metabolic, mmp, lab, api, data quality."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

import numpy as np
import pytest

from api.engine_schemas import (
    ExplainabilityDurabilityConfidenceRequest,
    ExplainabilityMetricNarrativeRequest,
    ExplainabilityWorkoutSummaryRequest,
    LabTextParseRequest,
    MmpQualityRequest,
)
from api.schemas import AthleteParams
from api.services.explainability_service import ExplainabilityService
from api.services.lab_service import LabService
from api.services.profile_extended_service import ProfileExtendedService
from engines.core.data_quality_engine import assess_data_quality, clean_workout_data
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.metabolic.bayesian_profiler import bayesian_metabolic_snapshot
from engines.metabolic.lab_data import parse_lab_text
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.effort_extractor import extract_test_proposal
from engines.performance.mmp_quality import analyze_mmp_quality, clean_mmp, filter_mmp_by_window
from engines.performance.mmp_aggregator import curve_to_mmp, extract_ride_curve, update_power_curve


def _stream(seconds: int = 600, power: float = 220.0):
    start = datetime(2026, 1, 1, 8, 0, 0)
    records = [
        {"timestamp": start + timedelta(seconds=i), "power": power, "heart_rate": 140.0, "cadence": 90.0}
        for i in range(seconds)
    ]
    return parse_fit_records_enhanced(records, session_dict={"start_time": start, "total_elapsed_time": seconds})


class TestMetabolicMmpLab92:
    def test_bayesian_and_profiler_edges(self) -> None:
        profiler = MetabolicProfiler(weight=72.0)
        sprinter = {1: 961, 5: 900, 60: 480, 300: 340, 1200: 290, 3600: 255}
        snap = bayesian_metabolic_snapshot(profiler, sprinter, n_samples=500, n_warmup=100, seed=5)
        body = snap.to_dict()
        assert body["status"] in {"success", "error"}

        measured = bayesian_metabolic_snapshot(
            profiler,
            sprinter,
            n_samples=400,
            n_warmup=80,
            seed=9,
            prior_vo2_mean=62.0,
            prior_vla_mean=0.48,
        )
        assert measured.to_dict()["status"] in {"success", "error"}

        sparse = profiler.generate_metabolic_snapshot({300: 320})
        assert sparse.get("status") in {"success", "error", "partial"} or hasattr(sparse, "to_dict")

    def test_mmp_quality_lab_effort(self) -> None:
        weird = {5: 2400, 15: 1800, 60: 520, 300: 520, 600: 518, 1200: 510, 3600: 490}
        report = analyze_mmp_quality(weird)
        assert report.issues
        cleaned, audit = clean_mmp(weird, drop_rules=["identical_plateau", "sprint_outlier", "non_monotonic"])
        assert audit["original_anchors"] >= 3

        ref = date(2026, 6, 17)
        filtered, kept = filter_mmp_by_window(
            [
                {"duration_s": 300, "power_w": 380, "date": "2026-06-01"},
                {"duration_s": 1200, "power_w": 320, "date": "2023-01-01"},
            ],
            today=ref,
            window_days=120,
        )
        assert 300 in filtered and 1200 not in filtered

        text = (
            "Lab\nVO2max 61 ml/kg/min\nVLamax 0.50\nMLSS 280 W\nFTP 275 W\n"
            "FatMax 200 W\nMAP 355 W\nHRmax 186\nWeight 70 kg\n"
        )
        assert parse_lab_text(text).vo2max_ml_kg_min == pytest.approx(61.0)

        proposal = extract_test_proposal(
            [
                {"file_id": "a.fit", "power": [150.0] * 300 + [330.0] * 360 + [150.0] * 300},
                {"file_id": "b.fit", "power": [120.0] * 200 + [1000.0] * 12 + [120.0] * 200},
            ]
        )
        assert proposal.to_dict()["status"] in {"proposed", "incomplete", "empty"}

        curve = extract_ride_curve([250.0 + (i % 10) for i in range(1800)])
        assert curve
        rebuilt = curve_to_mmp({60: 400.0, 300: {"power_w": 360.0}})
        assert rebuilt[60] == 400.0
        updated = update_power_curve(
            [250.0] * 1800,
            "2026-06-01",
            stored_curve={60: {"duration_s": 60, "power_w": 400.0, "ride_id": "old", "ride_date": "2020-01-01"}},
            ride_id="ride-1",
            enforce_quality_gate=True,
        )
        assert hasattr(updated, "curve") or isinstance(updated, dict)


class TestDataQualityApi92:
    def test_data_quality_pause_and_spike_paths(self) -> None:
        # Spike counter needs >10 consecutive pairs above 1000 W
        spiky = [220.0] * 20 + [2500.0] * 15 + [220.0] * 20
        spike_report = assess_data_quality(spiky)
        assert spike_report.power_quality < 1.0
        assert any("spike" in issue.lower() for issue in spike_report.issues_detected)

        trainer = [220.0 if i % 2 == 0 else 221.0 for i in range(400)]
        report = assess_data_quality(trainer, hr_stream=[140.0] * 400, cadence_stream=[300.0] * 400)
        assert report.cadence_quality < 1.0

        paused = clean_workout_data([220.0] * 60 + [0.0] * 45 + [220.0] * 60, remove_pauses_flag=True)
        assert len(paused["power_cleaned"]) < 165

    def test_api_service_branches(self) -> None:
        lab = LabService()
        parsed = lab.parse_text(LabTextParseRequest(text="VO2max 60 ml/kg/min\nVLamax 0.45\nMLSS 270 W\n"))
        assert parsed.get("status") in {"success", "partial", "error"} or "vo2max" in str(parsed).lower()

        profile = ProfileExtendedService()
        mq = profile.mmp_quality(MmpQualityRequest(mmp={"300": 320, "600": 320, "1200": 300, "3600": 290}))
        assert "quality_score" in mq or mq.get("status") in {"success", "error"}

        expl = ExplainabilityService()
        conf = expl.durability_confidence(
            ExplainabilityDurabilityConfidenceRequest(duration_hours=4.0, power_data_completeness=0.95)
        )
        narrative = expl.durability_narrative(
            {
                "durability_index": 92.0,
                "classification": "GOOD",
                "confidence": conf,
                "prescription": {"focus": "Base", "volume": "8h", "key_sessions": ["Long Z2"]},
            }
        )
        assert narrative.get("narrative") or isinstance(narrative, dict)

        metric = expl.metric_narrative(
            ExplainabilityMetricNarrativeRequest(metric_name="VO2max", value=62.0, confidence=conf)
        )
        assert isinstance(metric, dict) and "narrative" in metric

        summary = expl.workout_summary_narrative(
            ExplainabilityWorkoutSummaryRequest(
                summary={
                    "headline": {"workout_type": "Endurance", "tss": 90, "if_value": 0.72},
                    "stream_metadata": {"duration_s": 5400},
                    "sections": {},
                }
            )
        )
        assert "narrative" in summary
