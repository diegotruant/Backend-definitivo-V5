from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_load_service
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.schemas import ManualLoadRequest
from api.services.load_service import LoadService

router = APIRouter(tags=["load"])


@router.post(
    "/load/manual",
    summary="Inject manual non-cycling load",
    description="Approximate training load from RPE × duration (gym, run, life stress).",
    operation_id="loadManual",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def manual_load(
    req: ManualLoadRequest,
    service: LoadService = Depends(get_load_service),
):
    return json_response(service.calculate_manual(req))
