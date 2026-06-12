from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from engines.workouts.compliance_engine import compare_workout_to_activity
from engines.workouts.feasibility_engine import analyze_workout_feasibility
from engines.workouts.models import WorkoutValidationError, validate_workout_payload
from tests._hardening_utils import assert_json_safe, deadline, finite_score


@dataclass
class DummyStream:
    power: np.ndarray
    heart_rate: np.ndarray
    cadence: np.ndarray

    @property
    def n_samples(self) -> int:
        return int(max(len(self.power), len(self.heart_rate), len(self.cadence)))

    @property
    def total_elapsed_s(self) -> int:
        return self.n_samples

    @property
    def has_power(self) -> bool:
        return bool(np.any(np.asarray(self.power) > 0))

    @property
    def has_heart_rate(self) -> bool:
        return bool(np.any(np.asarray(self.heart_rate) > 0))


@pytest.mark.hardening
@pytest.mark.stress
def test_feasibility_large_pathological_workout_finishes_with_bounded_scores() -> None:
    steps: list[dict[str, Any]] = []
    for i in range(1_200):
        steps.append({
            "step_id": f"s{i}",
            "type": "work" if i % 2 == 0 else "recovery",
            "duration_s": 1,
            "target_w": 520 if i % 2 == 0 else 80,
            "is_key_step": i % 10 == 0,
        })
    workout = {"title": "Pathological 1200 step workout", "steps": steps}

    with deadline(2.5):
        out = analyze_workout_feasibility(workout, {"cp_w": 275, "w_prime_j": 18_000, "weight_kg": 70})

    assert out["status"] == "success"
    finite_score(out["feasibility_score"])
    assert 0 <= out["feasibility_score"] <= 100
    assert 0 <= out["confidence_score"] <= 1
    assert len(out["step_analysis"]) == len(steps)
    assert_json_safe(out)


@pytest.mark.hardening
def test_feasibility_insufficient_profile_is_reported_not_crashed(simple_power_workout: dict[str, Any]) -> None:
    out = analyze_workout_feasibility(simple_power_workout, {"weight_kg": 70})
    assert out["status"] == "insufficient_data"
    assert out["feasibility_score"] is None
    assert out["classification"] == "unknown"
    assert_json_safe(out)


@pytest.mark.hardening
@pytest.mark.stress
def test_compliance_large_activity_with_nan_segments_finishes_and_is_json_safe() -> None:
    workout = {
        "title": "Many short targets",
        "steps": [
            {"step_id": f"s{i}", "type": "work" if i % 3 == 0 else "recovery", "duration_s": 5, "target_w": 260 if i % 3 == 0 else 120, "is_key_step": i % 3 == 0}
            for i in range(500)
        ],
    }
    power = np.array(([260.0] * 5 + [120.0] * 10) * 167, dtype=float)[:2500]
    power[100:120] = np.nan
    hr = np.full_like(power, 145.0)
    cadence = np.full_like(power, 88.0)

    with deadline(2.5):
        out = compare_workout_to_activity(workout, DummyStream(power, hr, cadence), {"cp_w": 280, "w_prime_j": 20_000})

    assert out["status"] == "success"
    finite_score(out["compliance_score"])
    assert 0 <= out["compliance_score"] <= 100
    assert 0 <= out["confidence_score"] <= 1
    assert len(out["intervals"]) == 500
    assert_json_safe(out)


@pytest.mark.hardening
def test_compliance_empty_stream_returns_structured_failure(simple_power_workout: dict[str, Any]) -> None:
    stream = DummyStream(np.array([]), np.array([]), np.array([]))
    out = compare_workout_to_activity(simple_power_workout, stream, {})
    assert out["status"] == "failed"
    assert out["reason"] == "EMPTY_ACTIVITY_STREAM"
    assert out["confidence_score"] == 0.0
    assert out["discrepancies"][0]["type"] == "empty_activity"
    assert_json_safe(out)


@pytest.mark.hardening
def test_workout_validator_rejects_bad_payloads_without_looping() -> None:
    bad_payloads: list[Any] = [
        None,
        [],
        {"title": "missing steps"},
        {"steps": []},
        {"steps": [{"duration_s": 0, "target_w": 200}]},
        {"steps": [{"duration_s": -10, "target_w": 200}]},
        {"steps": ["not a step"]},
    ]
    for payload in bad_payloads:
        with deadline(0.25), pytest.raises(WorkoutValidationError):
            validate_workout_payload(payload)  # type: ignore[arg-type]
