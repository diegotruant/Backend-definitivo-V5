"""TwinState HTTP roundtrip: build → ride update → workout update → project."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from api_app import app
from tests._fixtures import twin_build_payload, workout_pct_cp

client = TestClient(app)


def _compare_workout(power: list[int]) -> dict:
    resp = client.post(
        "/workouts/compare",
        data={
            "workout_json": json.dumps(workout_pct_cp()),
            "athlete_profile_json": json.dumps({"cp_w": 260, "w_prime_j": 19000, "weight_kg": 72}),
            "power_json": json.dumps(power),
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_twin_state_full_http_roundtrip() -> None:
    # 1. Build canonical state
    build = client.post("/twin/state/build", json={"payload": twin_build_payload()})
    assert build.status_code == 200, build.text
    state = build.json()
    assert state["schema_version"] == "twin_state.v1"
    assert state["athlete_id"] == "athlete_1"

    # 2. Update after ride ingest/summary
    ride = client.post(
        "/twin/state/update-from-ride",
        json={
            "twin_state": state,
            "ride_summary": {
                "headline": {"np_w": 240},
                "sections": {"hrv": {"alpha1_mean": 0.8}},
            },
            "ingest_result": {"curve": {"60": 500}},
            "ride_id": "ride_roundtrip",
        },
    )
    assert ride.status_code == 200, ride.text
    after_ride = ride.json()
    assert after_ride["rolling_power_curve"]["60"] == 500

    # 3. Compare workout → compliance, then update TwinState
    power = [200 + (i % 30) for i in range(1800)]
    compliance = _compare_workout(power)
    assert compliance["status"] == "success"

    workout_update = client.post(
        "/twin/state/update-from-workout-result",
        json={
            "twin_state": after_ride,
            "compliance_result": compliance,
            "assignment_id": "w_roundtrip",
        },
    )
    assert workout_update.status_code == 200, workout_update.text
    after_workout = workout_update.json()
    assert after_workout["last_compliance_results"][-1]["assignment_id"] == "w_roundtrip"

    # 4. Season projection
    project = client.post(
        "/twin/state/project",
        json={
            "twin_state": after_workout,
            "calendar_plan": [{"date": "2026-06-12", "workout": workout_pct_cp()}],
            "start_date": "2026-06-11",
            "target_date": "2026-06-15",
        },
    )
    assert project.status_code == 200, project.text
    projection = project.json()
    assert projection["status"] == "success"
    assert len(projection["time_series"]) >= 1


def test_twin_build_rejects_invalid_payload_at_boundary() -> None:
    resp = client.post("/twin/state/build", json={"payload": {"athlete_id": ""}})
    assert resp.status_code == 422
    resp_empty = client.post("/twin/state/build", json={})
    assert resp_empty.status_code == 422
    state = client.post("/twin/state/build", json={"payload": twin_build_payload()}).json()
    resp = client.post(
        "/twin/state/update-from-ride",
        json={"twin_state": {"schema_version": "wrong", "athlete_id": "x"}},
    )
    assert resp.status_code == 422


def test_projection_alias_matches_primary_endpoint() -> None:
    state = client.post("/twin/state/build", json={"payload": twin_build_payload()}).json()
    body = {
        "twin_state": state,
        "calendar_plan": [],
        "start_date": "2026-06-11",
        "target_date": "2026-06-13",
    }
    primary = client.post("/twin/state/project", json=body)
    alias = client.post("/projection/season", json=body)
    assert primary.status_code == 200
    assert alias.status_code == 200
    assert primary.json()["status"] == alias.json()["status"] == "success"
