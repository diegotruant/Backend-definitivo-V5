"""FIT file upload parsing for HTTP endpoints."""

from __future__ import annotations

import hashlib
import logging
import tempfile
from typing import Any, Dict

from api.errors import fit_parser_unavailable, invalid_fit_file, upload_too_large
from engines.core.security import PayloadTooLarge, enforce_upload_size
from engines.io.fit_parser import FitFileError, parse_fit_file_enhanced

try:
    from fastapi import UploadFile
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
            raise upload_too_large() from exc
        chunks.append(chunk)
    data = b"".join(chunks)
    file_hash = hashlib.sha256(data).hexdigest()
    with tempfile.NamedTemporaryFile(suffix=".fit", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            stream = parse_fit_file_enhanced(tmp.name)
        except FitFileError as exc:
            logger.info("Invalid FIT upload %r: %s", file.filename, exc)
            raise invalid_fit_file() from exc
        except RuntimeError as exc:
            logger.error("FIT parser unavailable for %r: %s", file.filename, exc)
            raise fit_parser_unavailable() from exc
    return {
        "file_id": file.filename or "upload.fit",
        "file_hash": file_hash,
        "power": stream.power.tolist(),
        "laps": list(getattr(stream, "laps", []) or []),
        "_stream": stream,
    }
