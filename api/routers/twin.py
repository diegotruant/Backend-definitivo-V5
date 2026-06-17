from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_twin_service
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.schemas import (
    SeasonProjectionRequest,
    TwinStateBuildRequest,
    TwinStateUpdateRideRequest,
    TwinStateUpdateWorkoutRequest,
)
from api.services.twin_service import TwinService

router = APIRouter(tags=["twin"], )


@router.post(
    "/twin/state/build",
    summary="Build TwinState v1",
    description="Create canonical twin_state.v1 blob for DB persistence.",
    operation_id="twinStateBuild",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def twin_state_build(
    req: TwinStateBuildRequest,
    service: TwinService = Depends(get_twin_service),
):
    return json_response(service.build(req))


@router.post(
    "/twin/state/update-from-ride",
    summary="Update TwinState after ride",
    operation_id="twinStateUpdateFromRide",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def twin_state_update_from_ride(
    req: TwinStateUpdateRideRequest,
    service: TwinService = Depends(get_twin_service),
):
    return json_response(service.update_from_ride(req))


@router.post(
    "/twin/state/update-from-workout-result",
    summary="Append workout compliance to TwinState",
    operation_id="twinStateUpdateFromWorkout",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def twin_state_update_from_workout(
    req: TwinStateUpdateWorkoutRequest,
    service: TwinService = Depends(get_twin_service),
):
    return json_response(service.update_from_workout(req))


@router.post(
    "/twin/state/project",
    summary="Season what-if projection",
    description="Project CP, load and readiness from TwinState + future calendar.",
    operation_id="twinStateProject",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def twin_state_project(
    req: SeasonProjectionRequest,
    service: TwinService = Depends(get_twin_service),
):
    return json_response(service.project_season(req))


@router.post(
    "/projection/season",
    summary="Season projection (alias)",
    description="Alias of POST /twin/state/project.",
    operation_id="projectionSeason",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def projection_season(
    req: SeasonProjectionRequest,
    service: TwinService = Depends(get_twin_service),
):
    return json_response(service.project_season(req))
