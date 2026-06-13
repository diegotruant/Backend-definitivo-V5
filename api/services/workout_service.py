from __future__ import annotations

from typing import Any, Dict

from api.errors import ServiceError, workout_validation_error
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


class WorkoutService:
    def validate(self, req: WorkoutValidateRequest) -> Dict[str, Any]:
        try:
            return validate_workout_payload(req.workout.to_engine_dict())
        except WorkoutValidationError as exc:
            raise workout_validation_error(exc) from exc

    def prescribe(self, req: WorkoutPrescribeRequest) -> Dict[str, Any]:
        profile = req.athlete_profile.model_dump(exclude_none=True)
        try:
            prescription = materialize_workout(req.workout.to_engine_dict(), profile)
        except WorkoutValidationError as exc:
            raise workout_validation_error(exc) from exc
        return {
            "status": "success",
            "prescription": prescription,
            "athlete_profile_used": {
                "cp_w": profile.get("cp_w") or profile.get("critical_power_w"),
                "ftp_w": profile.get("ftp_w") or profile.get("ftp"),
                "weight_kg": profile.get("weight_kg"),
            },
        }

    def analyze_feasibility(self, req: WorkoutFeasibilityRequest) -> Dict[str, Any]:
        try:
            return analyze_workout_feasibility(
                req.workout.to_engine_dict(),
                req.athlete_profile.model_dump(exclude_none=True),
                req.context.model_dump(exclude_none=True),
            )
        except WorkoutValidationError as exc:
            raise workout_validation_error(exc) from exc

    def compare(
        self,
        workout: Dict[str, Any],
        stream: Any,
        athlete_profile: Dict[str, Any],
        tolerance_policy: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            return compare_workout_to_activity(workout, stream, athlete_profile, tolerance_policy)
        except WorkoutValidationError as exc:
            raise workout_validation_error(exc) from exc

    def transition_calendar(self, req: CalendarTransitionRequest) -> Dict[str, Any]:
        return validate_status_transition(req.current_status, req.desired_status)
