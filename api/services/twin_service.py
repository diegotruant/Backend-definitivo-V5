from __future__ import annotations

from typing import Any, Dict, Optional

from api.errors import ServiceError, workout_validation_error
from api.schemas import (
    SeasonProjectionRequest,
    TwinStateBuildRequest,
    TwinStateUpdateRideRequest,
    TwinStateUpdateWorkoutRequest,
)
from api.services.mmp_publication_gate import evaluate_mmp_gate
from engines.core.security import PayloadTooDeep, assert_json_depth, safe_error_detail
from engines.projection.season_projection_engine import project_season_from_plan
from engines.twin_state.models import build_twin_state, validate_twin_state
from engines.twin_state.state_update_engine import (
    update_twin_state_from_ride,
    update_twin_state_from_workout_result,
)
from engines.workouts.models import WorkoutValidationError


class TwinService:
    def validate(self, twin_state: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return validate_twin_state(twin_state)
        except ValueError as exc:
            raise ServiceError(str(exc), status_code=400, code="TWIN_VALIDATE") from exc

    def build(self, req: TwinStateBuildRequest) -> Dict[str, Any]:
        try:
            return build_twin_state(req.payload.to_engine_dict())
        except ValueError as exc:
            raise ServiceError(str(exc), status_code=400, code="TWIN_BUILD") from exc

    @staticmethod
    def _select_metabolic_snapshot_for_ride(
        *,
        state: Dict[str, Any],
        ingest_result: Optional[Dict[str, Any]],
        metabolic_snapshot: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Allow explicit snapshots, but gate automatic ride-driven refreshes.

        ``profile_should_refresh`` only means that a profile-critical MMP anchor
        changed or expired. It is not proof that the longitudinal curve is
        publication-grade. When a caller supplies a snapshot as part of that
        automatic ride flow, the internal MMP publication gate must also mark
        the candidate curve as profile-eligible before TwinState is refreshed.

        A snapshot supplied without an automatic refresh request is considered
        an explicit/test/laboratory update and keeps the pre-existing behavior.
        The assessment remains internal and is not serialized into TwinState or
        any API response.
        """

        if metabolic_snapshot is None:
            return None

        ingest = ingest_result or {}
        if not bool(ingest.get("profile_should_refresh")):
            return metabolic_snapshot

        candidate_curve = ingest.get("curve")
        if not isinstance(candidate_curve, dict) or not candidate_curve:
            stored_curve = state.get("rolling_power_curve")
            candidate_curve = stored_curve if isinstance(stored_curve, dict) else {}

        assessment = evaluate_mmp_gate(candidate_curve)
        return metabolic_snapshot if assessment.profile_eligible else None

    def update_from_ride(self, req: TwinStateUpdateRideRequest) -> Dict[str, Any]:
        try:
            state = req.twin_state.to_engine_dict()
            metabolic_snapshot = self._select_metabolic_snapshot_for_ride(
                state=state,
                ingest_result=req.ingest_result,
                metabolic_snapshot=req.metabolic_snapshot,
            )
            return update_twin_state_from_ride(
                state,
                ride_summary=req.ride_summary,
                ingest_result=req.ingest_result,
                power_source_report=req.power_source_report,
                ride_id=req.ride_id,
                metabolic_snapshot=metabolic_snapshot,
                lactate_steps=req.lactate_steps,
                sync_metabolic_curves=req.sync_metabolic_curves,
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
