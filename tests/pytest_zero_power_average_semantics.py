"""Regression tests for valid zero-power/cadence samples and power averages."""

from __future__ import annotations

import numpy as np

from engines.core.data_quality_engine import assess_data_quality
from engines.io.activity_charts import chart_power
from engines.io.activity_statistics import compute_activity_statistics
from engines.io.data_quality_report import build_data_quality_report
from engines.io.fit_parser import ActivityStreamEnhanced
from engines.performance.power_engine import normalized_power


def _coasting_stream() -> ActivityStreamEnhanced:
    stream = ActivityStreamEnhanced(
        n_samples=100,
        sport="cycling",
        total_elapsed_s=100.0,
    )
    stream.elapsed_s = np.arange(100, dtype=np.float32)
    stream.power = np.array([0.0] * 50 + [200.0] * 50, dtype=np.float32)
    stream.cadence = np.array([0.0] * 50 + [90.0] * 50, dtype=np.float32)
    stream.heart_rate = np.full(100, 140.0, dtype=np.float32)
    return stream


def test_zero_power_and_cadence_are_valid_coverage_samples() -> None:
    report = build_data_quality_report(_coasting_stream())

    assert report["signals"]["power"]["coverage_pct"] == 100.0
    assert report["signals"]["power"]["dropout_pct"] == 0.0
    assert report["signals"]["cadence"]["coverage_pct"] == 100.0
    assert report["signals"]["cadence"]["dropout_pct"] == 0.0
    assert "power_partial_coverage" not in report["warnings"]
    assert "cadence_partial_coverage" not in report["warnings"]


def test_core_quality_does_not_penalize_mixed_coasting_zeroes() -> None:
    report = assess_data_quality(
        [0.0] * 40 + [200.0] * 40,
        hr_stream=[140.0] * 80,
        cadence_stream=[0.0] * 40 + [90.0] * 40,
    )

    assert report.power_quality == 1.0
    assert report.cadence_quality == 1.0
    assert not any(
        "zeros" in issue.lower() or "gaps" in issue.lower() for issue in report.issues_detected
    )


def test_zero_only_power_stream_is_still_rejected_as_unusable_signal() -> None:
    report = assess_data_quality([0.0] * 80)

    assert report.power_quality < 0.5
    assert any("zero-only" in issue for issue in report.issues_detected)


def test_statistics_expose_elapsed_and_pedaling_power_separately() -> None:
    stream = _coasting_stream()
    output = compute_activity_statistics(stream, weight_kg=80.0)
    metrics = output["metrics"]

    assert metrics["avg_power_w"] == 100.0
    assert metrics["avg_power_w_kg"] == 1.25
    assert metrics["avg_power_elapsed_w"] == 100.0
    assert metrics["avg_power_elapsed_w_kg"] == 1.25
    assert metrics["avg_power_pedaling_w"] == 200.0
    assert metrics["avg_power_pedaling_w_kg"] == 2.5
    assert metrics["work_kj"] == 10.0
    assert metrics["np_w"] == round(normalized_power(stream.power.astype(float)), 1)
    assert output["context"]["avg_power_w_definition"] == "elapsed_timeline_including_zero_watts"
    assert output["context"]["avg_power_pedaling_w_definition"] == "positive_power_samples_only"


def test_power_chart_uses_same_average_and_np_contract_as_statistics() -> None:
    stream = _coasting_stream()
    statistics = compute_activity_statistics(stream, weight_kg=80.0)["metrics"]
    chart = chart_power(stream)
    summary = chart["summary"]

    assert summary["avg_power_w"] == statistics["avg_power_w"]
    assert summary["avg_power_elapsed_w"] == statistics["avg_power_elapsed_w"]
    assert summary["avg_power_pedaling_w"] == statistics["avg_power_pedaling_w"]
    assert summary["np_w"] == statistics["np_w"]
