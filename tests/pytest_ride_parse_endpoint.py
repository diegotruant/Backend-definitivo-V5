from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app

ASSET = Path(__file__).resolve().parent / "assets" / "fit" / "minimal_power_hr_lap_hrv.fit"


@pytest.mark.skipif(not ASSET.exists(), reason="golden FIT asset missing")
def test_ride_parse_endpoint_returns_full_contract(monkeypatch) -> None:
    monkeypatch.setenv("DIGITAL_TWIN_API_KEY_AUTH_ENABLED", "false")
    monkeypatch.setenv("DIGITAL_TWIN_REQUIRE_ATHLETE_ID", "false")
    app = create_app()
    client = TestClient(app)
    with ASSET.open("rb") as fh:
        response = client.post(
            "/ride/parse",
            files={"file": (ASSET.name, fh, "application/octet-stream")},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["parser_version"]
    assert payload["file_hash"]
    assert "power" in payload["available_signals"]
    assert payload["streams"]["power_w"]
    assert payload["quality"]["gap_summary"] is not None
    assert len(payload["laps"]) == 1
