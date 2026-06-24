from __future__ import annotations

import importlib
import math
import pkgutil
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pytest

import engines
from engines.adaptive_load.trend import calculate_load_trend
from engines.core.athlete_context import AthleteContext
from engines.core.model_safety import finalize_model_metadata
from engines.io.data_quality_report import build_data_quality_report
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.ability_profile import build_ability_profile
from engines.performance.mader_durability import MaderDurabilityEngine, from_metabolic_snapshot
from engines.performance.power_engine import PowerEngine, detect_sprints
from engines.planning.season_planner import create_season_plan
from engines.workouts.recommendation_engine import recommend_workout

try:
    from engines.readiness.readiness_engine import compute_load_risk, compute_readiness_today
except ModuleNotFoundError:  # temporary compatibility while the package is named readness
    from engines.readness.readiness_engine import compute_load_risk, compute_readiness_today


PROJECT_ROOT = Path(__file__).resolve().parents[1]


# -----------------------------------------------------------------------------
# Shared assertions
# -----------------------------------------------------------------------------


def _walk_numbers(value: Any) -> Iterable[float]:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float, np.number)):
        yield float(value)
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_numbers(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _walk_numbers(item)


def _assert_no_nan_or_inf(payload: Any) -> None:
    bad = [x for x in _walk_numbers(payload) if not math.isfinite(x)]
    assert not bad, f"Payload contains non-finite numbers: {bad[:10]}"


def _assert_model_metadata(payload: dict[str, Any]) -> None:
    meta = payload.get("model_metadata")
    assert isinstance(meta, dict), f"Missing model_metadata in {payload}"
    assert isinstance(meta.get("assumptions"), list)
    assert isinstance(meta.get("missing_inputs"), list)
    assert isinstance(meta.get("quality_flags"), list)
    confidence = meta.get("confidence_score")
    assert isinstance(confidence, (int, float))
    assert 0.0 <= float(confidence) <= 1.0


# -----------------------------------------------------------------------------
# Hard gates: these are true regression blockers.
# -----------------------------------------------------------------------------


def test_model_safety_metadata_is_bounded_and_penalizes_missing_inputs() -> None:
    meta = finalize_model_metadata(
        assumptions=["z", "z", "a"],
        missing_inputs=["weight_kg"],
        quality_flags=["cold_start"],
        confidence=9.0,
    )
    assert meta["assumptions"] == ["a", "z"]
    assert meta["missing_inputs"] == ["weight_kg"]
    assert meta["quality_flags"] == ["cold_start"]
    assert meta["confidence_score"] <= 0.55


def test_power_engine_work_uses_elapsed_time_not_sample_count() -> None:
    class Stream2Hz:
        def __init__(self) -> None:
            n = 120
            self.elapsed_s = np.arange(n, dtype=float) * 0.5
            self.power = np.full(n, 200.0, dtype=float)
            self.heart_rate = np.full(n, 140.0, dtype=float)
            self.total_elapsed_s = float(self.elapsed_s[-1] + 0.5)

    out = PowerEngine(ftp=250.0, weight_kg=70.0).analyze(Stream2Hz())
    assert out["status"] == "success"
    assert abs(out["metrics"]["work_kj"] - 12.0) < 0.2
    _assert_no_nan_or_inf(out)


def test_detect_sprints_includes_exact_three_second_effort() -> None:
    power = np.array([100, 500, 500, 500, 100], dtype=float)
    time_s = np.array([0, 1, 2, 3, 4], dtype=float)
    sprints = detect_sprints(power, time_s, ftp=250.0)
    assert len(sprints) == 1
    assert sprints[0]["duration_s"] >= 3.0


def test_metabolic_profiler_clips_measured_lacap_to_plausible_range() -> None:
    profiler = MetabolicProfiler(weight=72.0, context=AthleteContext())
    mmp = {15: 900, 60: 500, 300: 320, 1200: 270}
    high = profiler.generate_metabolic_snapshot(mmp, measured_lacap=99.0)
    low = profiler.generate_metabolic_snapshot(mmp, measured_lacap=1.0)
    assert high["status"] == "success"
    assert low["status"] == "success"
    assert high["assumed_la_capacity_mmol_L"] <= 30.0
    assert low["assumed_la_capacity_mmol_L"] >= 8.0
    _assert_no_nan_or_inf(high)
    _assert_no_nan_or_inf(low)


def test_mader_durability_uses_unmasked_mlss_fallback() -> None:
    snapshot = {
        "status": "success",
        "estimated_vo2max": 50.0,
        "estimated_vlamax_mmol_L_s": 0.5,
        "mlss_power_watts": None,
        "unmasked_estimates": {
            "estimated_vo2max": 50.0,
            "estimated_vlamax_mmol_L_s": 0.5,
            "mlss_power_watts": 260.0,
        },
        "context_used": {"resolved_eta": 0.23},
        "assumed_la_capacity_mmol_L": 14.0,
    }
    engine = from_metabolic_snapshot(snapshot, weight_kg=72.0)
    assert engine is not None
    out = engine.compute(np.full(300, 280.0), dt=1.0)
    assert out["status"] == "success"
    _assert_no_nan_or_inf(out)


def test_readiness_with_missing_inputs_exposes_low_confidence_metadata() -> None:
    out = compute_readiness_today(
        load_state={},
        hrv_status=None,
        sleep_status=None,
        subjective=None,
    )
    assert out["status"] == "success"
    _assert_model_metadata(out)
    assert out["model_metadata"]["missing_inputs"]
    assert out["model_metadata"]["confidence_score"] <= 0.55
    _assert_no_nan_or_inf(out)


def test_load_risk_cold_start_exposes_metadata() -> None:
    out = compute_load_risk({"acute_load": 50.0, "chronic_load": 0.0}, planned_load=30.0)
    assert out["status"] == "success"
    _assert_model_metadata(out)
    assert "chronic_load" in out["model_metadata"]["missing_inputs"]
    assert "cold_start_low_chronic_load" in out["model_metadata"]["quality_flags"]


def test_workout_recommendation_blocks_power_targets_without_cp_or_ftp() -> None:
    out = recommend_workout({"weight_kg": 70.0}, readiness={"readiness_score": 85})
    assert out["status"] == "insufficient_profile"
    assert out["recommendation"]["workout"] is None
    _assert_model_metadata(out)
    assert "athlete_profile.cp_or_ftp" in out["model_metadata"]["missing_inputs"]


def test_workout_recommendation_blocks_without_readiness_score() -> None:
    out = recommend_workout({"weight_kg": 70.0, "cp_w": 260})
    assert out["status"] == "insufficient_profile"
    assert out["recommendation"]["next_step"] == "provide_readiness_score"
    assert out["recommendation"]["workout"] is None
    assert "readiness.readiness_score" in out["model_metadata"]["missing_inputs"]


def test_ability_profile_hides_wkg_without_body_mass() -> None:
    out = build_ability_profile({"mmp": {"5": 1000, "60": 500, "300": 360, "1200": 300}})
    assert out["status"] == "success"
    _assert_model_metadata(out)
    assert "weight_kg" in out["model_metadata"]["missing_inputs"]
    assert all(v is None for v in out["raw_wkg"].values())


def test_history_load_trend_short_history_is_cold_start_metadata() -> None:
    short_history = [{"load": 40.0}, {"load": 50.0}, {"load": 60.0}]
    out = calculate_load_trend(short_history, current_session_load=None)
    assert out["status"] == "insufficient_data"
    _assert_model_metadata(out)
    assert "cold_start" in out["model_metadata"]["quality_flags"]


# -----------------------------------------------------------------------------
# Hard gates: regression blockers — failures must break the release gate.
# -----------------------------------------------------------------------------


def test_all_engine_submodules_import_without_side_effect_errors() -> None:
    errors: list[str] = []
    for module_info in pkgutil.walk_packages(engines.__path__, engines.__name__ + "."):
        name = module_info.name
        if ".__pycache__" in name:
            continue
        try:
            importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - diagnostic assertion
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    assert not errors, "Engine import failures:\n" + "\n".join(errors)


def test_data_quality_accepts_minimal_channel_dict_without_nonfinite_values() -> None:
    payload = {
        "power": [150, 160, 170, 180],
        "heart_rate": [130, 132, 135, 136],
        "cadence": [85, 86, 87, 88],
    }
    out = build_data_quality_report(payload)
    assert out["status"] == "success"
    _assert_no_nan_or_inf(out)


def test_season_plan_rejects_non_positive_weekly_hours() -> None:
    out = create_season_plan(
        start_date="2026-01-01",
        target_date="2026-03-01",
        weekly_hours=-8.0,
    )
    assert out["status"] == "invalid_input"
    assert out["error"] == "weekly_hours_must_be_positive"
    assert out["weeks"] == []


def test_mader_durability_output_is_bounded_for_constant_above_threshold_ride() -> None:
    engine = MaderDurabilityEngine(
        weight_kg=72.0,
        vo2max=55.0,
        vlamax=0.45,
        mlss_w=260.0,
        eta=0.23,
    )
    out = engine.compute(np.full(600, 300.0), dt=1.0)
    assert out["status"] == "success"
    assert 0 <= out["durability_loss_pct"] <= 100
    residual = out["cp_residual_curve"]
    assert min(residual) > 0
    assert max(residual) <= 260.0 + 1e-6
    _assert_no_nan_or_inf(out)


def test_no_high_risk_literal_power_or_weight_fallbacks_in_prescription_engines() -> None:
    high_risk_files = [
        PROJECT_ROOT / "engines" / "workouts" / "recommendation_engine.py",
        PROJECT_ROOT / "engines" / "performance" / "ability_profile.py",
        PROJECT_ROOT / "engines" / "planning" / "season_planner.py",
    ]
    bad: list[str] = []
    patterns = [
        re.compile(r"or\s+250(?:\.0)?\b"),
        re.compile(r"or\s+75(?:\.0)?\b"),
        re.compile(r"or\s+70(?:\.0)?\b"),
    ]
    for path in high_risk_files:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(p.search(line) for p in patterns):
                bad.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno}: {line.strip()}")
    assert not bad, "Silent physiological fallbacks found:\n" + "\n".join(bad)
