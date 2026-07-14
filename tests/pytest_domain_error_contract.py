"""Typed domain-error migration with unchanged public HTTP contracts."""

from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from api.activity_streams import load_activity_stream
from api.errors import (
    RequestParsingError,
    UploadDomainError,
    invalid_fit_file,
    upload_too_large,
)
from api.parsing import parse_iso_date, parse_metabolic_snapshot
from api.upload import parse_upload
from api_app import app
from engines.io.fit_parser import FitFileError

client = TestClient(app)


def test_invalid_date_uses_typed_request_error_with_legacy_compatibility() -> None:
    with pytest.raises(RequestParsingError) as exc:
        parse_iso_date("not-a-date", "ride_date")

    assert isinstance(exc.value, HTTPException)
    assert exc.value.status_code == 400
    assert exc.value.code == "INVALID_ISO_DATE"
    assert exc.value.message == "ride_date must be ISO date (YYYY-MM-DD)."


def test_snapshot_errors_are_typed_without_changing_detail_text() -> None:
    with pytest.raises(RequestParsingError) as malformed:
        parse_metabolic_snapshot("{bad")
    assert malformed.value.code == "INVALID_JSON"
    assert malformed.value.message.startswith("Invalid metabolic_snapshot_json:")

    with pytest.raises(RequestParsingError) as wrong_shape:
        parse_metabolic_snapshot("[1,2,3]")
    assert wrong_shape.value.code == "JSON_OBJECT_REQUIRED"
    assert wrong_shape.value.message == "metabolic_snapshot_json must be a JSON object."


def test_activity_input_errors_are_typed() -> None:
    with pytest.raises(RequestParsingError) as missing:
        asyncio.run(load_activity_stream(None, None))
    assert missing.value.code == "MISSING_ACTIVITY_INPUT"

    with pytest.raises(RequestParsingError) as malformed:
        asyncio.run(load_activity_stream(None, "not-json"))
    assert malformed.value.code == "INVALID_JSON"
    assert malformed.value.details == {
        "error": "INVALID_JSON",
        "message": "A JSON field in the request was malformed.",
    }

    with pytest.raises(RequestParsingError) as empty:
        asyncio.run(load_activity_stream(None, "[]"))
    assert empty.value.code == "NON_EMPTY_JSON_ARRAY_REQUIRED"


def test_upload_factories_are_typed_and_keep_public_details() -> None:
    too_large = upload_too_large()
    assert isinstance(too_large, UploadDomainError)
    assert isinstance(too_large, HTTPException)
    assert too_large.status_code == 413
    assert too_large.details == {
        "error": "FILE_TOO_LARGE",
        "message": "The uploaded file exceeds the allowed size.",
    }

    invalid = invalid_fit_file()
    assert invalid.status_code == 400
    assert invalid.details == {
        "error": "INVALID_FIT_FILE",
        "message": "The uploaded file is not a readable FIT file.",
    }


def test_parse_upload_converts_parser_failure_to_upload_domain_error(monkeypatch) -> None:
    def fail_parser(_path: str):
        raise FitFileError("INVALID_HEADER", "test")

    monkeypatch.setattr("api.upload.parse_fit_file_enhanced", fail_parser)
    upload = UploadFile(file=BytesIO(b"not-a-fit"), filename="bad.fit")

    with pytest.raises(UploadDomainError) as exc:
        asyncio.run(parse_upload(upload))

    assert exc.value.code == "INVALID_FIT_FILE"
    assert exc.value.status_code == 400


def test_invalid_power_json_http_contract_is_unchanged() -> None:
    response = client.post(
        "/ride/summary",
        data={"weight_kg": "70", "power_json": "not-json"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": {
            "error": "INVALID_JSON",
            "message": "A JSON field in the request was malformed.",
        }
    }


def test_missing_activity_http_contract_is_unchanged() -> None:
    response = client.post("/ride/summary", data={"weight_kg": "70"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Provide either a FIT file or power_json."}


def test_invalid_fit_http_contract_is_unchanged(monkeypatch) -> None:
    async def fail_upload(_file):
        raise invalid_fit_file()

    monkeypatch.setattr("api.routers.ride.parse_upload", fail_upload)
    response = client.post(
        "/ride/parse",
        files={"file": ("bad.fit", b"not-a-fit", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": {
            "error": "INVALID_FIT_FILE",
            "message": "The uploaded file is not a readable FIT file.",
        }
    }
