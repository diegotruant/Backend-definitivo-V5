"""FIT file upload parsing for HTTP endpoints."""

from __future__ import annotations

import logging
import tempfile
from typing import Any, Dict

from engines.core.security import PayloadTooLarge, enforce_upload_size, safe_error_detail
from engines.io.fit_parser import FitFileError, parse_fit_file_enhanced

try:
    from fastapi import HTTPException, UploadFile
except ImportError:  # pragma: no cover
    raise ImportError("FastAPI is required for the API layer: pip install fastapi uvicorn")

logger = logging.getLogger("digital_twin.api")


async def parse_upload(file: UploadFile) -> Dict[str, Any]:
    """Read an uploaded FIT into the {file_id, power, laps, _stream} dict engines use."""
    # Read upload incrementally so oversized payloads are rejected before
    # materializing the full body in memory.
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        try:
            enforce_upload_size(total)
        except PayloadTooLarge as exc:
            logger.warning("Rejected oversized upload %r: %s", file.filename, exc)
            raise HTTPException(status_code=413, detail=safe_error_detail("FILE_TOO_LARGE")) from exc
        chunks.append(chunk)
    data = b"".join(chunks)
    with tempfile.NamedTemporaryFile(suffix=".fit", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            stream = parse_fit_file_enhanced(tmp.name)
        except FitFileError as exc:
            logger.info("Invalid FIT upload %r: %s", file.filename, exc)
            raise HTTPException(
                status_code=400,
                detail=safe_error_detail("INVALID_FIT_FILE"),
            ) from exc
        except RuntimeError as exc:
            logger.error("FIT parser unavailable for %r: %s", file.filename, exc)
            raise HTTPException(
                status_code=503,
                detail={"error": "FIT_PARSER_UNAVAILABLE", "message": "Parser temporarily unavailable."},
            ) from exc
    return {
        "file_id": file.filename or "upload.fit",
        "power": stream.power.tolist(),
        "laps": None,
        "_stream": stream,
    }
