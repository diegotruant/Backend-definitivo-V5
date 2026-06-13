from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_twin_service
from api.helpers import json_response
from api.schemas import (
    SeasonProjectionRequest,
    TwinStateBuildRequest,
    TwinStateUpdateRideRequest,
    TwinStateUpdateWorkoutRequest,
)
from api.services.twin_service import TwinService

router = APIRouter(tags=["twin"])


@router.post("/twin/state/build")
def twin_state_build(
    req: TwinStateBuildRequest,
    service: TwinService = Depends(get_twin_service),
):
    return json_response(service.build(req))


@router.post("/twin/state/update-from-ride")
def twin_state_update_from_ride(
    req: TwinStateUpdateRideRequest,
    service: TwinService = Depends(get_twin_service),
):
    return json_response(service.update_from_ride(req))


@router.post("/twin/state/update-from-workout-result")
def twin_state_update_from_workout(
    req: TwinStateUpdateWorkoutRequest,
    service: TwinService = Depends(get_twin_service),
):
    return json_response(service.update_from_workout(req))


@router.post("/twin/state/project")
def twin_state_project(
    req: SeasonProjectionRequest,
    service: TwinService = Depends(get_twin_service),
):
    return json_response(service.project_season(req))


@router.post("/projection/season")
def projection_season(
    req: SeasonProjectionRequest,
    service: TwinService = Depends(get_twin_service),
):
    return json_response(service.project_season(req))
