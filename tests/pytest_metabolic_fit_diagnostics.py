"""Diagnostics and safe-error contracts for the metabolic multi-start fit."""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.metabolic import metabolic_profiler as profiler_module
from engines.metabolic.metabolic_profiler import MetabolicProfiler


CTX = AthleteContext(gender="MALE", training_years=10, discipline="ROAD")
MMP = {5: 950, 30: 650, 60: 480, 300: 345, 1200: 290, 3600: 260}
BIMODAL_MMP = {5: 1100, 15: 1000, 60: 520, 300: 340, 1200: 270, 3600: 240}


def _profiler() -> MetabolicProfiler:
    return MetabolicProfiler(weight=72.0, context=CTX)


def test_successful_fit_exposes_json_safe_multistart_diagnostics() -> None:
    snap = _profiler().generate_metabolic_snapshot(MMP)

    assert snap["status"] == "success"
    diagnostics = snap["fit_diagnostics"]
    assert diagnostics["fit_method"] == "joint"
    assert diagnostics["attempted_starts"] > 0
    assert diagnostics["candidate_starts"] > 0
    assert diagnostics["attempted_starts"] == (
        diagnostics["candidate_starts"]
        + diagnostics["exception_starts"]
        + diagnostics["invalid_result_starts"]
    )
    assert diagnostics["candidate_starts"] == (
        diagnostics["converged_starts"] + diagnostics["nonconverged_starts"]
    )
    assert len(diagnostics["selected_start"]) == 2
    assert isinstance(diagnostics["selected_optimizer"]["converged"], bool)
    assert diagnostics["selected_optimizer"]["function_evaluations"] > 0
    json.dumps(diagnostics, allow_nan=False)


def test_one_failed_start_is_audited_without_aborting_fit(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    real_least_squares = profiler_module.least_squares
    calls = 0

    def flaky_least_squares(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic first-start failure")
        return real_least_squares(*args, **kwargs)

    monkeypatch.setattr(profiler_module, "least_squares", flaky_least_squares)
    with caplog.at_level(logging.WARNING, logger=profiler_module.__name__):
        snap = _profiler().generate_metabolic_snapshot(MMP)

    assert snap["status"] == "success"
    diagnostics = snap["fit_diagnostics"]
    assert diagnostics["exception_starts"] == 1
    assert diagnostics["candidate_starts"] > 0
    assert "multistart_partial_failures" in snap["model_metadata"]["quality_flags"]
    assert any(
        record.getMessage() == "metabolic_multistart_fit_completed_with_partial_failures"
        for record in caplog.records
    )


def test_invalid_optimizer_result_is_skipped_and_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_least_squares = profiler_module.least_squares
    calls = 0

    class InvalidResult:
        x = np.array([np.nan, 0.4])
        fun = np.array([np.nan])
        success = False

    def one_invalid_result(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            return InvalidResult()
        return real_least_squares(*args, **kwargs)

    monkeypatch.setattr(profiler_module, "least_squares", one_invalid_result)
    snap = _profiler().generate_metabolic_snapshot(MMP)

    assert snap["status"] == "success"
    assert snap["fit_diagnostics"]["invalid_result_starts"] == 1
    assert "multistart_partial_failures" in snap["model_metadata"]["quality_flags"]


def test_all_start_failures_return_stable_public_error_without_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "INTERNAL_SOLVER_SECRET"

    def always_fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(secret)

    monkeypatch.setattr(profiler_module, "least_squares", always_fail)
    with caplog.at_level(logging.WARNING, logger=profiler_module.__name__):
        snap = _profiler().generate_metabolic_snapshot(MMP)

    assert snap["status"] == "error"
    assert snap["error_code"] == "metabolic_fit_failed"
    assert snap["message"] == "Metabolic model fitting could not produce a valid solution."
    assert secret not in str(snap)
    diagnostics = snap["fit_diagnostics"]
    assert diagnostics["candidate_starts"] == 0
    assert diagnostics["exception_starts"] == diagnostics["attempted_starts"]
    assert any(record.getMessage() == "metabolic_fit_failed" for record in caplog.records)


def test_unexpected_post_fit_error_is_logged_but_not_exposed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "PRIVATE_GLYCOLYTIC_TRACE"

    def fail_profile(*args: Any, **kwargs: Any) -> Any:
        raise ValueError(secret)

    monkeypatch.setattr(profiler_module, "build_glycolytic_profile", fail_profile)
    with caplog.at_level(logging.ERROR, logger=profiler_module.__name__):
        snap = _profiler().generate_metabolic_snapshot(MMP)

    assert snap["status"] == "error"
    assert snap["error_code"] == "metabolic_snapshot_failed"
    assert secret not in str(snap)
    assert any(
        record.getMessage() == "metabolic_snapshot_generation_failed"
        for record in caplog.records
    )


def test_input_processing_error_is_converted_to_safe_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger=profiler_module.__name__):
        snap = _profiler().generate_metabolic_snapshot([("60s", 300)])  # type: ignore[arg-type]

    assert snap["status"] == "error"
    assert snap["error_code"] == "metabolic_input_processing_failed"
    assert snap["message"] == "Metabolic snapshot input could not be processed."
    assert snap["fit_diagnostics"]["attempted_starts"] == 0
    assert any(
        record.getMessage() == "metabolic_snapshot_input_processing_failed"
        for record in caplog.records
    )


def test_nonconverged_selected_result_is_explicitly_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_least_squares = profiler_module.least_squares

    def force_nonconverged(*args: Any, **kwargs: Any) -> Any:
        result = real_least_squares(*args, **kwargs)
        result.success = False
        result.status = 0
        return result

    monkeypatch.setattr(profiler_module, "least_squares", force_nonconverged)
    snap = _profiler().generate_metabolic_snapshot(MMP)

    assert snap["status"] == "success"
    diagnostics = snap["fit_diagnostics"]
    assert diagnostics["nonconverged_starts"] == diagnostics["candidate_starts"]
    assert diagnostics["selected_optimizer"]["converged"] is False
    flags = snap["model_metadata"]["quality_flags"]
    assert "selected_optimizer_not_converged" in flags
    assert "multistart_partial_failures" in flags


def test_segmented_snapshot_keeps_both_stage_diagnostics() -> None:
    snap = _profiler().generate_metabolic_snapshot_segmented(BIMODAL_MMP)

    assert snap["status"] == "success"
    diagnostics = snap["fit_diagnostics"]
    assert diagnostics["fit_method"] == "segmented"
    assert diagnostics["aerobic_stage"]["fit_method"] == "joint"
    assert diagnostics["full_curve_stage"]["fit_method"] == "joint"
    assert diagnostics["combined_parameter_sources"] == {
        "vo2max": "aerobic_stage",
        "vlamax": "full_curve_stage",
    }
