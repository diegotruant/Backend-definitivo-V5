from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


def _snapshot_payload() -> dict:
    return {
        "mmp": {"1": 1034, "15": 720, "60": 489, "180": 351, "360": 309, "720": 304, "1200": 280},
        "athlete": {"weight_kg": 90, "training_years": 20, "discipline": "SPRINT"},
    }


def test_api_key_auth_rejects_missing_or_invalid_key(monkeypatch) -> None:
    monkeypatch.setenv("DIGITAL_TWIN_API_KEY_AUTH_ENABLED", "true")
    monkeypatch.setenv("DIGITAL_TWIN_API_KEYS", "k-prod-1")
    monkeypatch.setenv("DIGITAL_TWIN_REQUIRE_ATHLETE_ID", "false")
    app = create_app()
    client = TestClient(app)

    r_missing = client.post("/profile/snapshot", json=_snapshot_payload())
    assert r_missing.status_code == 401
    assert r_missing.json().get("error") == "UNAUTHORIZED"

    r_bad = client.post(
        "/profile/snapshot",
        json=_snapshot_payload(),
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert r_bad.status_code == 401
    assert r_bad.json().get("error") == "UNAUTHORIZED"


def test_api_key_auth_allows_valid_key(monkeypatch) -> None:
    monkeypatch.setenv("DIGITAL_TWIN_API_KEY_AUTH_ENABLED", "true")
    monkeypatch.setenv("DIGITAL_TWIN_API_KEYS", "k-prod-1")
    monkeypatch.setenv("DIGITAL_TWIN_REQUIRE_ATHLETE_ID", "false")
    app = create_app()
    client = TestClient(app)

    ok = client.post(
        "/profile/snapshot",
        json=_snapshot_payload(),
        headers={"Authorization": "Bearer k-prod-1"},
    )
    assert ok.status_code == 200


def test_api_key_athlete_prefix_scope_blocks_cross_athlete_access(monkeypatch) -> None:
    monkeypatch.setenv("DIGITAL_TWIN_API_KEY_AUTH_ENABLED", "true")
    monkeypatch.setenv("DIGITAL_TWIN_API_KEYS", "k-coach-1")
    monkeypatch.setenv("DIGITAL_TWIN_API_KEY_ATHLETE_PREFIXES", "k-coach-1:ath-a-|ath-b-")
    monkeypatch.setenv("DIGITAL_TWIN_REQUIRE_ATHLETE_ID", "true")
    app = create_app()
    client = TestClient(app)

    allowed = client.post(
        "/profile/snapshot",
        json=_snapshot_payload(),
        headers={
            "Authorization": "Bearer k-coach-1",
            "X-Athlete-Id": "ath-a-001",
        },
    )
    assert allowed.status_code == 200

    blocked = client.post(
        "/profile/snapshot",
        json=_snapshot_payload(),
        headers={
            "Authorization": "Bearer k-coach-1",
            "X-Athlete-Id": "ath-z-999",
        },
    )
    assert blocked.status_code == 403
    assert blocked.json().get("error") == "FORBIDDEN"
