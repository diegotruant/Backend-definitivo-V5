from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile

from api.deps import get_workout_service
from api.errors import invalid_json_field
from api.helpers import json_response, load_activity_stream
from api.schemas import (
    CalendarTransitionRequest,
    WorkoutFeasibilityRequest,
    WorkoutPrescribeRequest,
    WorkoutValidateRequest,
)
from api.services.workout_service import WorkoutService

router = APIRouter(prefix="/workouts", tags=["workouts"])


@router.post("/validate")
def validate_workout(
    req: WorkoutValidateRequest,
    service: WorkoutService = Depends(get_workout_service),
):
    return json_response(service.validate(req))


@router.post("/prescribe")
def prescribe_workout(
    req: WorkoutPrescribeRequest,
    service: WorkoutService = Depends(get_workout_service),
):
    return json_response(service.prescribe(req))


@router.post("/feasibility")
def workout_feasibility(
    req: WorkoutFeasibilityRequest,
    service: WorkoutService = Depends(get_workout_service),
):
    return json_response(service.analyze_feasibility(req))


@router.post("/compare")
async def workout_compare(
    workout_json: str = Form(...),
    athlete_profile_json: Optional[str] = Form(None),
    tolerance_policy_json: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
    service: WorkoutService = Depends(get_workout_service),
):
    try:
        workout = json.loads(workout_json)
    except json.JSONDecodeError as exc:
        raise invalid_json_field("workout_json", exc) from exc
    try:
        athlete_profile = json.loads(athlete_profile_json) if athlete_profile_json else {}
    except json.JSONDecodeError as exc:
        raise invalid_json_field("athlete_profile_json", exc) from exc
    try:
        tolerance_policy = json.loads(tolerance_policy_json) if tolerance_policy_json else {}
    except json.JSONDecodeError as exc:
        raise invalid_json_field("tolerance_policy_json", exc) from exc

    stream = await load_activity_stream(file, power_json)
    return json_response(
        service.compare(workout, stream, athlete_profile, tolerance_policy)
    )


@router.post("/calendar/transition")
def workout_calendar_transition(
    req: CalendarTransitionRequest,
    service: WorkoutService = Depends(get_workout_service),
):
    return json_response(service.transition_calendar(req))
