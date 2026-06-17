from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile

from api.deps import get_workout_service
from api.errors import invalid_json_field
from api.helpers import json_response, load_activity_stream
from api.responses import EnginePayload, WorkoutPrescribeResponse
from api.route_docs import ERRORS, JSON_OBJECT, WORKOUT_PRESCRIBE_OK
from api.schemas import (
    CalendarTransitionRequest,
    WorkoutFeasibilityRequest,
    WorkoutPrescribeRequest,
    WorkoutValidateRequest,
    WorkoutRecommendationRequest,
    ProgressionLevelsRequest,
    AdaptPlanRequest,
    WorkoutExportRequest,
)
from api.services.workout_service import WorkoutService

router = APIRouter(prefix="/workouts", tags=["workouts"], )


@router.post(
    "/validate",
    summary="Validate workout template",
    operation_id="workoutsValidate",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def validate_workout(
    req: WorkoutValidateRequest,
    service: WorkoutService = Depends(get_workout_service),
):
    return json_response(service.validate(req))


@router.post(
    "/prescribe",
    summary="Prescribe workout to athlete watts",
    description="Resolve percentage targets to concrete watts/HR for the athlete profile.",
    operation_id="workoutsPrescribe",
    response_model=WorkoutPrescribeResponse,
    responses={200: WORKOUT_PRESCRIBE_OK, 400: ERRORS[400]},
)
def prescribe_workout(
    req: WorkoutPrescribeRequest,
    service: WorkoutService = Depends(get_workout_service),
):
    return json_response(service.prescribe(req))


@router.post(
    "/feasibility",
    summary="Preview workout feasibility",
    description="W′ balance simulation before calendar assignment.",
    operation_id="workoutsFeasibility",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def workout_feasibility(
    req: WorkoutFeasibilityRequest,
    service: WorkoutService = Depends(get_workout_service),
):
    return json_response(service.analyze_feasibility(req))


@router.post(
    "/compare",
    summary="Compare assigned vs performed workout",
    description="Compliance score between prescribed workout and performed FIT/power stream.",
    operation_id="workoutsCompare",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400], 413: ERRORS[413]},
)
async def workout_compare(
    workout_json: str = Form(..., description="Assigned workout JSON."),
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


@router.post(
    "/calendar/transition",
    summary="Validate calendar assignment transition",
    operation_id="workoutsCalendarTransition",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def workout_calendar_transition(
    req: CalendarTransitionRequest,
    service: WorkoutService = Depends(get_workout_service),
):
    return json_response(service.transition_calendar(req))


@router.post(
    "/recommend",
    summary="Recommend next workout",
    operation_id="workoutsRecommend",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def workout_recommend(
    req: WorkoutRecommendationRequest,
    service: WorkoutService = Depends(get_workout_service),
):
    return json_response(service.recommend(req))


@router.post(
    "/progression-levels",
    summary="Compute progression levels",
    operation_id="workoutsProgressionLevels",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def workout_progression_levels(
    req: ProgressionLevelsRequest,
    service: WorkoutService = Depends(get_workout_service),
):
    return json_response(service.progression_levels(req))


@router.post(
    "/adapt-plan",
    summary="Adapt a planned workout list",
    operation_id="workoutsAdaptPlan",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def workout_adapt_plan(
    req: AdaptPlanRequest,
    service: WorkoutService = Depends(get_workout_service),
):
    return json_response(service.adapt_plan(req))


@router.post(
    "/export",
    summary="Export workout text format",
    operation_id="workoutsExport",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def workout_export(
    req: WorkoutExportRequest,
    service: WorkoutService = Depends(get_workout_service),
):
    return json_response(service.export_workout(req))
