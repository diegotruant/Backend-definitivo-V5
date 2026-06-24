"""Laboratory data and lactate validation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_lab_service
from api.engine_schemas import (
    LabCreateResultRequest,
    LabResultValidateRequest,
    LabTextParseRequest,
    LactateThresholdsRequest,
    LactateValidateModelRequest,
    VlapeakObservedRequest,
    VlapeakValidateRequest,
)
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.services.lab_service import LabService

router = APIRouter(prefix="/lab", tags=["lab"])


@router.post("/parse-text", operation_id="labParseText", response_model=EnginePayload, responses={200: JSON_OBJECT})
def parse_text(req: LabTextParseRequest, service: LabService = Depends(get_lab_service)):
    return json_response(service.parse_text(req))


@router.post("/validate-result", operation_id="labValidateResult", response_model=EnginePayload, responses={200: JSON_OBJECT})
def validate_result(req: LabResultValidateRequest, service: LabService = Depends(get_lab_service)):
    return json_response(service.validate_result(req))


@router.post("/create-result", operation_id="labCreateResult", response_model=EnginePayload, responses={200: JSON_OBJECT})
def create_result(req: LabCreateResultRequest, service: LabService = Depends(get_lab_service)):
    payload = {k: v for k, v in req.model_dump().items() if v is not None and k != "extra"}
    payload.update(req.extra)
    return json_response(service.create_result(payload))


@router.post("/lactate/thresholds", operation_id="labLactateThresholds", response_model=EnginePayload, responses={200: JSON_OBJECT})
def lactate_thresholds(req: LactateThresholdsRequest, service: LabService = Depends(get_lab_service)):
    return json_response(service.lactate_thresholds(req))


@router.post("/lactate/validate-model", operation_id="labLactateValidateModel", response_model=EnginePayload, responses={200: JSON_OBJECT})
def lactate_validate_model(req: LactateValidateModelRequest, service: LabService = Depends(get_lab_service)):
    return json_response(service.validate_lactate_model(req))


@router.post("/vlapeak/observed", operation_id="labVlapeakObserved", response_model=EnginePayload, responses={200: JSON_OBJECT})
def vlapeak_observed(req: VlapeakObservedRequest, service: LabService = Depends(get_lab_service)):
    return json_response(service.vlapeak_observed(req))


@router.post("/vlapeak/validate", operation_id="labVlapeakValidate", response_model=EnginePayload, responses={200: JSON_OBJECT})
def vlapeak_validate(req: VlapeakValidateRequest, service: LabService = Depends(get_lab_service)):
    return json_response(service.validate_vlapeak(req))
