"""JWT/OAuth authentication and role-based athlete access tests."""

from __future__ import annotations

import time

import jwt
from fastapi.testclient import TestClient

from api.app import create_app

JWT_SECRET = "test-secret-for-ci-only-32-bytes-minimum-0001"
COACH_TOKEN = jwt.encode(
    {
        "sub": "coach-001",
        "roles": ["coach"],
        "team_id": "team-alpha",
        "athlete_ids": ["ath-a-001", "ath-b-002"],
        "exp": int(time.time()) + 3600,
    },
    JWT_SECRET,
    algorithm="HS256",
)
ATHLETE_TOKEN = jwt.encode(
    {
        "sub": "athlete-001",
        "roles": ["athlete"],
        "team_id": "team-alpha",
        "athlete_id": "ath-a-001",
        "exp": int(time.time()) + 3600,
    },
    JWT_SECRET,
    algorithm="HS256",
)
ADMIN_TOKEN = jwt.encode(
    {
        "sub": "admin-001",
        "roles": ["admin"],
        "exp": int(time.time()) + 3600,
    },
    JWT_SECRET,
    algorithm="HS256",
)


def _jwt_env(monkeypatch) -> None:
    monkeypatch.setenv("DIGITAL_TWIN_AUTH_MODE", "jwt")
    monkeypatch.setenv("DIGITAL_TWIN_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("DIGITAL_TWIN_REQUIRE_ATHLETE_ID", "true")


def _snapshot_payload() -> dict:
    return {
        "mmp": {"1": 1034, "15": 720, "60": 489, "180": 351, "360": 309, "720": 304, "1200": 280},
        "athlete": {"weight_kg": 90, "training_years": 20, "discipline": "SPRINT"},
    }


def test_jwt_rejects_missing_or_invalid_token(monkeypatch) -> None:
    _jwt_env(monkeypatch)
    client = TestClient(create_app())

    missing = client.post(
        "/profile/snapshot",
        json=_snapshot_payload(),
        headers={"X-Athlete-Id": "ath-a-001"},
    )
    assert missing.status_code == 401
    assert missing.json().get("error") == "UNAUTHORIZED"

    bad = client.post(
        "/profile/snapshot",
        json=_snapshot_payload(),
        headers={"Authorization": "Bearer not-a-jwt", "X-Athlete-Id": "ath-a-001"},
    )
    assert bad.status_code == 401


def test_jwt_coach_can_access_roster_athlete(monkeypatch) -> None:
    _jwt_env(monkeypatch)
    client = TestClient(create_app())
    ok = client.post(
        "/profile/snapshot",
        json=_snapshot_payload(),
        headers={"Authorization": f"Bearer {COACH_TOKEN}", "X-Athlete-Id": "ath-a-001"},
    )
    assert ok.status_code == 200


def test_jwt_coach_blocked_for_out_of_scope_athlete(monkeypatch) -> None:
    _jwt_env(monkeypatch)
    client = TestClient(create_app())
    blocked = client.post(
        "/profile/snapshot",
        json=_snapshot_payload(),
        headers={"Authorization": f"Bearer {COACH_TOKEN}", "X-Athlete-Id": "ath-z-999"},
    )
    assert blocked.status_code == 403
    assert blocked.json().get("error") == "FORBIDDEN"


def test_jwt_athlete_role_uses_token_athlete_id(monkeypatch) -> None:
    _jwt_env(monkeypatch)
    client = TestClient(create_app())
    ok = client.post(
        "/profile/snapshot",
        json=_snapshot_payload(),
        headers={"Authorization": f"Bearer {ATHLETE_TOKEN}"},
    )
    assert ok.status_code == 200

    mismatch = client.post(
        "/profile/snapshot",
        json=_snapshot_payload(),
        headers={"Authorization": f"Bearer {ATHLETE_TOKEN}", "X-Athlete-Id": "ath-b-002"},
    )
    assert mismatch.status_code == 403


def test_jwt_admin_can_access_any_athlete(monkeypatch) -> None:
    _jwt_env(monkeypatch)
    client = TestClient(create_app())
    ok = client.post(
        "/profile/snapshot",
        json=_snapshot_payload(),
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}", "X-Athlete-Id": "ath-any-999"},
    )
    assert ok.status_code == 200


def test_jwt_athlete_cannot_confirm_test(monkeypatch) -> None:
    _jwt_env(monkeypatch)
    client = TestClient(create_app())
    blocked = client.post(
        "/test/confirm",
        json={"proposal_id": "p1", "confirmed_by": "athlete"},
        headers={"Authorization": f"Bearer {ATHLETE_TOKEN}"},
    )
    assert blocked.status_code == 403


def test_jwt_coach_can_propose_test(monkeypatch) -> None:
    _jwt_env(monkeypatch)
    client = TestClient(create_app())
    # Missing files → 400, but auth must pass first
    response = client.post(
        "/test/propose",
        headers={"Authorization": f"Bearer {COACH_TOKEN}"},
    )
    assert response.status_code == 400
    assert response.json().get("detail") != "UNAUTHORIZED"
