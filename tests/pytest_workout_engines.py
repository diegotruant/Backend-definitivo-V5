from __future__ import annotations

import numpy as np

from engines.workouts.compliance_engine import compare_workout_to_activity
from engines.workouts.feasibility_engine import analyze_workout_feasibility
from engines.workouts.models import materialize_workout, validate_workout_payload


class DummyStream:
    def __init__(self, power, hr=None, cadence=None):
        self.power = np.asarray(power, dtype=float)
        self.heart_rate = np.asarray(hr if hr is not None else [0] * len(power), dtype=float)
        self.cadence = np.asarray(cadence if cadence is not None else [0] * len(power), dtype=float)
        self.n_samples = len(power)
        self.total_elapsed_s = len(power)
        self.has_power = bool(np.any(self.power > 0))
        self.has_heart_rate = bool(np.any(self.heart_rate > 0))
        self.has_rr = False


def _workout():
    return {
        "workout_id": "w_test",
        "title": "2x3 VO2",
        "steps": [
            {"step_id": "warmup", "type": "warmup", "duration_s": 60, "target_w": 160},
            {"step_id": "i1", "type": "work", "duration_s": 180, "target_w": 330, "is_key_step": True},
            {"step_id": "r1", "type": "recovery", "duration_s": 120, "target_w": 140},
            {"step_id": "i2", "type": "work", "duration_s": 180, "target_w": 330, "is_key_step": True},
        ],
    }


def test_validate_and_materialize_workout_pct_cp():
    workout = {
        "title": "CP based",
        "steps": [{"duration_s": 120, "target_min_pct_cp": 110, "target_max_pct_cp": 120}],
    }
    valid = validate_workout_payload(workout)
    assert valid["status"] == "valid"
    prescribed = materialize_workout(workout, {"cp_w": 300})
    step = prescribed["steps"][0]
    assert step["resolved_target_min_w"] == 330
    assert step["resolved_target_max_w"] == 360


def test_feasibility_flags_impossible_workout():
    out = analyze_workout_feasibility(_workout(), {"cp_w": 270, "w_prime_j": 12000, "weight_kg": 70})
    assert out["status"] == "success"
    assert out["feasibility_score"] < 70
    assert out["classification"] in {"risky", "not_feasible", "feasible_with_caution"}
    assert out["summary"]["min_w_prime_balance_pct"] < 35


def test_compliance_good_execution_scores_high():
    workout = _workout()
    power = [160] * 60 + [332] * 180 + [140] * 120 + [328] * 180
    out = compare_workout_to_activity(workout, DummyStream(power), {"cp_w": 270, "w_prime_j": 20000})
    assert out["status"] == "success"
    assert out["compliance_score"] >= 90
    assert out["classification"] == "completed_as_prescribed"
    assert out["summary"]["completed_key_intervals"] == 2


def test_compliance_detects_missed_interval():
    workout = _workout()
    power = [160] * 60 + [332] * 180 + [140] * 120 + [210] * 180
    out = compare_workout_to_activity(workout, DummyStream(power), {"cp_w": 270, "w_prime_j": 20000})
    assert out["status"] == "success"
    assert out["compliance_score"] < 90
    assert any(d["step_id"] == "i2" for d in out["discrepancies"] if "step_id" in d)
