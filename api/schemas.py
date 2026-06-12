"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from engines.core.security import MAX_CALENDAR_EVENTS, MAX_PROJECTION_DAYS


class AthleteParams(BaseModel):
    weight_kg: float = Field(..., gt=30, lt=200)
    gender: str = "MALE"
    training_years: float = 10
    discipline: str = "ENDURANCE"
    active_muscle_mass_kg: Optional[float] = None


class ConfirmRequest(BaseModel):
    proposal: Dict[str, Any]
    athlete: AthleteParams
    measured_on: str


class UpdateProfileRequest(BaseModel):
    anchor: Dict[str, Any]
    ride_mmp: Dict[str, float]
    athlete: AthleteParams
    as_of: str
    load_factor: float = 1.0


class SnapshotRequest(BaseModel):
    mmp: Dict[str, float]
    athlete: AthleteParams


class RideUpdateCurveRequest(BaseModel):
    stored_curve: Optional[Dict[str, Any]] = None
    ride_date: str
    weight_kg: float = 70.0


class WorkoutValidateRequest(BaseModel):
    workout: Dict[str, Any]


class WorkoutPrescribeRequest(BaseModel):
    workout: Dict[str, Any]
    athlete_profile: Dict[str, Any] = Field(default_factory=dict)


class WorkoutFeasibilityRequest(BaseModel):
    workout: Dict[str, Any]
    athlete_profile: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)


class CalendarTransitionRequest(BaseModel):
    current_status: str
    desired_status: str


class TeamCalibrationUpdateRequest(BaseModel):
    team_id: str
    calibration_model: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = Field(default_factory=list)


class TeamCalibrationApplyRequest(BaseModel):
    calibration_model: Dict[str, Any]
    parameter: Optional[str] = None
    predicted_value: Optional[float] = None
    snapshot: Optional[Dict[str, Any]] = None
    athlete_id: Optional[str] = None
    phenotype: Optional[str] = None
    data_depth_score: float = 1.0


class InPersonTestRequest(BaseModel):
    test_type: str
    timestamp: Optional[str] = None
    athlete: Dict[str, Any] = Field(default_factory=dict)
    device: Optional[Dict[str, Any]] = None
    test_data: Dict[str, Any] = Field(default_factory=dict)


class TwinStateBuildRequest(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict)


class TwinStateUpdateRideRequest(BaseModel):
    twin_state: Dict[str, Any]
    ride_summary: Optional[Dict[str, Any]] = None
    ingest_result: Optional[Dict[str, Any]] = None
    power_source_report: Optional[Dict[str, Any]] = None
    ride_id: Optional[str] = None


class TwinStateUpdateWorkoutRequest(BaseModel):
    twin_state: Dict[str, Any]
    compliance_result: Dict[str, Any]
    assignment_id: Optional[str] = None


class SeasonProjectionRequest(BaseModel):
    twin_state: Dict[str, Any]
    calendar_plan: List[Dict[str, Any]] = Field(default_factory=list, max_length=MAX_CALENDAR_EVENTS)
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    max_days: int = Field(default=365, ge=1, le=MAX_PROJECTION_DAYS)


class PowerSourceNormalizationRequest(BaseModel):
    activities: List[Dict[str, Any]] = Field(default_factory=list)
    baseline_source_id: Optional[str] = None
    warning_threshold_pct: float = 3.0
    severe_threshold_pct: float = 6.0


class ManualLoadRequest(BaseModel):
    duration_min: float = Field(..., ge=0, le=600)
    rpe: float = Field(..., ge=0, le=10)
    modality: str = "other"
    muscle_damage_factor: Optional[float] = None
    notes: Optional[str] = None
