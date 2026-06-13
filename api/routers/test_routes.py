from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.deps import get_test_service
from api.helpers import json_response, logger, parse_upload
from api.schemas import ConfirmRequest, InPersonTestRequest
from api.services.test_service import TestService
from engines.core.security import MAX_UPLOAD_FILES, safe_error_detail

router = APIRouter(prefix="/test", tags=["test"])


@router.post("/propose")
async def propose_test(
    files: List[UploadFile] = File(...),
    service: TestService = Depends(get_test_service),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=413, detail=safe_error_detail("TOO_MANY_FILES"))
    parsed = []
    for upload in files:
        try:
            payload = await parse_upload(upload)
            payload.pop("_stream", None)
            parsed.append(payload)
        except HTTPException:
            raise
        except Exception as exc:
            logger.info("Cannot parse uploaded file %r: %s", upload.filename, exc)
            raise HTTPException(status_code=422, detail=safe_error_detail("FIT_PARSE_FAILED"))
    return json_response(service.propose_from_files(parsed))


@router.post("/confirm")
def confirm_test(
    req: ConfirmRequest,
    service: TestService = Depends(get_test_service),
):
    return json_response(service.confirm(req))


@router.post("/in-person")
def in_person_test(
    req: InPersonTestRequest,
    service: TestService = Depends(get_test_service),
):
    return json_response(service.run_in_person(req))
