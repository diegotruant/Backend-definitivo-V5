"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from api.domain_schemas import (
    AthleteProfileSnippet,
    CalendarPlanEvent,
    ComplianceResult,
    InPersonTestEnvelope,
    PowerSourceActivity,
    TwinStateBuildPayload,
    TwinStateDocument,
    WorkoutDefinitionInput,
    WorkoutFeasibilityContext,
)
from engines.core.security import MAX_CALENDAR_EVENTS, MAX_PROJECTION_DAYS


class AthleteParams(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "weight_kg": 72,
            "gender": "MALE",
            "training_years": 10,
            "discipline": "ENDURANCE",
        }
    })

    weight_kg: float = Field(..., gt=30, lt=200, description="Athlete body mass in kilograms.")
    gender: str = Field(default="MALE", description="MALE or FEMALE for physiological priors.")
    training_years: float = Field(default=10, description="Years of structured endurance training.")
    discipline: str = Field(default="ENDURANCE", description="ENDURANCE, ROAD, TT, etc.")
    active_muscle_mass_kg: Optional[float] = Field(
        default=None,
        description="Optional active muscle mass override for Mader modelling.",
    )


class ConfirmRequest(BaseModel):
    proposal: Dict[str, Any] = Field(description="Coach-reviewed output of POST /test/propose.")
    athlete: AthleteParams
    measured_on: str = Field(description="ISO date YYYY-MM-DD of the test session.")


class UpdateProfileRequest(BaseModel):
    anchor: Dict[str, Any] = Field(description="Persisted measured anchor from POST /test/confirm.")
    ride_mmp: Dict[str, float] = Field(description="Ride MMP map {duration_seconds: watts}.")
    athlete: AthleteParams
    as_of: str = Field(description="ISO date of the ride used for the update.")
    load_factor: float = Field(default=1.0, description="Optional load scaling for Bayesian update.")


class SnapshotRequest(BaseModel):
    mmp: Dict[str, float] = Field(description="Power-duration anchors {seconds: watts}.")
    athlete: AthleteParams


class WorkoutValidateRequest(BaseModel):
    workout: WorkoutDefinitionInput = Field(description="Workout template or coach draft with steps.")


class WorkoutPrescribeRequest(BaseModel):
    workout: WorkoutDefinitionInput
    athlete_profile: AthleteProfileSnippet = Field(
        default_factory=AthleteProfileSnippet,
        description="Athlete CP/FTP/weight used to resolve percentage targets.",
    )


class WorkoutFeasibilityRequest(BaseModel):
    workout: WorkoutDefinitionInput
    athlete_profile: AthleteProfileSnippet = Field(default_factory=AthleteProfileSnippet)
    context: WorkoutFeasibilityContext = Field(
        default_factory=WorkoutFeasibilityContext,
        description="Optional readiness/fatigue context for W′ simulation.",
    )


class CalendarTransitionRequest(BaseModel):
    current_status: str = Field(description="Current assignment status in calendar FSM.")
    desired_status: str = Field(description="Requested next status.")


class TeamCalibrationUpdateRequest(BaseModel):
    team_id: str
    calibration_model: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Previously persisted model; omit to start fresh.",
    )
    events: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Validation events with pre-test predicted_value.",
    )


class TeamCalibrationApplyRequest(BaseModel):
    calibration_model: Dict[str, Any]
    parameter: Optional[str] = Field(default=None, description="mlss, vo2max, vlamax, fatmax, map.")
    predicted_value: Optional[float] = None
    snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Full metabolic snapshot to calibrate in one call.",
    )
    athlete_id: Optional[str] = None
    phenotype: Optional[str] = None
    data_depth_score: float = Field(default=1.0, ge=0, le=1)


class InPersonTestRequest(InPersonTestEnvelope):
    """Tablet envelope — see TEST_JSON_CONTRACT.md."""


class TwinStateBuildRequest(BaseModel):
    payload: TwinStateBuildPayload = Field(
        default_factory=TwinStateBuildPayload,
        description="Initial athlete anchor, snapshot, curve and profile fragments.",
    )


class TwinStateUpdateRideRequest(BaseModel):
    twin_state: TwinStateDocument = Field(description="Current persisted TwinState (twin_state.v1).")
    ride_summary: Optional[Dict[str, Any]] = Field(default=None, description="Output of POST /ride/summary.")
    ingest_result: Optional[Dict[str, Any]] = Field(default=None, description="Output of POST /ride/ingest.")
    power_source_report: Optional[Dict[str, Any]] = None
    ride_id: Optional[str] = None


class TwinStateUpdateWorkoutRequest(BaseModel):
    twin_state: TwinStateDocument
    compliance_result: ComplianceResult = Field(description="Output of POST /workouts/compare.")
    assignment_id: Optional[str] = None


class SeasonProjectionRequest(BaseModel):
    twin_state: TwinStateDocument
    calendar_plan: List[CalendarPlanEvent] = Field(
        default_factory=list,
        max_length=MAX_CALENDAR_EVENTS,
        description="Future planned workouts/assignments.",
    )
    start_date: Optional[str] = Field(default=None, description="ISO date projection start.")
    target_date: Optional[str] = Field(default=None, description="ISO date projection end.")
    max_days: int = Field(default=365, ge=1, le=MAX_PROJECTION_DAYS)


class PowerSourceNormalizationRequest(BaseModel):
    activities: List[PowerSourceActivity] = Field(
        default_factory=list,
        description="Activities with source_id and MMP signatures.",
    )
    baseline_source_id: Optional[str] = None
    warning_threshold_pct: float = Field(default=3.0, ge=0, le=50)
    severe_threshold_pct: float = Field(default=6.0, ge=0, le=100)


class ManualLoadRequest(BaseModel):
    duration_min: float = Field(..., ge=0, le=600, description="Session duration in minutes.")
    rpe: float = Field(..., ge=0, le=10, description="Session RPE 0–10.")
    modality: str = Field(default="other", description="gym, run, swim, other, …")
    muscle_damage_factor: Optional[float] = Field(default=None, ge=0, le=3)
    notes: Optional[str] = None


class ActivityIntelligenceRequest(BaseModel):
    weight_kg: float = Field(default=70.0, gt=30, lt=200)
    ftp: Optional[float] = Field(default=None, gt=0)
    cp: Optional[float] = Field(default=None, gt=0)
    lthr: Optional[float] = Field(default=None, gt=0)


class HistorySummaryRequest(BaseModel):
    activities: List[Dict[str, Any]] = Field(default_factory=list)
    as_of: Optional[str] = None
    weight_kg: Optional[float] = Field(default=None, gt=30, lt=200)


class ReadinessTodayRequest(BaseModel):
    load_state: Optional[Dict[str, Any]] = None
    hrv_status: Optional[Dict[str, Any]] = None
    sleep_status: Optional[Dict[str, Any]] = None
    subjective: Optional[Dict[str, Any]] = None
    recent_warnings: List[str] = Field(default_factory=list)


class LoadStateUpdateRequest(BaseModel):
    previous_state: Optional[Dict[str, Any]] = None
    session_load: float = Field(default=0.0, ge=0)


class LoadRiskRequest(BaseModel):
    load_state: Dict[str, Any] = Field(default_factory=dict)
    planned_load: float = Field(default=0.0, ge=0)


class AbilityProfileRequest(BaseModel):
    athlete_profile: Dict[str, Any] = Field(default_factory=dict)
    weight_kg: Optional[float] = Field(default=None, gt=30, lt=200)
    durability: Optional[Dict[str, Any]] = None
    compliance_history: List[Dict[str, Any]] = Field(default_factory=list)


class BreakthroughRequest(BaseModel):
    baseline_curve: Dict[str, Any] = Field(default_factory=dict)
    activity_curve: Dict[str, Any] = Field(default_factory=dict)
    min_gain_pct: float = Field(default=1.5, ge=0)


class WorkoutRecommendationRequest(BaseModel):
    athlete_profile: Dict[str, Any] = Field(default_factory=dict)
    readiness: Optional[Dict[str, Any]] = None
    goal: Optional[Dict[str, Any]] = None
    recent_workouts: List[Dict[str, Any]] = Field(default_factory=list)


class ProgressionLevelsRequest(BaseModel):
    athlete_profile: Dict[str, Any] = Field(default_factory=dict)
    workout_history: List[Dict[str, Any]] = Field(default_factory=list)


class AdaptPlanRequest(BaseModel):
    plan: List[Dict[str, Any]] = Field(default_factory=list)
    readiness: Optional[Dict[str, Any]] = None
    last_compliance: Optional[Dict[str, Any]] = None


class WorkoutExportRequest(BaseModel):
    workout: Dict[str, Any] = Field(default_factory=dict)
    format: str = Field(default="erg", description="erg, mrc or zwo")


class CreateSeasonPlanRequest(BaseModel):
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    weekly_hours: float = Field(default=8.0, ge=1, le=40)
    goal: Optional[Dict[str, Any]] = None


class AdaptWeekRequest(BaseModel):
    week_plan: List[Dict[str, Any]] = Field(default_factory=list)
    readiness: Optional[Dict[str, Any]] = None
    compliance: Optional[Dict[str, Any]] = None


class CheckLoadRiskRequest(BaseModel):
    plan: List[Dict[str, Any]] = Field(default_factory=list)
    chronic_load: float = Field(default=50.0, ge=0)
