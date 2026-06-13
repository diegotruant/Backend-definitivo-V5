"""Application service layer — typed inputs, predictable 4xx, engine orchestration."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.domain_schemas import (
    InPersonTestEnvelope,
    PowerSourceActivity,
    TwinStateDocument,
    WorkoutDefinitionInput,
)

from api.schemas import (
    InPersonTestRequest,
    PowerSourceNormalizationRequest,
    TwinStateBuildRequest,
    WorkoutFeasibilityRequest,
    WorkoutValidateRequest,
)
from api.services.performance_service import PerformanceService
from api.services.test_service import TestService
from api.services.twin_service import TwinService
from api.services.workout_service import WorkoutService
from api_app import app
from tests._fixtures import (
    critical_power_in_person_payload,
    mader_in_person_payload,
    twin_build_payload,
    workout_pct_cp,
)

client = TestClient(app)


# --- Pydantic boundary: valid accepts, malformed rejects ---


def test_workout_definition_rejects_empty_steps() -> None:
    with pytest.raises(ValidationError):
        WorkoutDefinitionInput(title="Empty", steps=[])


def test_workout_definition_accepts_pct_cp_steps() -> None:
    model = WorkoutDefinitionInput.model_validate(workout_pct_cp())
    assert len(model.steps) == 4
    assert model.to_engine_dict()["title"] == "VO2 + sprint"


def test_twin_state_document_rejects_wrong_schema_version() -> None:
    with pytest.raises(ValidationError):
        TwinStateDocument(
            schema_version="twin_state.v0",  # type: ignore[arg-type]
            athlete_id="a1",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )


def test_in_person_envelope_rejects_unknown_test_type() -> None:
    with pytest.raises(ValidationError):
        InPersonTestEnvelope.model_validate({"test_type": "invalid_protocol"})


def test_power_source_activity_accepts_mmp_aliases() -> None:
    act = PowerSourceActivity.model_validate(
        {"power_source_id": "kickr", "mmp_curve": {"60": 500, "300": 330}}
    )
    merged = act.merged_mmp_dict()
    assert merged["60"] == 500


# --- Service orchestration ---


def test_twin_service_build_returns_canonical_state() -> None:
    svc = TwinService()
    out = svc.build(TwinStateBuildRequest(payload=twin_build_payload()))
    assert out["schema_version"] == "twin_state.v1"
    assert out["athlete_id"] == "athlete_1"


def test_workout_service_validate_empty_steps_pydantic_blocks_before_service() -> None:
    with pytest.raises(ValidationError):
        WorkoutValidateRequest(
            workout=WorkoutDefinitionInput.model_validate({"title": "bad", "steps": []})
        )


def test_workout_service_feasibility_with_minimal_profile() -> None:
    svc = WorkoutService()
    req = WorkoutFeasibilityRequest(
        workout=WorkoutDefinitionInput.model_validate(workout_pct_cp()),
        athlete_profile={"cp_w": 260, "w_prime_j": 19000, "weight_kg": 72},
    )
    out = svc.analyze_feasibility(req)
    assert out["status"] in ("success", "warning", "insufficient_profile")


def test_test_service_in_person_mader_via_service() -> None:
    svc = TestService()
    req = InPersonTestRequest.model_validate(mader_in_person_payload())
    out = svc.run_in_person(req)
    assert out.get("verdict") or out.get("status") in ("success", "proposed", "completed")


def test_test_service_in_person_critical_power_via_service() -> None:
    svc = TestService()
    req = InPersonTestRequest.model_validate(critical_power_in_person_payload())
    out = svc.run_in_person(req)
    assert out.get("status") == "success"
    assert float(out.get("cp_w", 0)) > 0


def test_performance_service_power_source_normalize() -> None:
    svc = PerformanceService()
    req = PowerSourceNormalizationRequest(
        activities=[
            PowerSourceActivity(power_source_id="a", mmp={"60": 500, "300": 330}),
            PowerSourceActivity(power_source_id="b", mmp={"60": 530, "300": 350}),
        ],
        baseline_source_id="a",
    )
    out = svc.normalize_power_sources(req)
    assert out["status"] == "success"


# --- HTTP wiring through services (4xx not 500) ---


def test_ride_summary_invalid_power_json_returns_400() -> None:
    resp = client.post("/ride/summary", data={"weight_kg": "70", "power_json": "not-json"})
    assert resp.status_code == 400
    assert "detail" in resp.json()


def test_workouts_compare_invalid_workout_json_returns_400() -> None:
    resp = client.post(
        "/workouts/compare",
        data={"workout_json": "not-json", "power_json": "[100,110]"},
    )
    assert resp.status_code == 400


def test_workouts_compare_empty_power_returns_400() -> None:
    workout = json.dumps({"title": "t", "steps": [{"duration_s": 60, "target_w": 200}]})
    resp = client.post(
        "/workouts/compare",
        data={"workout_json": workout, "power_json": "[]"},
    )
    assert resp.status_code == 400


def test_profile_snapshot_rejects_invalid_athlete_weight() -> None:
    resp = client.post(
        "/profile/snapshot",
        json={"mmp": {"60": 300}, "athlete": {"weight_kg": 10}},
    )
    assert resp.status_code == 422
