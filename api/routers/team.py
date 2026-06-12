from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.helpers import json_response
from api.schemas import TeamCalibrationApplyRequest, TeamCalibrationUpdateRequest
from engines.metabolic.team_learning_engine import TeamCalibrationModel, ValidationEvent

router = APIRouter(prefix="/team", tags=["team"])


@router.post("/calibration/update")
def update_team_calibration(req: TeamCalibrationUpdateRequest):
    try:
        if req.calibration_model:
            model = TeamCalibrationModel.from_dict(req.calibration_model)
            if model.team_id != req.team_id:
                raise HTTPException(status_code=400, detail="team_id does not match calibration_model.team_id")
        else:
            model = TeamCalibrationModel(team_id=req.team_id)
        for raw in req.events:
            model.add_event(ValidationEvent.from_dict({**raw, "team_id": raw.get("team_id", req.team_id)}))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return json_response(model.to_dict())


@router.post("/calibration/apply")
def apply_team_calibration(req: TeamCalibrationApplyRequest):
    try:
        model = TeamCalibrationModel.from_dict(req.calibration_model)
        if req.snapshot is not None:
            return json_response(model.calibrate_snapshot(
                req.snapshot,
                athlete_id=req.athlete_id,
                phenotype=req.phenotype,
                data_depth_score=req.data_depth_score,
            ))
        if req.parameter is None or req.predicted_value is None:
            raise HTTPException(
                status_code=400,
                detail="Provide either snapshot or both parameter and predicted_value.",
            )
        return json_response(model.correction_for(
            req.parameter,
            req.predicted_value,
            athlete_id=req.athlete_id,
            phenotype=req.phenotype,
            data_depth_score=req.data_depth_score,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
