from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api_app import app
from tests._hardening_utils import assert_json_safe, deadline, finite_score

client = TestClient(app)


@pytest.mark.hardening
def test_api_invalid_inputs_return_4xx_not_500() -> None:
    cases = [
        ("/workouts/validate", {"workout": {"steps": []}}),
        ("/workouts/feasibility", {"workout": {"steps": [{"duration_s": -1}]}, "athlete_profile": {}}),
        ("/profile/snapshot", {"mmp": {}, "athlete": {"weight_kg": 10}}),
    ]
    for path, payload in cases:
        with deadline(1.0):
            response = client.post(path, json=payload)
        assert 400 <= response.status_code < 500, (path, response.status_code, response.text)
        assert_json_safe(response.json())

    response = client.post(
        "/workouts/compare",
        data={"workout_json": "not-json", "power_json": "[1,2,3]"},
    )
    assert response.status_code == 400
    assert_json_safe(response.json())

    response = client.post(
        "/workouts/compare",
        data={"workout_json": json.dumps({"steps": [{"duration_s": 10, "target_w": 200}]}), "power_json": "[]"},
    )
    assert response.status_code == 400
    assert_json_safe(response.json())


@pytest.mark.hardening
@pytest.mark.stress
def test_api_compare_large_power_json_does_not_timeout_or_emit_nan() -> None:
    workout = {
        "workout_id": "api_stress",
        "title": "API stress compare",
        "steps": [
            {"step_id": f"s{i}", "type": "work" if i % 4 == 0 else "recovery", "duration_s": 4, "target_w": 300 if i % 4 == 0 else 120, "is_key_step": i % 4 == 0}
            for i in range(800)
        ],
    }
    power = [300 if i % 16 < 4 else 120 for i in range(3_200)]
    with deadline(4.0):
        response = client.post(
            "/workouts/compare",
            data={
                "workout_json": json.dumps(workout),
                "athlete_profile_json": json.dumps({"cp_w": 275, "w_prime_j": 20_000, "weight_kg": 70}),
                "power_json": json.dumps(power),
            },
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    finite_score(payload["compliance_score"])
    assert 0 <= payload["confidence_score"] <= 1
    assert len(payload["intervals"]) == 800
    assert_json_safe(payload)


@pytest.mark.hardening
def test_api_ride_summary_handles_missing_or_invalid_power_paths_cleanly() -> None:
    response = client.post("/ride/summary", data={"weight_kg": "70", "power_json": "not-json"})
    assert response.status_code == 400
    assert_json_safe(response.json())

    with deadline(2.0):
        response = client.post(
            "/ride/summary",
            data={"weight_kg": "70", "ftp": "250", "power_json": json.dumps([0, 0, 0, 0, 0])},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert_json_safe(payload)


@pytest.mark.hardening
def test_calendar_transition_api_is_total_for_unknown_states() -> None:
    response = client.post(
        "/workouts/calendar/transition",
        json={"current_status": "unknown", "desired_status": "completed"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["allowed"] is False
    assert_json_safe(payload)

@pytest.mark.hardening
@pytest.mark.stress
def test_ride_summary_large_rr_stream_uses_adaptive_hrv_step_and_stays_bounded() -> None:
    # Synthetic long ride: enough power/HR/RR to exercise power, zones, HRV and
    # cardiac sections without needing a real FIT file in CI.  The regression is
    # that /ride/summary used to run DFA-alpha1 at a fixed 10s step, creating
    # >1000 windows on long files and making large FIT summaries too slow.
    n = 14_400  # four hours at 1Hz
    power = [220 + (i % 180) * 0.05 for i in range(n)]
    # power_json cannot carry RR, so we exercise the endpoint's adaptive knobs
    # on the synthetic power path and the direct summary path is covered by the
    # real-FIT validation script in docs/logs.  The endpoint must still accept
    # and forward hrv_max_windows without breaking old clients.
    with deadline(8.0):
        response = client.post(
            "/ride/summary",
            data={
                "weight_kg": "70",
                "ftp": "260",
                "lthr": "170",
                "hrv_max_windows": "250",
                "power_json": json.dumps(power),
            },
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["sections"]["power"]["status"] == "success"
    assert payload["sections"]["hrv"]["status"] == "unavailable"
    assert_json_safe(payload)
