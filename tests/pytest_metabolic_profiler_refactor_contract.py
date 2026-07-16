"""Structural contracts for the incremental metabolic-profiler refactor.

These tests do not introduce new physiology. They make the extracted pipeline
stages independently testable while the public snapshot remains unchanged.
"""

from __future__ import annotations

import numpy as np

from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_profiler import MetabolicProfiler


CTX = AthleteContext(gender="MALE", training_years=10, discipline="ROAD")
MMP = {5: 950, 30: 650, 60: 480, 300: 345, 1200: 290, 3600: 260}


def _profiler() -> MetabolicProfiler:
    return MetabolicProfiler(weight=72.0, context=CTX)


def test_preparation_stage_normalizes_inputs_and_builds_audits() -> None:
    prepared = _profiler()._prepare_snapshot_inputs(
        {"1m": 480, "300s": 345, 1200: 290, 3600: 260},
        expected_eta=None,
        measured_lacap=None,
        mmp_samples=None,
        clean_mmp_first=False,
    )

    assert prepared.mmp == {60: 480.0, 300: 345.0, 1200: 290.0, 3600: 260.0}
    assert prepared.input_audit["mmp"]["used_anchor_count"] == 4
    assert prepared.mmp_quality_audit is None


def test_fit_context_has_finite_arrays_and_fixed_residual_dimension() -> None:
    profiler = _profiler()
    prepared = profiler._prepare_snapshot_inputs(
        MMP,
        expected_eta=None,
        measured_lacap=None,
        mmp_samples=None,
        clean_mmp_first=False,
    )
    context = profiler._build_fit_context(
        prepared,
        expected_eta=None,
        measured_lacap=None,
    )
    residuals = profiler._fit_residuals(
        np.array([context.vo2_guess, 0.5], dtype=float),
        context,
    )

    assert context.durs_u.size >= profiler.fit_policy.minimum_fit_anchors
    assert residuals.size == context.durs_u.size + 5
    assert np.all(np.isfinite(residuals))


def test_multistart_stage_returns_a_finite_selection_and_diagnostics() -> None:
    profiler = _profiler()
    prepared = profiler._prepare_snapshot_inputs(
        MMP,
        expected_eta=None,
        measured_lacap=None,
        mmp_samples=None,
        clean_mmp_first=False,
    )
    context = profiler._build_fit_context(
        prepared,
        expected_eta=None,
        measured_lacap=None,
    )
    selection = profiler._run_multistart_fit(context)

    assert np.isfinite(selection.vo2)
    assert np.isfinite(selection.vlamax)
    assert context.fit_diagnostics["candidate_starts"] > 0
    assert "selected_optimizer" in context.fit_diagnostics


def test_success_serialization_stage_builds_the_same_public_contract() -> None:
    profiler = _profiler()
    prepared = profiler._prepare_snapshot_inputs(
        MMP,
        expected_eta=None,
        measured_lacap=None,
        mmp_samples=None,
        clean_mmp_first=False,
    )
    context = profiler._build_fit_context(
        prepared,
        expected_eta=None,
        measured_lacap=None,
    )
    selection = profiler._run_multistart_fit(context)
    snapshot = profiler._build_success_snapshot(prepared, context, selection)

    assert snapshot["status"] == "success"
    assert snapshot["fit_diagnostics"] is context.fit_diagnostics
    assert snapshot["estimated_vo2max"] is not None
    assert isinstance(snapshot["cross_validation"]["coherent"], bool)
    assert "glycolytic_profile" in snapshot


def test_public_orchestrator_still_returns_finalized_configuration() -> None:
    snapshot = _profiler().generate_metabolic_snapshot(MMP)

    assert snapshot["status"] == "success"
    assert snapshot["model_configuration"]["schema_version"] == "1.0"
    assert snapshot["model_metadata"]["confidence_score"] == snapshot["confidence_score"]
