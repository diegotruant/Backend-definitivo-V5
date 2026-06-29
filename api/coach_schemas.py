"""Request schemas for coach phase-2 endpoints (checkin, safety, attention)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from api.domain_schemas import AthleteProfileSnippet


class CheckinInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    sleep_quality: Optional[float] = Field(default=None, ge=1, le=10)
    stress: Optional[float] = Field(default=None, ge=1, le=10)
    motivation: Optional[float] = Field(default=None, ge=1, le=10)
    muscle_soreness: Optional[float] = Field(default=None, ge=1, le=10)
    joint_pain: Optional[float] = Field(default=None, ge=1, le=10)
    perceived_fatigue: Optional[float] = Field(default=None, ge=1, le=10)
    willingness_to_train: Optional[float] = Field(default=None, ge=1, le=10)
    notes: Optional[str] = None
    pain_flags: List[str] = Field(default_factory=list)


class CoachCheckinRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    athlete: Optional[AthleteProfileSnippet] = None
    checkin: CheckinInput
    recent_checkins: List[Dict[str, Any]] = Field(default_factory=list)


class CoachDecisionSafetyRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    twin_state: Optional[Dict[str, Any]] = None
    load_state: Optional[Dict[str, Any]] = None
    readiness_state: Optional[Dict[str, Any]] = None
    last_compliance: Optional[Dict[str, Any]] = None
    injury_flags: List[str] = Field(default_factory=list)
    checkin: Optional[CheckinInput] = None
    recent_checkins: List[Dict[str, Any]] = Field(default_factory=list)
    upcoming_key_session: bool = False


class CoachAttentionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: str = Field(..., min_length=1)
    twin_state: Optional[Dict[str, Any]] = None
    load_state: Optional[Dict[str, Any]] = None
    readiness_state: Optional[Dict[str, Any]] = None
    checkin: Optional[CheckinInput] = None
    last_compliance: Optional[Dict[str, Any]] = None
    upcoming_key_session: bool = False
    recent_checkins: List[Dict[str, Any]] = Field(default_factory=list)


class RosterAttentionEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: str = Field(..., min_length=1)
    twin_state: Optional[Dict[str, Any]] = None
    load_state: Optional[Dict[str, Any]] = None
    readiness_state: Optional[Dict[str, Any]] = None
    checkin: Optional[CheckinInput] = None
    last_compliance: Optional[Dict[str, Any]] = None
    upcoming_key_session: bool = False
    recent_checkins: List[Dict[str, Any]] = Field(default_factory=list)


class CoachRosterAttentionRequest(BaseModel):
    roster: List[RosterAttentionEntry] = Field(..., min_length=1)


class CoachAdherenceRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    athlete: Optional[AthleteProfileSnippet] = None
    planned_workout: Optional[Dict[str, Any]] = None
    performed_compliance: Optional[Dict[str, Any]] = None
    compliance_history: List[Dict[str, Any]] = Field(default_factory=list)
    readiness_state: Optional[Dict[str, Any]] = None
    checkin: Optional[CheckinInput] = None
    twin_state: Optional[Dict[str, Any]] = None


class CoachTestingPlanRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    twin_state: Optional[Dict[str, Any]] = None
    metabolic_snapshot: Optional[Dict[str, Any]] = None
    lactate_state: Optional[Dict[str, Any]] = None
    season_phase: str = "base"
    days_since_last_lactate_test: Optional[int] = Field(default=None, ge=0)


class CoachRaceExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    twin_state: Optional[Dict[str, Any]] = None
    metabolic_snapshot: Optional[Dict[str, Any]] = None
    metabolic_curves: Optional[Dict[str, Any]] = None
    target_event: str = "granfondo"
    race_simulation: Optional[Dict[str, Any]] = None
    duration_h: Optional[float] = Field(default=None, gt=0)


class CoachPeriodizationRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    twin_state: Optional[Dict[str, Any]] = None
    season_plan: List[Dict[str, Any]] = Field(default_factory=list)
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    weekly_hours: float = Field(default=8.0, gt=0)
    goal: Optional[Dict[str, Any]] = None
    season_phase: str = "base"
    strength_prescription: Optional[Dict[str, Any]] = None
    upcoming_bike_sessions: List[Dict[str, Any]] = Field(default_factory=list)
    load_state: Optional[Dict[str, Any]] = None


class CoachCommunicationDraftRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    athlete: Optional[AthleteProfileSnippet] = None
    twin_state: Optional[Dict[str, Any]] = None
    decision_safety: Optional[Dict[str, Any]] = None
    attention: Optional[Dict[str, Any]] = None
    adherence_report: Optional[Dict[str, Any]] = None
    checkin: Optional[CheckinInput] = None
    tone: str = "supportive"
    channel: str = "message"


class CoachEnvironmentAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    twin_state: Optional[Dict[str, Any]] = None
    environment_context: Optional[Dict[str, Any]] = None
    metabolic_snapshot: Optional[Dict[str, Any]] = None
    session_context: Optional[Dict[str, Any]] = None
    thermal_state: Optional[Dict[str, Any]] = None


class CoachPneiContextRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    twin_state: Optional[Dict[str, Any]] = None
    load_state: Optional[Dict[str, Any]] = None
    readiness_state: Optional[Dict[str, Any]] = None
    checkin: Optional[CheckinInput] = None
    recent_checkins: List[Dict[str, Any]] = Field(default_factory=list)
    sleep: Optional[Dict[str, Any]] = None
    nutrition_energy: Optional[Dict[str, Any]] = None
    performance: Optional[Dict[str, Any]] = None
    illness_symptoms: Optional[bool] = None
    endocrine_context: Optional[Dict[str, Any]] = None


class CoachEndocrineContextRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    twin_state: Optional[Dict[str, Any]] = None
    nutrition_energy: Optional[Dict[str, Any]] = None
    load_state: Optional[Dict[str, Any]] = None
    readiness_state: Optional[Dict[str, Any]] = None
    checkin: Optional[CheckinInput] = None
    sleep: Optional[Dict[str, Any]] = None
    performance: Optional[Dict[str, Any]] = None
    weight_trend: Optional[str] = None
    fuel_deficit_g: Optional[float] = None
    cycle_context: Optional[Dict[str, Any]] = None
    female_athlete_context: Optional[Dict[str, Any]] = None
    biomarkers: Optional[Dict[str, Any]] = None


class CoachConstraintsRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    constraints: Optional[Dict[str, Any]] = None
    season_phase: str = "build"
    planned_weekly_hours: Optional[float] = Field(default=None, gt=0)


class CoachTrainingSafetyRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    twin_state: Optional[Dict[str, Any]] = None
    injury_flags: List[str] = Field(default_factory=list)
    illness_symptoms: Optional[bool] = None
    checkin: Optional[CheckinInput] = None
    recent_checkins: List[Dict[str, Any]] = Field(default_factory=list)
    load_state: Optional[Dict[str, Any]] = None
    readiness_state: Optional[Dict[str, Any]] = None


class CoachEquipmentComfortRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    twin_state: Optional[Dict[str, Any]] = None
    equipment_state: Optional[Dict[str, Any]] = None
    comfort_notes: List[str] = Field(default_factory=list)
    position_change_log: List[Dict[str, Any]] = Field(default_factory=list)
    session_history: List[Dict[str, Any]] = Field(default_factory=list)
    checkin: Optional[CheckinInput] = None


class CoachFemaleAthleteContextRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    twin_state: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None
    checkin: Optional[CheckinInput] = None


class CoachDailyBriefRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: str = Field(..., min_length=1)
    twin_state: Optional[Dict[str, Any]] = None
    load_state: Optional[Dict[str, Any]] = None
    readiness_state: Optional[Dict[str, Any]] = None
    checkin: Optional[CheckinInput] = None
    recent_checkins: List[Dict[str, Any]] = Field(default_factory=list)
    last_compliance: Optional[Dict[str, Any]] = None
    upcoming_key_session: bool = False
    constraints: Optional[Dict[str, Any]] = None
    equipment_state: Optional[Dict[str, Any]] = None
    comfort_notes: List[str] = Field(default_factory=list)
    female_athlete_context: Optional[Dict[str, Any]] = None
    metabolic_snapshot: Optional[Dict[str, Any]] = None
    include_communication_draft: bool = True


class CoachSessionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    athlete_id: str = Field(..., min_length=1)
    planned_session: Dict[str, Any]
    twin_state: Optional[Dict[str, Any]] = None
    load_state: Optional[Dict[str, Any]] = None
    readiness_state: Optional[Dict[str, Any]] = None
    checkin: Optional[CheckinInput] = None
    recent_checkins: List[Dict[str, Any]] = Field(default_factory=list)
    environment_context: Optional[Dict[str, Any]] = None
