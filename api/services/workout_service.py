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
from engines.workouts.recommendation_engine import recommend_workout
from engines.workouts.progression_levels import compute_progression_levels
from engines.workouts.adaptive_planner import adapt_plan
from engines.workouts.exporters import export_erg, export_mrc, export_zwo


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

    def recommend(self, req) -> Dict[str, Any]:
        return recommend_workout(
            req.athlete_profile,
            readiness=req.readiness,
            goal=req.goal,
            recent_workouts=req.recent_workouts,
        )

    def progression_levels(self, req) -> Dict[str, Any]:
        return compute_progression_levels(req.athlete_profile, req.workout_history)

    def adapt_plan(self, req) -> Dict[str, Any]:
        return adapt_plan(req.plan, readiness=req.readiness, last_compliance=req.last_compliance)

    def export_workout(self, req) -> Dict[str, Any]:
        fmt = str(req.format or "erg").lower()
        if fmt == "zwo":
            return export_zwo(req.workout)
        if fmt == "mrc":
            return export_mrc(req.workout)
        if fmt == "erg":
            return export_erg(req.workout)
        raise ServiceError("Unsupported workout export format.", status_code=400, code="UNSUPPORTED_EXPORT_FORMAT")

    def transition_calendar(self, req: CalendarTransitionRequest) -> Dict[str, Any]:
        return validate_status_transition(req.current_status, req.desired_status)
