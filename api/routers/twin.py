from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.helpers import json_response
from api.schemas import (
    SeasonProjectionRequest,
    TwinStateBuildRequest,
    TwinStateUpdateRideRequest,
    TwinStateUpdateWorkoutRequest,
)
from engines.core.security import PayloadTooDeep, assert_json_depth, safe_error_detail
from engines.projection.season_projection_engine import project_season_from_plan
from engines.twin_state.models import build_twin_state
from engines.twin_state.state_update_engine import (
    update_twin_state_from_ride,
    update_twin_state_from_workout_result,
)
from engines.workouts.models import WorkoutValidationError

router = APIRouter(tags=["twin"])


@router.post("/twin/state/build")
def twin_state_build(req: TwinStateBuildRequest):
    try:
        return json_response(build_twin_state(req.payload))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/twin/state/update-from-ride")
def twin_state_update_from_ride(req: TwinStateUpdateRideRequest):
    try:
        return json_response(update_twin_state_from_ride(
            req.twin_state,
            ride_summary=req.ride_summary,
            ingest_result=req.ingest_result,
            power_source_report=req.power_source_report,
            ride_id=req.ride_id,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/twin/state/update-from-workout-result")
def twin_state_update_from_workout(req: TwinStateUpdateWorkoutRequest):
    try:
        return json_response(update_twin_state_from_workout_result(
            req.twin_state,
            compliance_result=req.compliance_result,
            assignment_id=req.assignment_id,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/twin/state/project")
def twin_state_project(req: SeasonProjectionRequest):
    try:
        assert_json_depth(req.twin_state)
        assert_json_depth(req.calendar_plan)
        return json_response(project_season_from_plan(
            req.twin_state,
            req.calendar_plan,
            start_date=req.start_date,
            target_date=req.target_date,
            max_days=req.max_days,
        ))
    except PayloadTooDeep as e:
        raise HTTPException(status_code=400, detail=safe_error_detail("PAYLOAD_TOO_DEEP")) from e
    except (ValueError, WorkoutValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/projection/season")
def projection_season(req: SeasonProjectionRequest):
    return twin_state_project(req)
