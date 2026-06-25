from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.power_engine import PowerEngine
from engines.performance.test_protocols import run_test as run_in_person_test

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def _load_cases(name: str) -> list[dict]:
    return json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))


class _Stream:
    def __init__(self, power: np.ndarray) -> None:
        n = power.size
        self.power = power.astype(float)
        self.heart_rate = np.full(n, 145.0)
        self.elapsed_s = np.arange(n, dtype=float)
        self.total_elapsed_s = float(n)
        self.n_samples = n
        self.has_power = True
        self.has_heart_rate = True


@pytest.mark.parametrize("case", _load_cases("metabolic_lab_cases.json"), ids=lambda c: c["id"])
def test_golden_metabolic_lab_cases(case: dict) -> None:
    if "mmp" in case:
        profiler = MetabolicProfiler(weight=case["weight_kg"], context=AthleteContext())
        snap = profiler.generate_metabolic_snapshot(case["mmp"])
        expected = case["expected"]
        assert snap.get("status") == expected["status"]

        if "vo2max_range" in expected:
            vo2 = snap.get("estimated_vo2max")
            assert vo2 is not None
            lo, hi = expected["vo2max_range"]
            assert lo <= vo2 <= hi

        if "vlamax_range" in expected:
            vla = snap.get("estimated_vlamax_mmol_L_s")
            assert vla is not None
            lo, hi = expected["vlamax_range"]
            assert lo <= vla <= hi

        if "mlss_w_range" in expected:
            mlss = snap.get("mlss_power_watts")
            assert mlss is not None
            lo, hi = expected["mlss_w_range"]
            assert lo <= mlss <= hi

        if expected.get("mlss_gt_fatmax"):
            assert snap["mlss_power_watts"] > snap["fatmax_power_watts"]

        if expected.get("map_gt_mlss"):
            assert snap["map_aerobic_watts"] > snap["mlss_power_watts"]

        if "confidence_min" in expected:
            assert snap["confidence_score"] >= expected["confidence_min"]

        if expected.get("vlamax_is_null"):
            assert snap.get("estimated_vlamax_mmol_L_s") is None

        if expected.get("mlss_is_present"):
            assert snap.get("mlss_power_watts") is not None

        if "confidence_max" in expected:
            assert snap["confidence_score"] <= expected["confidence_max"]

        if "confidence_max" in expected:
            assert snap["confidence_score"] <= expected["confidence_max"]

        if expected.get("ui_display_masked"):
            assert snap.get("ui_display", {}).get("show_values") is False
        return

    envelope = case["envelope"]
    expected = case["expected"]
    profiler = MetabolicProfiler(
        weight=float(envelope.get("athlete", {}).get("weight_kg") or 70.0),
        context=AthleteContext(),
    )
    out = run_in_person_test(envelope, profiler=profiler)
    assert out.get("status") == expected["status"]

    if "peak_power_w_range" in expected:
        lo, hi = expected["peak_power_w_range"]
        assert lo <= out["peak_power_w"] <= hi

    if "peak_power_wkg_range" in expected:
        lo, hi = expected["peak_power_wkg_range"]
        assert out["peak_power_wkg"] is not None
        assert lo <= out["peak_power_wkg"] <= hi

    if expected.get("peak_power_wkg_is_null"):
        assert out.get("peak_power_wkg") is None

    if expected.get("has_weight_assumption"):
        assert "body_weight_missing_peak_power_wkg_not_computed" in (out.get("assumptions") or [])

    if expected.get("assumptions_empty"):
        assert not out.get("assumptions")


@pytest.mark.parametrize("case", _load_cases("power_metric_cases.json"), ids=lambda c: c["id"])
def test_golden_power_metric_cases(case: dict) -> None:
    expected = case["expected"]
    if "power" in case:
        n = int(case["duration_s"])
        power = np.full(n, float(case["power"]), dtype=float)
        stream = _Stream(power)
        out = PowerEngine(ftp=case["ftp"], weight_kg=case["weight_kg"]).analyze(stream)
        assert out["status"] == "success"
        metrics = out["metrics"]
        tol = expected.get("work_kj_tolerance", 0.1)
        assert abs(metrics["work_kj"] - expected["work_kj"]) <= tol
        assert abs(metrics["average_power"] - expected["avg_power_w"]) < 1e-6
        return

    if case.get("fixture") == "synthetic_ride":
        from tests.fixtures.synthetic_fit import parse_synthetic_fit
        from engines.io.activity_statistics import compute_activity_statistics

        fit_path = Path(__file__).resolve().parent / "assets" / "synthetic_ride.fit"
        if not fit_path.exists():
            pytest.skip("synthetic_ride.fit not committed in this workspace")
        stream = parse_synthetic_fit(fit_path.read_bytes())
        stats = compute_activity_statistics(stream, weight_kg=case["weight_kg"], ftp=case["ftp"])
        metrics = stats["metrics"]
        assert metrics["avg_power_w"] >= expected["avg_power_w_min"]
        assert metrics["work_kj"] >= expected["work_kj_min"]
        assert metrics["max_hr_bpm"] >= expected["max_hr_bpm_min"]


@pytest.mark.parametrize("case", _load_cases("lactate_lab_cases.json"), ids=lambda c: c["id"])
def test_golden_lactate_lab_cases(case: dict) -> None:
    from engines.metabolic.lactate_validation_engine import (
        LactateStep,
        compute_lactate_thresholds,
        validate_model_against_lactate,
    )

    expected = case["expected"]
    steps = [LactateStep(**s) for s in case["steps"]]

    if "mlss_dmax_range" in expected:
        thr = compute_lactate_thresholds(steps)
        lo, hi = expected["mlss_dmax_range"]
        assert thr.mlss_dmax_w is not None
        assert lo <= thr.mlss_dmax_w <= hi
        if "obla_4mmol_range" in expected:
            lo_o, hi_o = expected["obla_4mmol_range"]
            assert thr.obla_4mmol_w is not None
            assert lo_o <= thr.obla_4mmol_w <= hi_o
        if "aerobic_2mmol_range" in expected:
            lo_a, hi_a = expected["aerobic_2mmol_range"]
            assert thr.aerobic_2mmol_w is not None
            assert lo_a <= thr.aerobic_2mmol_w <= hi_a
        return

    if expected.get("mlss_dmax_is_null"):
        thr = compute_lactate_thresholds(steps)
        assert thr.mlss_dmax_w is None
        return

    profiler = MetabolicProfiler(weight=case["weight_kg"], context=AthleteContext())
    out = validate_model_against_lactate(steps, profiler, case["mmp"])
    assert out.get("status") == expected["status"]
    if expected.get("validated") is not None:
        assert out.get("validated") is expected["validated"]
    if "mlss_model_range" in expected:
        mlss = out.get("mlss_model_watts")
        assert mlss is not None
        lo, hi = expected["mlss_model_range"]
        assert lo <= mlss <= hi
    if "abs_error_pct_max" in expected:
        assert abs(out.get("error_pct", 999.0)) <= expected["abs_error_pct_max"]
    if "abs_error_pct_min" in expected:
        assert abs(out.get("error_pct", 0.0)) >= expected["abs_error_pct_min"]
