from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_team_service
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.schemas import TeamCalibrationApplyRequest, TeamCalibrationUpdateRequest
from api.services.team_service import TeamService

router = APIRouter(prefix="/team", tags=["team"], )


@router.post(
    "/calibration/update",
    summary="Update team calibration model",
    description="Add validated test events. Requires pre-test predicted_value per event.",
    operation_id="teamCalibrationUpdate",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def update_team_calibration(
    req: TeamCalibrationUpdateRequest,
    service: TeamService = Depends(get_team_service),
):
    return json_response(service.update_calibration(req))


@router.post(
    "/calibration/apply",
    summary="Apply team calibration",
    description="Apply learned correction to a snapshot or single parameter estimate.",
    operation_id="teamCalibrationApply",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def apply_team_calibration(
    req: TeamCalibrationApplyRequest,
    service: TeamService = Depends(get_team_service),
):
    return json_response(service.apply_calibration(req))
