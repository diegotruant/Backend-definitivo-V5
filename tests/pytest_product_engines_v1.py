from fastapi.testclient import TestClient

from api.app import app


def test_history_and_records_endpoints():
    client = TestClient(app)
    payload = {
        "weight_kg": 70,
        "activities": [
            {"date": "2026-01-01", "mmp": {"60": 400, "300": 300}, "tss": 50},
            {"date": "2026-01-08", "mmp": {"60": 420, "300": 290}, "tss": 70},
        ],
    }
    r = client.post("/history/summary", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["activity_count"] == 2
    assert body["personal_records"]["records"]


def test_readiness_and_load_state_endpoints():
    client = TestClient(app)
    r = client.post("/load/state/update", json={"previous_state": {"acute_load": 30, "chronic_load": 40}, "session_load": 80})
    assert r.status_code == 200
    state = r.json()
    assert state["status"] == "success"
    r2 = client.post("/readiness/today", json={"load_state": state})
    assert r2.status_code == 200
    assert 0 <= r2.json()["readiness_score"] <= 100


def test_performance_ability_and_breakthroughs():
    client = TestClient(app)
    profile = {"weight_kg": 70, "mmp": {"5": 1000, "60": 500, "300": 350, "1200": 280, "3600": 240}}
    r = client.post("/performance/ability-profile", json={"athlete_profile": profile})
    assert r.status_code == 200
    assert "levels" in r.json()
    r2 = client.post("/performance/breakthroughs", json={"baseline_curve": {"60": 450}, "activity_curve": {"60": 500}})
    assert r2.status_code == 200
    assert r2.json()["breakthrough"] is True


def test_workout_recommend_export_and_planning():
    client = TestClient(app)
    r = client.post("/workouts/recommend", json={"athlete_profile": {"cp_w": 280, "weight_kg": 70}, "readiness": {"readiness_score": 80}})
    assert r.status_code == 200
    workout = r.json()["recommendation"]["workout"]
    if not workout.get("steps"):
        workout["steps"] = [{"duration_s": 60, "target_w": 200}]
    r2 = client.post("/workouts/export", json={"format": "erg", "workout": workout})
    assert r2.status_code == 200
    assert r2.json()["content"].startswith("[COURSE HEADER]")
    r3 = client.post(
        "/planning/create-season-plan",
        json={"start_date": "2026-01-01", "target_date": "2026-04-01", "weekly_hours": 8},
    )
    assert r3.status_code == 200
    assert r3.json()["weeks"]


def test_ride_intelligence_with_power_json():
    client = TestClient(app)
    r = client.post(
        "/ride/intelligence",
        data={"weight_kg": "70", "cp": "250", "lthr": "160", "power_json": "[100,120,200,250,300,280,150,100]"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert "best_efforts_power" in body
    assert "data_quality" in body
