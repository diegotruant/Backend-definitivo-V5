from __future__ import annotations

from typing import Any, Dict

from api.errors import ServiceError, workout_validation_error
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


class TwinService:
    def build(self, req: TwinStateBuildRequest) -> Dict[str, Any]:
        try:
            return build_twin_state(req.payload.to_engine_dict())
        except ValueError as exc:
            raise ServiceError(str(exc), status_code=400, code="TWIN_BUILD") from exc

    def update_from_ride(self, req: TwinStateUpdateRideRequest) -> Dict[str, Any]:
        try:
            return update_twin_state_from_ride(
                req.twin_state.to_engine_dict(),
                ride_summary=req.ride_summary,
                ingest_result=req.ingest_result,
                power_source_report=req.power_source_report,
                ride_id=req.ride_id,
            )
        except ValueError as exc:
            raise ServiceError(str(exc), status_code=400, code="TWIN_UPDATE_RIDE") from exc

    def update_from_workout(self, req: TwinStateUpdateWorkoutRequest) -> Dict[str, Any]:
        try:
            return update_twin_state_from_workout_result(
                req.twin_state.to_engine_dict(),
                compliance_result=req.compliance_result.to_engine_dict(),
                assignment_id=req.assignment_id,
            )
        except ValueError as exc:
            raise ServiceError(str(exc), status_code=400, code="TWIN_UPDATE_WORKOUT") from exc

    def project_season(self, req: SeasonProjectionRequest) -> Dict[str, Any]:
        twin_dict = req.twin_state.to_engine_dict()
        calendar = [event.to_engine_dict() for event in req.calendar_plan]
        try:
            assert_json_depth(twin_dict)
            assert_json_depth(calendar)
            return project_season_from_plan(
                twin_dict,
                calendar,
                start_date=req.start_date,
                target_date=req.target_date,
                max_days=req.max_days,
            )
        except PayloadTooDeep as exc:
            raise ServiceError(
                message="Payload too deep.",
                status_code=400,
                code="PAYLOAD_TOO_DEEP",
                details=safe_error_detail("PAYLOAD_TOO_DEEP"),
            ) from exc
        except (ValueError, WorkoutValidationError) as exc:
            if isinstance(exc, WorkoutValidationError):
                raise workout_validation_error(exc) from exc
            raise ServiceError(str(exc), status_code=400, code="PROJECTION") from exc
