"""Input-audit contracts for the metabolic profiler."""

from __future__ import annotations

import json

import pytest

from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_profiler import MetabolicProfiler


MMP = {5: 950, 30: 650, 60: 480, 300: 345, 1200: 290, 3600: 260}
BIMODAL_RAW = {
    5: 1100,
    15: 1000,
    "60s": 520,
    "1m": 515,
    300: 340,
    1200: 270,
    3600: 240,
    "bad": 250,
}


def test_valid_inputs_are_audited_without_adjustment_flags() -> None:
    profiler = MetabolicProfiler(
        weight=72.0,
        context=AthleteContext(
            gender="MALE",
            training_years=10,
            discipline="ROAD",
            body_fat_pct=15.0,
        ),
    )
    snap = profiler.generate_metabolic_snapshot(
        MMP,
        expected_eta=0.23,
        measured_lacap=14.0,
    )

    assert snap["status"] == "success"
    audit = snap["input_audit"]
    assert audit["schema_version"] == "1.0"
    assert audit["has_adjustments"] is False
    assert audit["summary"] == {
        "clipped_fields": [],
        "discarded_mmp_anchors": 0,
        "duplicate_mmp_durations": 0,
        "quality_cleaner_removed_mmp_anchors": 0,
    }
    assert audit["mmp"]["provided_anchor_count"] == len(MMP)
    assert audit["mmp"]["accepted_anchor_count"] == len(MMP)
    assert audit["mmp"]["used_anchor_count"] == len(MMP)
    assert audit["athlete"]["weight_kg"]["status"] == "accepted"
    assert audit["athlete"]["body_fat_pct"]["status"] == "accepted"
    assert audit["model_inputs"]["expected_eta"]["status"] == "accepted"
    assert audit["model_inputs"]["measured_lacap_mmol_L"]["status"] == "accepted"
    assert "input_adjustments_applied" not in snap["model_metadata"]["quality_flags"]
    json.dumps(audit, allow_nan=False)


def test_weight_and_body_fat_clipping_are_explicit_and_context_is_consistent() -> None:
    profiler = MetabolicProfiler(
        weight=38.0,
        context=AthleteContext(
            gender="MALE",
            training_years=10,
            discipline="ROAD",
            body_fat_pct=2.0,
        ),
    )
    snap = profiler.generate_metabolic_snapshot(MMP)

    assert snap["status"] == "success"
    audit = snap["input_audit"]
    assert audit["athlete"]["weight_kg"] == {
        "provided": 38.0,
        "used": 40.0,
        "source": "constructor_argument",
        "status": "clipped",
        "supported_range": {"min": 40.0, "max": None},
    }
    assert audit["athlete"]["body_fat_pct"]["provided"] == 2.0
    assert audit["athlete"]["body_fat_pct"]["used"] == 3.0
    assert audit["athlete"]["body_fat_pct"]["status"] == "clipped"
    assert snap["context_used"]["body_fat_pct"] == 3.0
    assert set(audit["summary"]["clipped_fields"]) >= {"weight_kg", "body_fat_pct"}
    assert "input_clipping_applied" in snap["model_metadata"]["quality_flags"]


def test_default_body_fat_is_distinguished_from_an_explicit_value() -> None:
    profiler = MetabolicProfiler(weight=72.0, context=AthleteContext(gender="FEMALE"))
    snap = profiler.generate_metabolic_snapshot(MMP)

    assert snap["status"] == "success"
    body_fat = snap["input_audit"]["athlete"]["body_fat_pct"]
    assert body_fat["provided"] is None
    assert body_fat["used"] == 22.0
    assert body_fat["source"] == "athlete_context_default"
    assert body_fat["status"] == "defaulted"


def test_eta_and_measured_lacap_clipping_are_audited() -> None:
    profiler = MetabolicProfiler(
        weight=72.0,
        context=AthleteContext(body_fat_pct=15.0),
    )
    snap = profiler.generate_metabolic_snapshot(
        MMP,
        expected_eta=0.35,
        measured_lacap=99.0,
    )

    assert snap["status"] == "success"
    audit = snap["input_audit"]["model_inputs"]
    assert audit["expected_eta"]["provided"] == 0.35
    assert audit["expected_eta"]["used"] == 0.28
    assert audit["expected_eta"]["status"] == "clipped"
    assert audit["measured_lacap_mmol_L"]["provided"] == 99.0
    assert audit["measured_lacap_mmol_L"]["used"] == 30.0
    assert audit["measured_lacap_mmol_L"]["status"] == "clipped"
    assert snap["assumed_la_capacity_mmol_L"] == 30.0


def test_discarded_and_duplicate_mmp_anchors_are_fully_audited() -> None:
    profiler = MetabolicProfiler(
        weight=72.0,
        context=AthleteContext(body_fat_pct=15.0),
    )
    raw = {
        "60s": 500,
        "1m": 510,
        300: 340,
        1200: 280,
        "bad": 250,
        0: 100,
        30: -1,
    }
    snap = profiler.generate_metabolic_snapshot(raw)

    assert snap["status"] == "success"
    audit = snap["input_audit"]["mmp"]
    assert audit["provided_anchor_count"] == 7
    assert audit["valid_anchor_observations"] == 4
    assert audit["accepted_anchor_count"] == 3
    assert audit["used_anchor_count"] == 3
    assert audit["discarded_anchor_count"] == 3
    assert audit["duplicate_duration_count"] == 1
    assert audit["duplicate_resolution"] == "last_value_wins"
    assert audit["duplicate_durations"][0]["duration_s"] == 60
    assert audit["duplicate_durations"][0]["previous_power_w"] == 500.0
    assert audit["duplicate_durations"][0]["replacement_power_w"] == 510.0
    assert {item["reason"] for item in audit["discarded_anchors"]} == {
        "invalid_duration",
        "non_positive_duration",
        "non_positive_or_non_finite_power",
    }
    flags = snap["model_metadata"]["quality_flags"]
    assert "mmp_anchors_discarded" in flags
    assert "mmp_duplicate_durations_resolved" in flags


def test_inferred_eta_and_lacap_are_recorded_without_being_called_clipping() -> None:
    profiler = MetabolicProfiler(
        weight=72.0,
        context=AthleteContext(training_years=10, body_fat_pct=15.0),
    )
    snap = profiler.generate_metabolic_snapshot(MMP)

    assert snap["status"] == "success"
    model_inputs = snap["input_audit"]["model_inputs"]
    assert model_inputs["expected_eta"]["source"] == "athlete_context"
    assert model_inputs["expected_eta"]["status"] == "resolved"
    assert model_inputs["expected_eta"]["used"] == pytest.approx(0.245)
    assert model_inputs["measured_lacap_mmol_L"]["source"] == "model_inferred"
    assert model_inputs["measured_lacap_mmol_L"]["status"] == "inferred_during_fit"
    assert model_inputs["measured_lacap_mmol_L"]["used"] == pytest.approx(
        snap["assumed_la_capacity_mmol_L"],
        abs=0.1,
    )


def test_insufficient_curve_still_returns_normalization_audit() -> None:
    profiler = MetabolicProfiler(
        weight=72.0,
        context=AthleteContext(body_fat_pct=15.0),
    )
    snap = profiler.generate_metabolic_snapshot({"60s": 400, "bad": 300})

    assert snap["status"] == "error"
    assert snap["error_code"] == "insufficient_mmp_anchors"
    audit = snap["input_audit"]["mmp"]
    assert audit["provided_anchor_count"] == 2
    assert audit["accepted_anchor_count"] == 1
    assert audit["discarded_anchor_count"] == 1


def test_malformed_input_error_contains_a_json_safe_audit_shell() -> None:
    profiler = MetabolicProfiler(
        weight=72.0,
        context=AthleteContext(body_fat_pct=15.0),
    )
    snap = profiler.generate_metabolic_snapshot([("60s", 300)])  # type: ignore[arg-type]

    assert snap["status"] == "error"
    assert snap["error_code"] == "metabolic_input_processing_failed"
    assert snap["input_audit"]["mmp"]["input_type"] == "list"
    assert snap["input_audit"]["mmp"]["provided_anchor_count"] is None
    json.dumps(snap["input_audit"], allow_nan=False)


def test_segmented_snapshot_preserves_full_raw_mmp_provenance() -> None:
    profiler = MetabolicProfiler(
        weight=72.0,
        context=AthleteContext(
            gender="MALE",
            training_years=10,
            discipline="ROAD",
            body_fat_pct=15.0,
        ),
    )
    snap = profiler.generate_metabolic_snapshot_segmented(BIMODAL_RAW)

    assert snap["status"] == "success"
    assert snap["fit_method"] == "segmented"
    audit = snap["input_audit"]["mmp"]
    assert audit["provided_anchor_count"] == len(BIMODAL_RAW)
    assert audit["discarded_anchor_count"] == 1
    assert audit["duplicate_duration_count"] == 1
    assert audit["accepted_anchor_count"] == 6
    assert snap["input_audit"]["model_inputs"]["expected_eta"]["used"] is not None


def test_quality_cleaner_removals_are_counted_separately() -> None:
    profiler = MetabolicProfiler(
        weight=72.0,
        context=AthleteContext(body_fat_pct=15.0),
    )
    snap = profiler.generate_metabolic_snapshot(
        {60: 400, 120: 400, 300: 350, 1200: 280},
        clean_mmp_first=True,
    )

    assert snap["status"] == "success"
    audit = snap["input_audit"]
    assert audit["mmp"]["clean_mmp_first"] is True
    assert audit["mmp"]["quality_cleaner_removed_anchor_count"] >= 1
    assert audit["summary"]["quality_cleaner_removed_mmp_anchors"] >= 1
    assert audit["mmp"]["used_anchor_count"] < audit["mmp"]["accepted_anchor_count"]
    assert "mmp_anchors_discarded" in snap["model_metadata"]["quality_flags"]
