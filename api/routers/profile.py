from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_profile_service
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.schemas import SnapshotRequest
from api.services.profile_service import ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])


@router.post(
    "/snapshot",
    summary="Metabolic snapshot from MMP",
    description="Full metabolic read model (VO2max, VLamax, MLSS, zones, combustion, cross-validation).",
    operation_id="profileSnapshot",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def snapshot(
    req: SnapshotRequest,
    service: ProfileService = Depends(get_profile_service),
):
    return json_response(service.build_snapshot(req))
