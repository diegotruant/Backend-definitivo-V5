"""Contract tests for the Starlette/FastAPI HTTP test client stack."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import starlette.testclient as starlette_testclient


def test_starlette_testclient_uses_httpx2() -> None:
    assert starlette_testclient.httpx.__name__ == "httpx2"


def test_fastapi_testclient_round_trip() -> None:
    app = FastAPI()

    @app.get("/health-testclient")
    def health_testclient() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/health-testclient")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
