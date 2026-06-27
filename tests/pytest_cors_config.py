"""CORS startup configuration tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import _resolve_cors_settings, create_app


def test_resolve_cors_settings_rejects_wildcard_with_credentials() -> None:
    with pytest.raises(ValueError, match="allow_credentials=True"):
        _resolve_cors_settings(["*"])


def test_resolve_cors_settings_allows_explicit_origins() -> None:
    origins, allow_credentials = _resolve_cors_settings(["https://app.example.com"])
    assert origins == ["https://app.example.com"]
    assert allow_credentials is True


def test_create_app_rejects_wildcard_cors_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIGITAL_TWIN_CORS_ORIGINS", "*")
    with pytest.raises(ValueError, match="allow_credentials=True"):
        create_app()


def test_create_app_accepts_explicit_cors_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIGITAL_TWIN_CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("DIGITAL_TWIN_AUTH_MODE", "none")
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200
