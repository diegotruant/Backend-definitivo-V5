from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from api_app import app
from engines.io.fit_parser import parse_fit_records_enhanced
from engines.io.power_source_normalizer import analyze_power_source_offsets
from engines.load.manual_load import calculate_manual_load
from engines.performance.neuromuscular_profile import analyze_neuromuscular_profile
from engines.projection.season_projection_engine import project_season_from_plan
from engines.twin_state.models import build_twin_state, validate_twin_state
from engines.twin_state.state_update_engine import update_twin_state_from_ride, update_twin_state_from_workout_result


def _twin_state():
    return build_twin_state({
        "athlete_id": "athlete_1",
        "athlete_profile": {"weight_kg": 72, "cp_w": 260, "w_prime_j": 19000},
        "metabolic_snapshot": {
            "status": "success",
            "confidence_score": 0.62,
            "vo2max": 52,
            "vlamax": 0.48,
            "mlss_watts": 260,
            "w_prime_j": 19000,
        },
        "rolling_power_curve": {"60": 480, "300": 330, "1200": 275},
    })


def _workout():
    return {
        "title": "VO2 + sprint",
        "steps": [
            {"id": "warm", "type": "warmup", "duration_s": 600, "target_pct_cp": 65},
            {"id": "vo2", "type": "work", "duration_s": 240, "target_pct_cp": 118, "is_key_step": True},
            {"id": "rec", "type": "recovery", "duration_s": 240, "target_pct_cp": 55},
            {"id": "sprint", "type": "work", "duration_s": 12, "target_pct_cp": 250, "is_key_step": True},
        ],
    }


def test_twin_state_build_validate_and_updates_are_canonical():
    state = _twin_state()
    assert state["schema_version"] == "twin_state.v1"
    assert state["metabolic_metrics"]["cp_w"] == 260
    assert validate_twin_state(state)["athlete_id"] == "athlete_1"

    updated = update_twin_state_from_ride(
        state,
        ride_summary={"headline": {"np_w": 240}, "sections": {"hrv": {"alpha1_mean": 0.8}}},
        ingest_result={"curve": {"60": 500}},
        ride_id="ride_a",
    )
    assert updated["rolling_power_curve"] == {"60": 500}
    assert updated["sensor_quality"]["last_hrv"]["alpha1_mean"] == 0.8

    updated2 = update_twin_state_from_workout_result(
        updated,
        compliance_result={"classification": "completed_as_prescribed", "compliance_score": 94},
        assignment_id="w1",
    )
    assert updated2["last_compliance_results"][-1]["assignment_id"] == "w1"


def test_season_projection_moves_metrics_and_is_bounded():
    state = _twin_state()
    plan = [
        {"date": "2026-06-12", "workout": _workout()},
        {"date": "2026-06-14", "workout": _workout()},
        {"date": "2026-06-16", "training_load": 35, "modality": "strength"},
    ]
    out = project_season_from_plan(state, plan, start_date="2026-06-11", target_date="2026-06-20")
    assert out["status"] == "success"
    assert len(out["time_series"]) == 10
    assert 0.12 <= out["final_projection"]["vlamax_mmol_l_s"] <= 1.35
    assert out["confidence_score"] > 0.4


def test_neuromuscular_profile_detects_sprints_and_balance():
    start = datetime(2026, 1, 1, 8, 0, 0)
    records = []
    for i in range(420):
        p = 180
        if 60 <= i < 70:
            p = 850 - abs(i - 64) * 25
        if 240 <= i < 250:
            p = 760 - abs(i - 244) * 20
        records.append({
            "timestamp": start + timedelta(seconds=i),
            "power": p,
            "cadence": 95 + (i % 20),
            "heart_rate": 140,
            "left_right_balance": 49,
        })
    stream = parse_fit_records_enhanced(records, session_dict={"start_time": start, "sport": "cycling", "total_elapsed_time": 420})
    out = analyze_neuromuscular_profile(stream, weight_kg=72)
    assert out["status"] == "success"
    assert out["summary"]["pmax_w"] >= 800
    assert out["summary"]["n_sprints_detected"] >= 2
    assert out["summary"]["repeatability_score"] is not None


def test_power_source_normalizer_flags_offset():
    outdoor = {"power_source_id": "outdoor_meter_a", "device_name": "Outdoor meter A", "mmp": {"60": 500, "300": 330, "1200": 270}}
    indoor = {"power_source_id": "indoor_trainer_a", "device_name": "Indoor trainer A", "mmp": {"60": 535, "300": 353, "1200": 289}}
    out = analyze_power_source_offsets([outdoor, indoor], baseline_source_id="outdoor_meter_a")
    assert out["status"] == "success"
    assert out["normalization_recommendations"]["indoor_trainer_a"]["action"] == "normalize_before_profile"
    assert out["warnings"]


def test_manual_load_returns_readiness_modifier():
    out = calculate_manual_load(duration_min=50, rpe=7, modality="strength")
    assert out["status"] == "success"
    assert out["load"]["training_load_equivalent"] > 0
    assert out["load"]["readiness_modifier"] < 0


def test_new_api_endpoints_smoke():
    client = TestClient(app)
    state = _twin_state()
    r = client.post("/twin/state/build", json={"payload": state})
    assert r.status_code == 200
    r = client.post("/twin/state/project", json={
        "twin_state": state,
        "calendar_plan": [{"date": "2026-06-12", "workout": _workout()}],
        "start_date": "2026-06-11",
        "target_date": "2026-06-15",
    })
    assert r.status_code == 200
    assert r.json()["status"] == "success"
    r = client.post("/power-source/normalize", json={
        "activities": [
            {"power_source_id": "a", "mmp": {"60": 500, "300": 330}},
            {"power_source_id": "b", "mmp": {"60": 530, "300": 350}},
        ],
        "baseline_source_id": "a",
    })
    assert r.status_code == 200
    r = client.post("/load/manual", json={"duration_min": 40, "rpe": 6, "modality": "running"})
    assert r.status_code == 200
    assert r.json()["status"] == "success"
