"""Structural contracts for the segmented metabolic-profiler refactor."""

from __future__ import annotations

import ast
from pathlib import Path

from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_profiler import MetabolicProfiler

CTX = AthleteContext(gender="MALE", training_years=10, discipline="ROAD")
BIMODAL_MMP = {5: 1100, 15: 1000, 60: 520, 300: 340, 1200: 270, 3600: 240}


def _profiler() -> MetabolicProfiler:
    return MetabolicProfiler(weight=72.0, context=CTX)


def test_segmented_preparation_preserves_raw_audit_and_aerobic_domain() -> None:
    prepared = _profiler()._prepare_segmented_inputs(
        {"5s": 1100, "1m": 520, "300s": 340, "20m": 270, "60m": 240},
        None,
        {},
    )
    assert prepared.mmp == {5: 1100.0, 60: 520.0, 300: 340.0, 1200: 270.0, 3600: 240.0}
    assert prepared.aerobic_mmp == {300: 340.0, 1200: 270.0, 3600: 240.0}
    assert prepared.aerobic_duration_source == "fit_policy"
    assert prepared.input_audit["mmp"]["provided_anchor_count"] == 5


def test_segmented_parameter_pair_combines_the_two_stage_sources() -> None:
    profiler = _profiler()
    prepared = profiler._prepare_segmented_inputs(BIMODAL_MMP, None, {})
    aerobic = profiler.generate_metabolic_snapshot(prepared.aerobic_mmp)
    full_curve = profiler.generate_metabolic_snapshot(prepared.mmp)
    parameters = profiler._resolve_segmented_parameter_pair(aerobic, full_curve)
    assert parameters is not None
    assert parameters.vo2max == float(aerobic["unmasked_estimates"]["estimated_vo2max"])
    assert parameters.vlamax == float(full_curve["unmasked_estimates"]["estimated_vlamax_mmol_L_s"])
    assert parameters.fixed_eta == float(aerobic["context_used"]["resolved_eta"])


def test_segmented_derived_stage_recomputes_coupled_outputs() -> None:
    profiler = _profiler()
    prepared = profiler._prepare_segmented_inputs(BIMODAL_MMP, None, {})
    aerobic = profiler.generate_metabolic_snapshot(prepared.aerobic_mmp)
    full_curve = profiler.generate_metabolic_snapshot(prepared.mmp)
    parameters = profiler._resolve_segmented_parameter_pair(aerobic, full_curve)
    assert parameters is not None
    derived = profiler._derive_segmented_outputs(prepared, parameters, aerobic, full_curve)
    assert derived.unmasked["estimated_vo2max"] == round(parameters.vo2max, 1)
    assert derived.unmasked["estimated_vlamax_mmol_L_s"] == round(parameters.vlamax, 4)
    assert derived.cross_validation.to_dict()["coherent"] in {True, False}
    assert derived.combustion_curve


def test_segmented_success_builder_exposes_both_stage_diagnostics() -> None:
    profiler = _profiler()
    prepared = profiler._prepare_segmented_inputs(BIMODAL_MMP, None, {})
    aerobic = profiler.generate_metabolic_snapshot(prepared.aerobic_mmp)
    full_curve = profiler.generate_metabolic_snapshot(prepared.mmp)
    parameters = profiler._resolve_segmented_parameter_pair(aerobic, full_curve)
    assert parameters is not None
    derived = profiler._derive_segmented_outputs(prepared, parameters, aerobic, full_curve)
    snapshot = profiler._build_segmented_success_snapshot(
        prepared, parameters, derived, aerobic, full_curve
    )
    diagnostics = snapshot["fit_diagnostics"]
    assert diagnostics["fit_method"] == "segmented"
    assert diagnostics["aerobic_stage"] == aerobic["fit_diagnostics"]
    assert diagnostics["full_curve_stage"] == full_curve["fit_diagnostics"]
    assert snapshot["segmented_detail"]["mlss_source"] == "recomputed_segmented_parameter_pair"


def test_segmented_public_orchestrator_remains_bounded() -> None:
    tree = ast.parse(Path("engines/metabolic/metabolic_profiler.py").read_text(encoding="utf-8"))
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "generate_metabolic_snapshot_segmented"
    )
    assert method.end_lineno is not None
    assert method.end_lineno - method.lineno + 1 <= 100
