"""Exhaustive edge-case tests for validate → prescribe → feasibility → compare.

These tests encode product contracts and regressions found during perfection hardening.
They are allowed to fail first when exposing bugs; engine fixes must make them pass.
"""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.activity_streams import stream_from_power
from api_app import app
from engines.workouts.compliance_engine import compare_workout_to_activity
from engines.workouts.feasibility_engine import analyze_workout_feasibility
from engines.workouts.models import (
    WorkoutValidationError,
    materialize_workout,
    validate_workout_payload,
)

client = TestClient(app)

PROFILE = {"cp_w": 260, "w_prime_j": 18000, "ftp_w": 250, "weight_kg": 72}
INTERVAL_WORKOUT = {
    "title": "VO2 repeats",
    "steps": [
        {"step_id": "w1", "type": "warmup", "duration_s": 600, "target_w": 150},
        {
            "step_id": "i1",
            "type": "work",
            "duration_s": 240,
            "target_w": 320,
            "is_key_step": True,
        },
        {"step_id": "r1", "type": "recovery", "duration_s": 180, "target_w": 120},
    ],
}


class TestValidatePerfection:
    def test_engine_rejects_empty_steps(self) -> None:
        with pytest.raises(WorkoutValidationError, match="non-empty"):
            validate_workout_payload({"steps": []})

    def test_api_rejects_empty_steps(self) -> None:
        response = client.post("/workouts/validate", json={"workout": {"steps": []}})
        assert response.status_code == 422

    def test_api_rejects_negative_duration(self) -> None:
        response = client.post(
            "/workouts/validate",
            json={"workout": {"steps": [{"duration_s": -10, "target_w": 200}]}},
        )
        assert response.status_code == 422

    def test_warns_on_key_step_without_measurable_target(self) -> None:
        out = validate_workout_payload(
            {"steps": [{"duration_s": 600, "type": "work", "is_key_step": True}]}
        )
        assert any("no measurable target" in w.lower() for w in out["warnings"])

    def test_warns_on_duplicate_step_ids(self) -> None:
        out = validate_workout_payload(
            {
                "steps": [
                    {"step_id": "dup", "duration_s": 300, "target_w": 200, "type": "work"},
                    {"step_id": "dup", "duration_s": 300, "target_w": 180, "type": "recovery"},
                ]
            }
        )
        assert any("duplicate step_id" in w.lower() for w in out["warnings"])

    def test_valid_workout_returns_structured_summary(self) -> None:
        response = client.post("/workouts/validate", json={"workout": INTERVAL_WORKOUT})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "valid"
        assert body["summary"]["n_steps"] == 3
        assert body["summary"]["key_steps"] == 1


class TestPrescribePerfection:
    def test_resolves_pct_ftp_with_ftp_only_profile(self) -> None:
        workout = {"steps": [{"duration_s": 300, "target_pct_ftp": 95, "type": "work"}]}
        out = materialize_workout(workout, {"ftp_w": 250})
        step = out["steps"][0]
        assert out["prescription_status"] == "resolved"
        assert step["resolved_target_w"] == pytest.approx(237.5, rel=0.01)

    def test_partial_when_pct_target_without_profile(self) -> None:
        workout = {"steps": [{"duration_s": 300, "target_pct_ftp": 95, "type": "work"}]}
        out = materialize_workout(workout, {})
        assert out["prescription_status"] == "partially_resolved"
        assert out["unresolved_steps"] == ["step_1"]
        assert out["prescription_warnings"]

    def test_partial_when_zone_type_without_fields(self) -> None:
        out = materialize_workout(
            {"steps": [{"duration_s": 600, "type": "work", "target_type": "zone"}]},
            {},
        )
        assert out["prescription_status"] == "partially_resolved"
        assert out["unresolved_steps"] == ["step_1"]

    def test_api_prescribe_partial_resolution(self) -> None:
        response = client.post(
            "/workouts/prescribe",
            json={
                "workout": {"steps": [{"duration_s": 300, "target_pct_ftp": 90, "type": "work"}]},
                "athlete_profile": {},
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["prescription"]["prescription_status"] == "partially_resolved"
        assert body["prescription"]["unresolved_steps"]

    def test_api_prescribe_resolves_cp_percent(self) -> None:
        response = client.post(
            "/workouts/prescribe",
            json={
                "workout": {"steps": [{"duration_s": 300, "target_pct_cp": 105, "type": "work"}]},
                "athlete_profile": {"cp_w": 260},
            },
        )
        assert response.status_code == 200
        step = response.json()["prescription"]["steps"][0]
        assert step["resolved_target_w"] == pytest.approx(273.0, rel=0.01)


class TestFeasibilityPerfection:
    def test_insufficient_data_without_w_prime(self) -> None:
        out = analyze_workout_feasibility(
            {"steps": [{"duration_s": 300, "target_w": 280, "type": "work"}]},
            {"cp_w": 260},
        )
        assert out["status"] == "insufficient_data"
        assert out["limiting_factor"] == "missing_w_prime"

    def test_estimates_cp_from_ftp_with_warning(self) -> None:
        out = analyze_workout_feasibility(
            {"steps": [{"duration_s": 300, "target_pct_ftp": 90, "type": "work"}]},
            {"ftp_w": 250, "w_prime_j": 20000},
        )
        assert out["status"] == "success"
        assert any(w["type"] == "cp_estimated_from_ftp" for w in out["warnings"])
        assert out["summary"]["cp_w"] == pytest.approx(257.5, rel=0.01)

    def test_impossible_intervals_classified_not_feasible(self) -> None:
        hard = {
            "steps": [
                {"duration_s": 120, "target_w": 500, "type": "work"},
                {"duration_s": 60, "target_w": 100, "type": "recovery"},
                {"duration_s": 120, "target_w": 500, "type": "work"},
            ]
        }
        out = analyze_workout_feasibility(hard, PROFILE)
        assert out["classification"] == "not_feasible"
        assert out["validity"] == "red"
        assert out["feasibility_score"] < 40

    def test_easy_endurance_classified_feasible(self) -> None:
        easy = {"steps": [{"duration_s": 3600, "target_w": 180, "type": "endurance"}]}
        out = analyze_workout_feasibility(easy, PROFILE)
        assert out["classification"] == "feasible"
        assert out["feasibility_score"] >= 85

    def test_free_step_not_simulated_but_workout_succeeds(self) -> None:
        out = analyze_workout_feasibility(
            {"steps": [{"duration_s": 300, "type": "warmup", "target_type": "free"}]},
            PROFILE,
        )
        assert out["status"] == "success"
        assert out["step_analysis"][0]["status"] == "not_simulated"

    def test_api_feasibility_rejects_invalid_step(self) -> None:
        response = client.post(
            "/workouts/feasibility",
            json={
                "workout": {"steps": [{"duration_s": 0, "target_w": 200}]},
                "athlete_profile": PROFILE,
            },
        )
        assert response.status_code == 422

    def test_api_feasibility_success_shape(self) -> None:
        response = client.post(
            "/workouts/feasibility",
            json={"workout": INTERVAL_WORKOUT, "athlete_profile": PROFILE},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert "feasibility_score" in body
        assert len(body["step_analysis"]) == 3


class TestComparePerfection:
    def test_empty_stream_returns_failed_not_success(self) -> None:
        empty = SimpleNamespace(
            power=np.array([], dtype=float),
            heart_rate=np.array([], dtype=float),
            cadence=np.array([], dtype=float),
            n_samples=0,
            has_power=False,
            has_heart_rate=False,
        )
        out = compare_workout_to_activity(INTERVAL_WORKOUT, empty, PROFILE)
        assert out["status"] == "failed"
        assert out["compliance_score"] is None
        assert out["reason"] == "EMPTY_ACTIVITY_STREAM"

    def test_api_rejects_empty_power_json(self) -> None:
        response = client.post(
            "/workouts/compare",
            data={
                "workout_json": json.dumps(INTERVAL_WORKOUT),
                "power_json": "[]",
            },
        )
        assert response.status_code == 400

    def test_missing_power_does_not_score_perfect_compliance(self) -> None:
        workout = {"steps": [{"duration_s": 120, "target_w": 250, "type": "work", "is_key_step": True}]}
        stream = stream_from_power([0] * 120)
        out = compare_workout_to_activity(workout, stream, PROFILE)
        assert out["status"] == "success"
        assert out["compliance_score"] < 55
        assert out["classification"] == "not_completed_as_prescribed"
        assert any(d["type"] == "missing_power" for d in out["discrepancies"])
        assert any(d["type"] == "intensity_unverifiable" for d in out["discrepancies"])

    def test_perfect_power_match_scores_high(self) -> None:
        stream = stream_from_power([250] * 600)
        workout = {"steps": [{"duration_s": 600, "target_w": 250, "type": "work", "is_key_step": True}]}
        out = compare_workout_to_activity(workout, stream, PROFILE)
        assert out["compliance_score"] >= 90
        assert out["classification"] == "completed_as_prescribed"

    def test_short_stream_penalizes_duration(self) -> None:
        stream = stream_from_power([250] * 100)
        workout = {"steps": [{"duration_s": 600, "target_w": 250, "type": "work", "is_key_step": True}]}
        out = compare_workout_to_activity(workout, stream, PROFILE)
        assert out["compliance_score"] < 75
        assert any(d["type"] == "short_step" for d in out["discrepancies"])

    def test_nan_power_samples_do_not_crash_compare(self) -> None:
        stream = stream_from_power([float("nan")] * 30 + [250] * 90)
        workout = {"steps": [{"duration_s": 120, "target_w": 250, "type": "work"}]}
        out = compare_workout_to_activity(workout, stream, PROFILE)
        assert out["status"] == "success"
        assert math.isfinite(out["compliance_score"])

    def test_inf_power_json_sanitized_at_api(self) -> None:
        response = client.post(
            "/workouts/compare",
            data={
                "workout_json": json.dumps(
                    {"steps": [{"duration_s": 60, "target_w": 250, "type": "work"}]}
                ),
                "power_json": json.dumps([float("inf"), 250, 250] + [250] * 57),
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert math.isfinite(body["compliance_score"])

    def test_pct_target_without_profile_stays_low_confidence(self) -> None:
        workout = {"steps": [{"duration_s": 120, "target_pct_ftp": 100, "type": "work", "is_key_step": True}]}
        stream = stream_from_power([250] * 120)
        out = compare_workout_to_activity(workout, stream, {})
        assert out["confidence_score"] <= 0.45
        assert any(d["type"] == "no_comparable_targets" for d in out["discrepancies"])


class TestWorkoutPipelineIntegration:
    def test_validate_prescribe_feasibility_chain(self) -> None:
        validate = client.post("/workouts/validate", json={"workout": INTERVAL_WORKOUT})
        assert validate.status_code == 200

        prescribe = client.post(
            "/workouts/prescribe",
            json={"workout": INTERVAL_WORKOUT, "athlete_profile": PROFILE},
        )
        assert prescribe.status_code == 200
        prescription = prescribe.json()["prescription"]
        assert prescription["prescription_status"] == "resolved"
        assert prescription["steps"][1]["resolved_target_w"] == 320

        feasibility = client.post(
            "/workouts/feasibility",
            json={"workout": INTERVAL_WORKOUT, "athlete_profile": PROFILE},
        )
        assert feasibility.status_code == 200
        assert feasibility.json()["status"] == "success"

    def test_prescribed_workout_compare_after_materialization(self) -> None:
        prescribed = materialize_workout(INTERVAL_WORKOUT, PROFILE)
        key_w = prescribed["steps"][1]["resolved_target_w"]
        power = [150] * 600 + [key_w] * 240 + [120] * 180
        stream = stream_from_power(power)
        out = compare_workout_to_activity(prescribed, stream, PROFILE)
        assert out["compliance_score"] >= 85
