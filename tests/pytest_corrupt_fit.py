"""
Regression tests for graceful handling of malformed / corrupt .FIT binaries.

The parser must never leak backend parser exception hierarchies
(FitEOFError, FitHeaderError, FitCRCError, FitParseError) to callers. Every
unrecoverable file raises a single typed FitFileError carrying a stable
`reason` code; recoverable files (corrupt trailing CRC, truncated mid-stream
with intact leading records) parse successfully via the recovery paths.

These tests fabricate corrupt binaries by mutating a real FIT file at runtime,
so they need a sample present. They are skipped cleanly if none is available.
"""

from __future__ import annotations

import glob
import os
import tempfile
from pathlib import Path

import pytest

from engines.io.fit_parser import parse_fit_file_enhanced, FitFileError, FITPARSE_AVAILABLE

pytestmark = pytest.mark.skipif(not FITPARSE_AVAILABLE, reason="no FIT parser backend installed")


def _sample_fit_bytes() -> bytes:
    repo_asset = Path(__file__).resolve().parent / "assets" / "fit" / "garmin_power_hr.fit"
    if repo_asset.is_file():
        data = repo_asset.read_bytes()
        if len(data) > 1000:
            return data
    candidates = glob.glob("/mnt/user-data/uploads/*.fit") + glob.glob("*.fit")
    for path in candidates:
        try:
            with open(path, "rb") as f:
                data = f.read()
            if len(data) > 1000:
                return data
        except OSError:
            continue
    pytest.skip("no sample .fit file available to mutate")


def _parse_bytes(data: bytes):
    path = tempfile.mktemp(suffix=".fit")
    with open(path, "wb") as f:
        f.write(data)
    try:
        return parse_fit_file_enhanced(path)
    finally:
        os.unlink(path)


def test_empty_file_raises_typed_error() -> None:
    with pytest.raises(FitFileError) as exc:
        _parse_bytes(b"")
    assert exc.value.reason == "EMPTY_FILE"


def test_one_byte_raises_typed_error() -> None:
    with pytest.raises(FitFileError) as exc:
        _parse_bytes(b"\x0e")
    assert exc.value.reason == "EMPTY_FILE"


def test_random_text_is_invalid_header() -> None:
    with pytest.raises(FitFileError) as exc:
        _parse_bytes(b"this is not a fit file" * 50)
    assert exc.value.reason == "INVALID_HEADER"


def test_all_ones_is_invalid_header() -> None:
    with pytest.raises(FitFileError) as exc:
        _parse_bytes(b"\xff" * 1024)
    assert exc.value.reason == "INVALID_HEADER"


def test_zeroed_header_is_invalid_header() -> None:
    good = _sample_fit_bytes()
    with pytest.raises(FitFileError) as exc:
        _parse_bytes(b"\x00" * 14 + good[14:])
    assert exc.value.reason == "INVALID_HEADER"


def test_header_only_is_truncated() -> None:
    good = _sample_fit_bytes()
    with pytest.raises(FitFileError) as exc:
        _parse_bytes(good[:14])
    assert exc.value.reason == "TRUNCATED"


def test_header_plus_garbage_is_malformed() -> None:
    good = _sample_fit_bytes()
    with pytest.raises(FitFileError) as exc:
        _parse_bytes(good[:14] + b"\xff\xff\xff\xff")
    assert exc.value.reason == "MALFORMED_RECORDS"


def test_corrupt_crc_recovers() -> None:
    # Only the trailing CRC is wrong — records are intact, so the parser
    # recovers with CRC checking disabled rather than raising.
    good = _sample_fit_bytes()
    stream = _parse_bytes(good[:-2] + b"\xff\xff")
    assert stream.n_samples > 0


def test_truncated_midstream_raises_typed_error() -> None:
    good = _sample_fit_bytes()
    with pytest.raises(FitFileError) as exc:
        _parse_bytes(good[: int(len(good) * 0.9)])
    assert exc.value.reason == "TRUNCATED"


def test_valid_file_still_parses() -> None:
    good = _sample_fit_bytes()
    stream = _parse_bytes(good)
    assert stream.n_samples > 0
    assert stream.has_power


def test_fitfileerror_carries_reason_and_detail() -> None:
    err = FitFileError("TRUNCATED", "ends at byte 14")
    assert err.reason == "TRUNCATED"
    assert err.detail == "ends at byte 14"
    assert "TRUNCATED" in str(err)
