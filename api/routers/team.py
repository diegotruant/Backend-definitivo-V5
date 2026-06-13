from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_team_service
from api.helpers import json_response
from api.schemas import TeamCalibrationApplyRequest, TeamCalibrationUpdateRequest
from api.services.team_service import TeamService

router = APIRouter(prefix="/team", tags=["team"])


@router.post("/calibration/update")
def update_team_calibration(
    req: TeamCalibrationUpdateRequest,
    service: TeamService = Depends(get_team_service),
):
    return json_response(service.update_calibration(req))


@router.post("/calibration/apply")
def apply_team_calibration(
    req: TeamCalibrationApplyRequest,
    service: TeamService = Depends(get_team_service),
):
    return json_response(service.apply_calibration(req))
