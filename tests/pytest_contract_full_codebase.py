"""Contract-first tests for the full product stack outside engines/ internals.

Tests encode what coaches, frontend, and API clients must see at the wire.
Failures indicate production bugs — fix services/schemas/HTTP, not the contract.
"""

from __future__ import annotations

import asyncio
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.activity_streams import load_activity_stream, stream_from_power
from api.auth.config import AuthConfig
from api.auth.service import authenticate_request
from api.domain_schemas import (
    InPersonTestEnvelope,
    TwinStateDocument,
    WorkoutDefinitionInput,
    WorkoutStepInput,
)
from api.errors import ServiceError, invalid_json_field, workout_validation_error
from api.parsing import parse_iso_date, parse_metabolic_snapshot
from api.serialization import json_response, nan_to_none
from api.services.coach_service import CoachService
from api.services.history_service import HistoryService
from api.services.integration_service import IntegrationService
from api.services.load_service import LoadService
from api.services.planning_service import PlanningService
from api.services.twin_service import TwinService
from api.services.workout_service import WorkoutService
from api.engine_schemas import IntegrationDeduplicateRequest
from api.coach_schemas import CoachDecisionSafetyRequest
from api.nutrition_schemas import PerformanceFuelingRequest
from api.schemas import (
    AdaptWeekRequest,
    ManualLoadRequest,
    TwinStateBuildRequest,
    TwinStateUpdateRideRequest,
    WorkoutFeasibilityRequest,
)
from api_app import app
from tests._fixtures import twin_build_payload, workout_pct_cp

client = TestClient(app)

ATHLETE = {"weight_kg": 72, "cp_w": 260, "ftp_w": 250}
SNAPSHOT = {
    "mlss_power_watts": 275,
    "confidence_score": 0.35,
    "expressiveness": {"reliability": {"mlss": False}},
}


# ---------------------------------------------------------------------------
# API plumbing
# ---------------------------------------------------------------------------


class TestSerializationContracts:
    def test_nan_and_inf_become_null(self) -> None:
        payload = {"a": float("nan"), "b": float("inf"), "c": [1.0, float("nan")]}
        cleaned = nan_to_none(payload)
        assert cleaned == {"a": None, "b": None, "c": [1.0, None]}

    def test_json_response_never_emits_nan(self) -> None:
        response = json_response({"score": float("nan"), "nested": {"x": float("inf")}})
        body = json.loads(response.body)
        assert body["score"] is None
        assert body["nested"]["x"] is None

    def test_numpy_scalar_sanitized(self) -> None:
        assert nan_to_none(np.float64(float("nan"))) is None
        assert nan_to_none(np.int64(42)) == 42


class TestParsingContracts:
    def test_invalid_iso_date_is_400(self) -> None:
        with pytest.raises(HTTPException) as exc:
            parse_iso_date("not-a-date", "start_date")
        assert exc.value.status_code == 400

    def test_invalid_metabolic_snapshot_json_is_400(self) -> None:
        with pytest.raises(HTTPException) as exc:
            parse_metabolic_snapshot("{bad")
        assert exc.value.status_code == 400

    def test_metabolic_snapshot_must_be_object(self) -> None:
        with pytest.raises(HTTPException) as exc:
            parse_metabolic_snapshot("[1,2,3]")
        assert exc.value.status_code == 400


class TestActivityStreamContracts:
    def test_power_json_stream_never_synthesizes_hr(self) -> None:
        stream = stream_from_power([200, 210, 220])
        assert stream.has_heart_rate is False
        provenance = getattr(stream, "data_provenance", {})
        assert "heart_rate" not in provenance.get("synthetic_signals", [])

    def test_power_json_stream_accepts_explicit_hr(self) -> None:
        stream = stream_from_power([200, 210], heart_rate=[140, 142])
        assert stream.has_heart_rate is True

    def test_load_stream_requires_file_or_power_json(self) -> None:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(load_activity_stream(None, None))
        assert exc.value.status_code == 400

    def test_invalid_power_json_is_400(self) -> None:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(load_activity_stream(None, "not-json"))
        assert exc.value.status_code == 400

    def test_empty_power_json_is_400(self) -> None:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(load_activity_stream(None, "[]"))
        assert exc.value.status_code == 400


class TestAuthContracts:
    def _config(self, **overrides: object) -> AuthConfig:
        base = {
            "mode": "api_key",
            "require_athlete_id": True,
            "valid_api_keys": frozenset({"secret-key"}),
            "api_key_athlete_prefixes": {"secret-key": ["athlete_"]},
            "jwt_secret": None,
            "jwt_algorithms": ("HS256",),
            "jwt_audience": None,
            "jwt_issuer": None,
            "jwt_jwks_url": None,
            "athlete_scoped_prefixes": ("/ride", "/profile"),
            "protected_prefixes": ("/ride", "/profile", "/coach"),
        }
        base.update(overrides)
        return AuthConfig(**base)  # type: ignore[arg-type]

    def test_protected_route_without_token_is_401(self) -> None:
        out = authenticate_request(
            path="/coach/decision-safety",
            authorization=None,
            athlete_header=None,
            config=self._config(),
        )
        assert out.ok is False
        assert out.status_code == 401

    def test_athlete_scoped_route_requires_header(self) -> None:
        out = authenticate_request(
            path="/ride/ingest",
            authorization="Bearer secret-key",
            athlete_header=None,
            config=self._config(),
        )
        assert out.ok is False
        assert out.status_code == 400
        assert out.body["detail"]["error"] == "MISSING_ATHLETE_ID"

    def test_api_key_wrong_athlete_prefix_is_403(self) -> None:
        out = authenticate_request(
            path="/ride/ingest",
            authorization="Bearer secret-key",
            athlete_header="other_99",
            config=self._config(),
        )
        assert out.ok is False
        assert out.status_code == 403


class TestErrorContracts:
    def test_service_error_carries_code(self) -> None:
        err = ServiceError("bad", status_code=422, code="VALIDATION")
        assert err.code == "VALIDATION"
        assert err.status_code == 422

    def test_workout_validation_error_maps_code(self) -> None:
        err = workout_validation_error(ValueError("missing steps"))
        assert err.code == "WORKOUT_VALIDATION"

    def test_invalid_json_field_maps_code(self) -> None:
        err = invalid_json_field("payload", ValueError("x"))
        assert err.code == "INVALID_JSON"


# ---------------------------------------------------------------------------
# Schema boundary
# ---------------------------------------------------------------------------


class TestDomainSchemaContracts:
    def test_workout_rejects_empty_steps(self) -> None:
        with pytest.raises(ValidationError):
            WorkoutDefinitionInput(title="Empty", steps=[])

    def test_workout_step_duration_alias_resolves(self) -> None:
        step = WorkoutStepInput(type="work", duration=120, target_w=200)
        assert step.duration_s == 120

    def test_twin_rejects_wrong_schema_version(self) -> None:
        with pytest.raises(ValidationError):
            TwinStateDocument(
                schema_version="twin_state.v0",  # type: ignore[arg-type]
                athlete_id="a1",
                created_at="2024-01-01T00:00:00Z",
                updated_at="2024-01-01T00:00:00Z",
            )

    def test_in_person_rejects_unknown_protocol(self) -> None:
        with pytest.raises(ValidationError):
            InPersonTestEnvelope.model_validate({"test_type": "invalid_protocol"})


# ---------------------------------------------------------------------------
# Service orchestration (wire contract, not engine math)
# ---------------------------------------------------------------------------


class TestServiceContracts:
    def test_twin_build_returns_canonical_schema(self) -> None:
        out = TwinService().build(TwinStateBuildRequest(payload=twin_build_payload()))
        assert out["schema_version"] == "twin_state.v1"
        assert out["athlete_id"] == "athlete_1"

    def test_twin_ride_update_propagates_training_load(self) -> None:
        base = TwinService().build(TwinStateBuildRequest(payload=twin_build_payload()))
        req = TwinStateUpdateRideRequest(
            twin_state=TwinStateDocument.model_validate(base),
            ride_summary={"headline": {"training_load": 95, "tss": 95}},
        )
        out = TwinService().update_from_ride(req)
        assert out["load_state"]["acute_load"] > 0
        assert out["load_state"]["session_load"] == 95.0

    def test_planning_adapt_week_fractional_readiness_keeps_plan(self) -> None:
        out = PlanningService().adapt_week(
            AdaptWeekRequest(
                week_plan=[{"type": "vo2", "duration_min": 60}],
                readiness={"readiness_score": 0.82},
                compliance={"compliance_score": 78},
            )
        )
        assert out["reason"] == "keep_plan"

    def test_history_load_empty_activities_insufficient(self) -> None:
        out = HistoryService().load(SimpleNamespace(activities=[], as_of=None))
        assert out["status"] == "insufficient_data"

    def test_load_service_nan_rpe_at_engine_boundary(self) -> None:
        with pytest.raises(ValidationError):
            ManualLoadRequest(duration_min=30, rpe=float("nan"))

    def test_integration_deduplicate_detects_replay(self) -> None:
        act = {"start_time": "2026-01-01", "distance_m": 10000, "duration_s": 3600, "source_id": "x1"}
        out = IntegrationService().deduplicate(IntegrationDeduplicateRequest(activities=[act, act]))
        assert out["duplicate_count"] == 1

    def test_coach_decision_safety_fractional_readiness_not_low(self) -> None:
        out = CoachService().decision_safety(
            CoachDecisionSafetyRequest(
                athlete_id="svc-1",
                readiness_state={"readiness_score": 0.85},
            )
        )
        reasons = out["decision_safety"]["reasons"]
        assert "readiness_low" not in reasons
        assert "readiness_very_low" not in reasons

    def test_coach_fueling_fractional_readiness_not_red_flag(self) -> None:
        out = CoachService().performance_fueling_targets(
            PerformanceFuelingRequest(
                athlete=ATHLETE,
                readiness_state={"readiness_score": 0.8},
            )
        )
        assert "low_energy_availability_risk" not in out.get("red_flags", [])

    def test_workout_feasibility_missing_w_prime_insufficient(self) -> None:
        out = WorkoutService().analyze_feasibility(
            WorkoutFeasibilityRequest(
                workout=WorkoutDefinitionInput.model_validate(workout_pct_cp()),
                athlete_profile={"cp_w": 260},
            )
        )
        assert out["status"] == "insufficient_data"


# ---------------------------------------------------------------------------
# HTTP — coach family semantic contracts
# ---------------------------------------------------------------------------


COACH_SEMANTIC_CASES = [
    (
        "/coach/decision-safety",
        {"athlete_id": "http-1", "readiness_state": {"readiness_score": 0.85}},
        lambda b: "readiness_low" not in b["decision_safety"]["reasons"],
    ),
    (
        "/coach/attention",
        {"athlete_id": "http-2", "last_compliance": {"compliance_score": 0.65}},
        lambda b: "high_fatigue_low_compliance" not in b["athlete_attention"]["reasons"],
    ),
    (
        "/coach/communication-draft",
        {"athlete_id": "http-3"},
        lambda b: b["communication_draft"]["coach_review_required"] is True,
    ),
    (
        "/coach/nutrition/performance-targets",
        {"athlete": ATHLETE, "readiness_state": {"readiness_score": 0.8}},
        lambda b: "low_energy_availability_risk" not in b.get("red_flags", []),
    ),
    (
        "/coach/environment-adjustment",
        {"athlete_id": "http-4", "environment_context": {"temperature_c": 36, "humidity_pct": 80}},
        lambda b: b["environment_adjustment"]["intensity_cap_adjustment_pct"] < 100,
    ),
    (
        "/coach/strength/prescription",
        {"athlete": ATHLETE, "injury_flags": ["acute_pain"]},
        lambda b: b["decision_safety"]["level"] != "ok_to_auto_suggest",
    ),
    (
        "/coach/periodization",
        {
            "athlete_id": "http-5",
            "upcoming_bike_sessions": [{"date": "2026-06-02", "type": "vo2"}],
            "strength_prescription": {"scheduled_days": ["2026-06-02"]},
        },
        lambda b: bool(b["periodization_review"]["conflicts"]),
    ),
    (
        "/coach/pnei-context",
        {"athlete_id": "http-6", "readiness_state": {"readiness_score": 0.8}},
        lambda b: b["pnei_context"]["status"] != "professional_review",
    ),
    (
        "/coach/endocrine-context",
        {"athlete_id": "http-7", "readiness_state": {"readiness_score": 0.8}},
        lambda b: b["endocrine_context"]["status"] != "professional_review",
    ),
]


class TestCoachHttpContracts:
    @pytest.mark.parametrize("path,payload,check", COACH_SEMANTIC_CASES, ids=[c[0] for c in COACH_SEMANTIC_CASES])
    def test_coach_semantic_contract(self, path: str, payload: dict, check) -> None:
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text[:400]
        assert check(response.json())

    COACH_MINIMAL_ENDPOINTS = [
        "/coach/daily-brief",
        "/coach/session-decision",
        "/coach/checkin",
        "/coach/adherence",
        "/coach/testing-plan",
        "/coach/race-execution",
        "/coach/constraints",
        "/coach/training-safety",
        "/coach/equipment-comfort",
        "/coach/female-athlete-context",
        "/coach/attention/roster",
    ]

    @pytest.mark.parametrize("path", COACH_MINIMAL_ENDPOINTS)
    def test_coach_minimal_payload_never_500(self, path: str) -> None:
        payload = {"athlete_id": "minimal-1"}
        if path == "/coach/checkin":
            payload = {"checkin": {"stress": 5, "motivation": 7}}
        if path == "/coach/session-decision":
            payload = {"athlete_id": "minimal-1", "planned_session": {"type": "endurance", "duration_min": 60}}
        if path == "/coach/attention/roster":
            payload = {"roster": [{"athlete_id": "minimal-2"}]}
        if path == "/coach/testing-plan":
            payload = {"athlete_id": "minimal-1", "metabolic_snapshot": SNAPSHOT}
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text[:300]


# ---------------------------------------------------------------------------
# HTTP — core athlete workflows
# ---------------------------------------------------------------------------


class TestCoreHttpContracts:
    def test_planning_adapt_week_fractional_readiness_via_http(self) -> None:
        response = client.post(
            "/planning/adapt-week",
            json={
                "week_plan": [{"type": "vo2", "duration_min": 60}],
                "readiness": {"readiness_score": 0.82},
                "compliance": {"compliance_score": 78},
            },
        )
        assert response.status_code == 200
        assert response.json()["reason"] == "keep_plan"

    def test_workouts_recommend_fractional_readiness_not_recovery(self) -> None:
        response = client.post(
            "/workouts/recommend",
            json={
                "athlete_profile": {**ATHLETE, "mmp": {"60": 400, "300": 320, "1200": 280}},
                "readiness": {"readiness_score": 0.82},
            },
        )
        assert response.status_code == 200
        assert response.json()["recommendation"]["focus"] != "recovery"

    def test_twin_build_validate_roundtrip(self) -> None:
        built = client.post("/twin/state/build", json={"payload": twin_build_payload()})
        assert built.status_code == 200
        state = built.json()
        validated = client.post("/twin/state/validate", json={"twin_state": state})
        assert validated.status_code == 200
        assert validated.json()["schema_version"] == "twin_state.v1"

    def test_planning_empty_plan_rejected_at_api_boundary(self) -> None:
        response = client.post("/planning/check-load-risk", json={"plan": []})
        assert response.status_code == 422

    def test_history_load_rejects_empty_activities_at_schema(self) -> None:
        response = client.post("/history/load", json={"activities": []})
        assert response.status_code == 422

    def test_json_responses_are_finite(self) -> None:
        endpoints = [
            ("/load/manual", {"duration_min": 45, "rpe": 7}),
            ("/readiness/today", {"load_state": {"acute_load": 50, "chronic_load": 45}}),
            ("/planning/create-season-plan", {
                "start_date": "2026-06-01",
                "target_date": "2026-07-01",
                "weekly_hours": 8,
            }),
        ]
        for path, payload in endpoints:
            response = client.post(path, json=payload)
            assert response.status_code == 200, f"{path}: {response.text[:200]}"
            text = response.text
            assert "NaN" not in text and "Infinity" not in text
            _assert_no_non_finite(response.json())

    def test_integrations_normalize_assigns_activity_id(self) -> None:
        response = client.post(
            "/integrations/activity/normalize",
            json={"activity": {"duration_s": 3600, "power_w": 200}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["activity"]["activity_id"]


def _assert_no_non_finite(obj: object) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _assert_no_non_finite(v)
    elif isinstance(obj, list):
        for v in obj:
            _assert_no_non_finite(v)
    elif isinstance(obj, float):
        assert math.isfinite(obj)


# ---------------------------------------------------------------------------
# Ride + workout HTTP contracts
# ---------------------------------------------------------------------------


class TestRideWorkoutHttpContracts:
    def test_ride_summary_power_json_returns_headline(self) -> None:
        power = [180 + (i % 30) for i in range(300)]
        response = client.post(
            "/ride/summary",
            data={"weight_kg": "72", "power_json": json.dumps(power)},
        )
        assert response.status_code == 200, response.text[:300]
        body = response.json()
        assert body["stream_metadata"]["duration_s"] > 0
        assert "headline" in body

    def test_workouts_compare_good_execution_scores_high(self) -> None:
        workout = {
            "title": "steady",
            "steps": [{"type": "work", "duration_s": 120, "target_w": 200}],
        }
        power = [198 + (i % 5) for i in range(120)]
        response = client.post(
            "/workouts/compare",
            data={
                "workout_json": json.dumps(workout),
                "power_json": json.dumps(power),
                "athlete_profile_json": json.dumps(ATHLETE),
            },
        )
        assert response.status_code == 200, response.text[:300]
        body = response.json()
        assert body.get("compliance_score", 0) >= 70

    def test_performance_ability_profile_fractional_compliance_scale(self) -> None:
        response = client.post(
            "/performance/ability-profile",
            json={
                "athlete_profile": {**ATHLETE, "mmp": {"60": 400, "300": 320, "1200": 280}},
                "weight_kg": 72,
                "compliance_history": [{"compliance_score": 0.78}],
            },
        )
        assert response.status_code == 200
        levels = response.json().get("levels") or {}
        assert levels["execution_consistency"] >= 7.0

    def test_twin_workout_update_reads_fractional_compliance(self) -> None:
        built = client.post("/twin/state/build", json={"payload": twin_build_payload()})
        state = built.json()
        compare = client.post(
            "/workouts/compare",
            data={
                "workout_json": json.dumps({
                    "title": "steady",
                    "steps": [{"type": "work", "duration_s": 60, "target_w": 200}],
                }),
                "power_json": json.dumps([200] * 60),
            },
        )
        assert compare.status_code == 200
        compliance = compare.json()
        updated = client.post(
            "/twin/state/update-from-workout-result",
            json={"twin_state": state, "compliance_result": compliance},
        )
        assert updated.status_code == 200
        results = updated.json().get("last_compliance_results") or []
        assert results
        stored = results[-1]
        inner = stored.get("result") or stored
        score = inner.get("compliance_score")
        assert score is None or score >= 50


# ---------------------------------------------------------------------------
# API package import health
# ---------------------------------------------------------------------------


class TestApiPackageIntegrity:
    @pytest.mark.parametrize(
        "module_name",
        [
            "api.app",
            "api.serialization",
            "api.parsing",
            "api.activity_streams",
            "api.upload",
            "api.auth.service",
            "api.services.coach_service",
            "api.services.twin_service",
            "api.services.workout_service",
            "api.services.ride_service",
            "api.services.history_service",
            "api.services.planning_service",
            "api.services.readiness_service",
            "api.services.integration_service",
        ],
    )
    def test_api_module_importable(self, module_name: str) -> None:
        import importlib

        mod = importlib.import_module(module_name)
        assert mod is not None
