from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.helpers import json_response, load_activity_stream
from api.schemas import (
    CalendarTransitionRequest,
    WorkoutFeasibilityRequest,
    WorkoutPrescribeRequest,
    WorkoutValidateRequest,
)
from engines.workouts.calendar_engine import validate_status_transition
from engines.workouts.compliance_engine import compare_workout_to_activity
from engines.workouts.feasibility_engine import analyze_workout_feasibility
from engines.workouts.models import WorkoutValidationError, materialize_workout, validate_workout_payload

router = APIRouter(prefix="/workouts", tags=["workouts"])


@router.post("/validate")
def validate_workout(req: WorkoutValidateRequest):
    try:
        return json_response(validate_workout_payload(req.workout))
    except WorkoutValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/prescribe")
def prescribe_workout(req: WorkoutPrescribeRequest):
    try:
        prescription = materialize_workout(req.workout, req.athlete_profile)
    except WorkoutValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return json_response({
        "status": "success",
        "prescription": prescription,
        "athlete_profile_used": {
            "cp_w": req.athlete_profile.get("cp_w") or req.athlete_profile.get("critical_power_w"),
            "ftp_w": req.athlete_profile.get("ftp_w") or req.athlete_profile.get("ftp"),
            "weight_kg": req.athlete_profile.get("weight_kg"),
        },
    })


@router.post("/feasibility")
def workout_feasibility(req: WorkoutFeasibilityRequest):
    try:
        out = analyze_workout_feasibility(req.workout, req.athlete_profile, req.context)
    except WorkoutValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return json_response(out)


@router.post("/compare")
async def workout_compare(
    workout_json: str = Form(...),
    athlete_profile_json: Optional[str] = Form(None),
    tolerance_policy_json: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    power_json: Optional[str] = Form(None),
):
    try:
        workout = json.loads(workout_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid workout_json: {e}")
    try:
        athlete_profile = json.loads(athlete_profile_json) if athlete_profile_json else {}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid athlete_profile_json: {e}")
    try:
        tolerance_policy = json.loads(tolerance_policy_json) if tolerance_policy_json else {}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid tolerance_policy_json: {e}")

    stream = await load_activity_stream(file, power_json)
    try:
        out = compare_workout_to_activity(workout, stream, athlete_profile, tolerance_policy)
    except WorkoutValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return json_response(out)


@router.post("/calendar/transition")
def workout_calendar_transition(req: CalendarTransitionRequest):
    return json_response(validate_status_transition(req.current_status, req.desired_status))
