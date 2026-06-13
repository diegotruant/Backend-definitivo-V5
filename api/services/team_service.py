from __future__ import annotations

from typing import Any, Dict, Optional

from api.errors import ServiceError
from api.schemas import TeamCalibrationApplyRequest, TeamCalibrationUpdateRequest
from engines.metabolic.team_learning_engine import TeamCalibrationModel, ValidationEvent


class TeamService:
    def update_calibration(self, req: TeamCalibrationUpdateRequest) -> Dict[str, Any]:
        try:
            if req.calibration_model:
                model = TeamCalibrationModel.from_dict(req.calibration_model)
                if model.team_id != req.team_id:
                    raise ServiceError(
                        "team_id does not match calibration_model.team_id",
                        status_code=400,
                        code="TEAM_ID_MISMATCH",
                    )
            else:
                model = TeamCalibrationModel(team_id=req.team_id)
            for raw in req.events:
                model.add_event(
                    ValidationEvent.from_dict({**raw, "team_id": raw.get("team_id", req.team_id)})
                )
        except ValueError as exc:
            raise ServiceError(str(exc), status_code=400, code="CALIBRATION_UPDATE") from exc
        return model.to_dict()

    def apply_calibration(self, req: TeamCalibrationApplyRequest) -> Dict[str, Any]:
        try:
            model = TeamCalibrationModel.from_dict(req.calibration_model)
            if req.snapshot is not None:
                return model.calibrate_snapshot(
                    req.snapshot,
                    athlete_id=req.athlete_id,
                    phenotype=req.phenotype,
                    data_depth_score=req.data_depth_score,
                )
            if req.parameter is None or req.predicted_value is None:
                raise ServiceError(
                    "Provide either snapshot or both parameter and predicted_value.",
                    status_code=400,
                    code="CALIBRATION_APPLY_INPUT",
                )
            return model.correction_for(
                req.parameter,
                req.predicted_value,
                athlete_id=req.athlete_id,
                phenotype=req.phenotype,
                data_depth_score=req.data_depth_score,
            )
        except ValueError as exc:
            raise ServiceError(str(exc), status_code=400, code="CALIBRATION_APPLY") from exc
