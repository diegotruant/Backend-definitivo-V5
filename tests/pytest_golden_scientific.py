"""Phase 3 golden scientific regression — versioned fixtures per engine family."""

from __future__ import annotations

from pathlib import Path

import pytest

from engines.adaptive_load.recommendation import generate_recommendation
from engines.metabolic.lactate_validation_engine import (
    compute_lactate_thresholds,
    steps_from_payload,
    validate_model_against_lactate,
)
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.durability_engine import calculate_durability_index
from engines.performance.test_protocols import run_test
from engines.twin_state.models import build_twin_state, validate_twin_state
from engines.twin_state.state_update_engine import (
    update_twin_state_from_ride,
    update_twin_state_from_workout_result,
)
from engines.workouts.compliance_engine import compare_workout_to_activity
from tests.golden_support import (
    MatrixActivityStream,
    assert_in_range,
    assert_within_pct,
    build_power_from_pattern,
    load_golden_cases,
)
from tests.product_quality import assert_finite_json_tree, assert_no_null_in_named_lists
from tests.pytest_golden_fit_parse import GOLDEN_CASES as FIT_GOLDEN_CASES

GOLDEN_FAMILIES = {
    "metabolic_profiler": "metabolic_lab_cases.json",
    "lactate_validation": "lactate_lab_cases.json",
    "durability": "durability_cases.json",
    "workout_compliance": "workout_compliance_cases.json",
    "adaptive_load": "adaptive_load_cases.json",
    "twin_state": "twin_state_cases.json",
}


def _metabolic_mmp_cases() -> list[dict]:
    return [case for case in load_golden_cases("metabolic_lab_cases.json") if "mmp" in case]


def _metabolic_protocol_cases() -> list[dict]:
    return [case for case in load_golden_cases("metabolic_lab_cases.json") if "envelope" in case]


def _lactate_validation_cases() -> list[dict]:
    return [case for case in load_golden_cases("lactate_lab_cases.json") if "mmp" in case]


def test_golden_phase3_families_meet_minimum_case_count() -> None:
    for family, filename in GOLDEN_FAMILIES.items():
        cases = load_golden_cases(filename)
        assert len(cases) >= 5, f"{family} needs >=5 golden cases, got {len(cases)}"
    fit_assets = Path(__file__).resolve().parent / "assets" / "fit"
    committed_fit_cases = sum(1 for stem in FIT_GOLDEN_CASES if (fit_assets / f"{stem}.fit").is_file())
    assert committed_fit_cases >= 5, f"fit_parser needs >=5 FIT assets, got {committed_fit_cases}"


@pytest.mark.parametrize("case", _metabolic_mmp_cases(), ids=lambda c: c["id"])
def test_golden_metabolic_profiler_mmp_cases(case: dict) -> None:
    """Versioned MMP fixtures must keep physiological outputs in expected bands."""
    profiler = MetabolicProfiler(weight=float(case["weight_kg"]))
    out = profiler.generate_metabolic_snapshot(case["mmp"])
    expected = case["expected"]

    assert out.get("status") == expected["status"]
    assert_finite_json_tree(out, path=f"metabolic.{case['id']}")
    assert_no_null_in_named_lists(out, path=f"metabolic.{case['id']}")

    if "vo2max_range" in expected:
        assert out["estimated_vo2max"] is not None
        lo, hi = expected["vo2max_range"]
        assert_in_range(out["estimated_vo2max"], lo, hi, label="estimated_vo2max")

    if "vlamax_range" in expected:
        assert out["estimated_vlamax_mmol_L_s"] is not None
        lo, hi = expected["vlamax_range"]
        assert_in_range(out["estimated_vlamax_mmol_L_s"], lo, hi, label="estimated_vlamax")

    if expected.get("vlamax_is_null"):
        assert out["estimated_vlamax_mmol_L_s"] is None
        assert "vlamax" in out["expressiveness"]["unreliable_parameters"]

    if "mlss_w_range" in expected:
        assert out["mlss_power_watts"] is not None
        lo, hi = expected["mlss_w_range"]
        assert_in_range(out["mlss_power_watts"], lo, hi, label="mlss_power_watts")

    if expected.get("mlss_is_present"):
        assert out["mlss_power_watts"] is not None

    if expected.get("mlss_gt_fatmax"):
        assert out["mlss_power_watts"] > out["fatmax_power_watts"]

    if expected.get("map_gt_mlss"):
        assert out["map_aerobic_watts"] > out["mlss_power_watts"]

    if "confidence_min" in expected:
        assert out["confidence_score"] >= expected["confidence_min"]
    if "confidence_max" in expected:
        assert out["confidence_score"] <= expected["confidence_max"]

    if expected.get("ui_display_masked"):
        assert out["metabolic_phenotype"] is None
        assert out["fatmax_power_watts"] is None


@pytest.mark.parametrize("case", _metabolic_protocol_cases(), ids=lambda c: c["id"])
def test_golden_metabolic_protocol_cases(case: dict) -> None:
    """Direct protocol fixtures must not fabricate absent athlete measurements."""
    envelope = case["envelope"]
    weight = envelope.get("athlete", {}).get("weight_kg") or 72.0
    out = run_test(envelope, profiler=MetabolicProfiler(weight=weight))
    expected = case["expected"]

    assert out.get("status") == expected["status"]
    assert_finite_json_tree(out, path=f"protocol.{case['id']}")
    assert_no_null_in_named_lists(out, path=f"protocol.{case['id']}")

    if "peak_power_w_range" in expected:
        lo, hi = expected["peak_power_w_range"]
        assert_in_range(out["peak_power_w"], lo, hi, label="peak_power_w")
    if "peak_power_wkg_range" in expected:
        lo, hi = expected["peak_power_wkg_range"]
        assert_in_range(out["peak_power_wkg"], lo, hi, label="peak_power_wkg")
    if expected.get("peak_power_wkg_is_null"):
        assert out["peak_power_wkg"] is None
    if expected.get("assumptions_empty"):
        assert out["assumptions"] == []
    if expected.get("has_weight_assumption"):
        assert "body_weight_missing_peak_power_wkg_not_computed" in out["assumptions"]


@pytest.mark.parametrize("case", load_golden_cases("lactate_lab_cases.json"), ids=lambda c: c["id"])
def test_golden_lactate_threshold_cases(case: dict) -> None:
    """Measured lactate fixtures must keep independent threshold anchors stable."""
    thresholds = compute_lactate_thresholds(steps_from_payload(case["steps"])).to_dict()
    expected = case["expected"]

    if "mlss_dmax_range" in expected:
        lo, hi = expected["mlss_dmax_range"]
        assert_in_range(thresholds["mlss_dmax_watts"], lo, hi, label="mlss_dmax_watts")
    if "obla_4mmol_range" in expected:
        lo, hi = expected["obla_4mmol_range"]
        assert_in_range(thresholds["obla_4mmol_watts"], lo, hi, label="obla_4mmol_watts")
    if "aerobic_2mmol_range" in expected:
        lo, hi = expected["aerobic_2mmol_range"]
        assert_in_range(thresholds["aerobic_2mmol_watts"], lo, hi, label="aerobic_2mmol_watts")


@pytest.mark.parametrize("case", _lactate_validation_cases(), ids=lambda c: c["id"])
def test_golden_lactate_validation_cases(case: dict) -> None:
    """Onboarding lactate validation must distinguish agreement from mismatch."""
    profiler = MetabolicProfiler(weight=float(case.get("weight_kg", 72.0)))
    out = validate_model_against_lactate(
        steps=steps_from_payload(case["steps"]),
        profiler=profiler,
        mmp=case["mmp"],
    )
    expected = case["expected"]

    assert out.get("status") == expected["status"]
    assert out.get("validated") is expected["validated"]
    assert_finite_json_tree(out, path=f"lactate_validation.{case['id']}")
    assert_no_null_in_named_lists(out, path=f"lactate_validation.{case['id']}")

    if "mlss_model_range" in expected:
        lo, hi = expected["mlss_model_range"]
        assert_in_range(out["mlss_model_watts"], lo, hi, label="mlss_model_watts")
    if "abs_error_pct_max" in expected:
        assert abs(out["error_pct"]) <= expected["abs_error_pct_max"]
    if "abs_error_pct_min" in expected:
        assert abs(out["error_pct"]) >= expected["abs_error_pct_min"]


@pytest.mark.parametrize("case", load_golden_cases("durability_cases.json"), ids=lambda c: c["id"])
def test_golden_durability_cases(case: dict) -> None:
    power = build_power_from_pattern(case["power_pattern"])
    duration = int(case.get("duration_seconds", len(power)))
    out = calculate_durability_index(power, duration)
    expected = case["expected"]
    assert out.get("status") == expected["status"]

    if "durability_index" in expected:
        assert_within_pct(out["durability_index"], expected["durability_index"], label="durability_index")
    if "durability_index_range" in expected:
        lo, hi = expected["durability_index_range"]
        assert_in_range(out["durability_index"], lo, hi, label="durability_index")
    if "durability_index_max" in expected:
        assert out["durability_index"] <= expected["durability_index_max"]
    if "classification" in expected:
        assert out.get("classification") == expected["classification"]


@pytest.mark.parametrize("case", load_golden_cases("workout_compliance_cases.json"), ids=lambda c: c["id"])
def test_golden_workout_compliance_cases(case: dict) -> None:
    power = build_power_from_pattern(case["power_pattern"])
    stream = MatrixActivityStream(power=power)
    out = compare_workout_to_activity(case["workout"], stream, case.get("athlete_profile"))
    expected = case["expected"]
    assert out.get("status") == expected["status"]
    if "classification" in expected:
        assert out.get("classification") == expected["classification"]
    if "compliance_score" in expected:
        assert_within_pct(out["compliance_score"], expected["compliance_score"], label="compliance_score")
    if "compliance_score_max" in expected:
        assert out["compliance_score"] <= expected["compliance_score_max"]
    if "compliance_score_min" in expected:
        assert out["compliance_score"] >= expected["compliance_score_min"]


@pytest.mark.parametrize("case", load_golden_cases("adaptive_load_cases.json"), ids=lambda c: c["id"])
def test_golden_adaptive_load_cases(case: dict) -> None:
    inp = case["input"]
    out = generate_recommendation(
        session_load=inp["session_load"],
        trend=inp["trend"],
        readiness=inp["readiness"],
    )
    expected = case["expected"]
    assert out.get("status") == expected["status"]
    assert out.get("risk_points") == expected["risk_points"]


@pytest.mark.parametrize("case", load_golden_cases("twin_state_cases.json"), ids=lambda c: c["id"])
def test_golden_twin_state_cases(case: dict) -> None:
    action = case["action"]
    expected = case["expected"]

    if action == "build":
        state = build_twin_state(case["payload"])
        assert state["schema_version"] == expected["schema_version"]
        assert state["athlete_id"] == expected["athlete_id"]
        assert state["metabolic_metrics"]["cp_w"] == expected["cp_w"]
        return

    if action == "validate":
        state = build_twin_state(case["payload"])
        cleaned = validate_twin_state(state)
        assert cleaned["schema_version"] == expected["schema_version"]
        assert cleaned["athlete_id"] == expected["athlete_id"]
        return

    if action == "update_ride":
        state = build_twin_state(case["payload"])
        ride = case.get("ride") or {}
        updated = update_twin_state_from_ride(
            state,
            ride_summary=ride.get("ride_summary"),
            ingest_result=ride.get("ingest_result"),
            ride_id=ride.get("ride_id"),
        )
        assert updated["rolling_power_curve"] == expected["rolling_power_curve"]
        return

    if action == "update_workout":
        state = build_twin_state(case["payload"])
        workout = case["workout"]
        updated = update_twin_state_from_workout_result(
            state,
            compliance_result=workout["compliance_result"],
            assignment_id=workout.get("assignment_id"),
        )
        last = updated["last_compliance_results"][-1]
        assert last["assignment_id"] == expected["last_assignment_id"]
        assert last["result"]["compliance_score"] == expected["last_compliance_score"]
        return

    if action == "validate_raw":
        with pytest.raises(ValueError):
            validate_twin_state(case["twin_state"])
        return

    pytest.fail(f"unknown twin_state action: {action}")


def test_golden_fit_timezone_edge_synthetic_stream_is_utc_aware() -> None:
    """Synthetic FIT records with non-midnight UTC start must stay timezone-aware."""
    from tests.fixtures.synthetic_fit import build_synthetic_fit_bytes, parse_synthetic_fit

    # 2026-06-15 14:30:00 UTC — summer date, non-zero offset from epoch boundary
    start_ts = 1_750_000_200
    records = [(start_ts + i * 60, 230, 142, 91) for i in range(12)]
    stream = parse_synthetic_fit(build_synthetic_fit_bytes(records))
    assert stream.start_time.tzinfo is not None
    assert stream.n_samples >= 60
    assert stream.has_power
    assert float(stream.power[0]) == 230.0
