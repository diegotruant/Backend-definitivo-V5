"""Typed domain payloads shared by API request models."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engines.twin_state.models import TWIN_STATE_SCHEMA_VERSION


class AthleteProfileSnippet(BaseModel):
    """Subset of athlete fields commonly embedded in TwinState or workout context."""

    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    weight_kg: Optional[float] = Field(default=None, gt=30, lt=200)
    gender: Optional[str] = None
    sex: Optional[str] = None
    training_years: Optional[float] = Field(default=None, ge=0, le=60)
    discipline: Optional[str] = None
    cp_w: Optional[float] = Field(default=None, gt=0)
    critical_power_w: Optional[float] = Field(default=None, gt=0)
    ftp_w: Optional[float] = Field(default=None, gt=0)
    ftp: Optional[float] = Field(default=None, gt=0)


class WorkoutStepInput(BaseModel):
    """Single workout step — mirrors engines.workouts.models.WorkoutStep JSON."""

    model_config = ConfigDict(extra="allow")

    step_id: Optional[str] = None
    id: Optional[str] = None
    type: str = Field(default="work", description="work | warmup | cooldown | rest | …")
    step_type: Optional[str] = None
    duration_s: Optional[int] = Field(default=None, gt=0)
    duration: Optional[float] = Field(default=None, gt=0)
    seconds: Optional[float] = Field(default=None, gt=0)
    target_type: str = Field(default="free")
    target_w: Optional[float] = Field(default=None, ge=0)
    target_min_w: Optional[float] = Field(default=None, ge=0)
    target_max_w: Optional[float] = Field(default=None, ge=0)
    target_pct_cp: Optional[float] = Field(default=None, ge=0, le=300)
    target_min_pct_cp: Optional[float] = Field(default=None, ge=0, le=300)
    target_max_pct_cp: Optional[float] = Field(default=None, ge=0, le=300)
    target_pct_ftp: Optional[float] = Field(default=None, ge=0, le=300)
    target_min_pct_ftp: Optional[float] = Field(default=None, ge=0, le=300)
    target_max_pct_ftp: Optional[float] = Field(default=None, ge=0, le=300)
    target_hr: Optional[float] = Field(default=None, ge=40, le=230)
    target_min_hr: Optional[float] = Field(default=None, ge=40, le=230)
    target_max_hr: Optional[float] = Field(default=None, ge=40, le=230)
    is_key_step: bool = False
    key: Optional[bool] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _resolve_duration(self) -> "WorkoutStepInput":
        if self.duration_s is None:
            raw = self.duration if self.duration is not None else self.seconds
            if raw is not None:
                object.__setattr__(self, "duration_s", int(round(float(raw))))
        return self


class WorkoutDefinitionInput(BaseModel):
    """Coach workout template or draft."""

    model_config = ConfigDict(extra="allow")

    workout_id: Optional[str] = None
    id: Optional[str] = None
    title: str = Field(default="Untitled workout", min_length=1)
    name: Optional[str] = None
    description: Optional[str] = None
    discipline: str = Field(default="cycling")
    goal: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    steps: List[WorkoutStepInput] = Field(min_length=1)
    structure: Optional[List[WorkoutStepInput]] = None

    @model_validator(mode="after")
    def _normalize_steps(self) -> "WorkoutDefinitionInput":
        if not self.steps and self.structure:
            object.__setattr__(self, "steps", self.structure)
        if self.name and self.title == "Untitled workout":
            object.__setattr__(self, "title", self.name)
        return self

    def to_engine_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True, exclude={"structure"})


class WorkoutFeasibilityContext(BaseModel):
    """Optional readiness/fatigue context for W′ simulation."""

    model_config = ConfigDict(extra="allow")

    w_prime_j: Optional[float] = Field(default=None, ge=0)
    readiness_score: Optional[float] = Field(default=None, ge=0, le=1)
    fatigue_score: Optional[float] = Field(default=None, ge=0, le=1)
    notes: Optional[str] = None


class InPersonAthlete(BaseModel):
    """Tablet test athlete envelope — see TEST_JSON_CONTRACT.md."""

    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    type: Optional[Literal["registered", "guest"]] = None
    name: Optional[str] = None
    surname: Optional[str] = None
    dob: Optional[str] = None
    weight_kg: Optional[float] = Field(default=None, gt=30, lt=200)
    height_cm: Optional[float] = Field(default=None, gt=100, lt=250)
    sex: Optional[str] = None
    gender: Optional[str] = None
    hr_max: Optional[float] = Field(default=None, ge=100, le=230)
    training_years: Optional[float] = Field(default=10, ge=0, le=60)
    discipline: Optional[str] = "ENDURANCE"


class InPersonDevice(BaseModel):
    model_config = ConfigDict(extra="allow")

    trainer: Optional[str] = None
    power_source: Optional[Literal["trainer", "power_meter"]] = None
    control_mode: Optional[Literal["erg", "manual"]] = None


class InPersonTestData(BaseModel):
    """Protocol-specific block — extra keys allowed per TEST_JSON_CONTRACT.md."""

    model_config = ConfigDict(extra="allow")

    steps: Optional[List[Dict[str, Any]]] = None
    power_w: Optional[List[float]] = None
    lactate_mmol_l: Optional[List[float]] = None
    heart_rate_bpm: Optional[List[float]] = None
    duration_s: Optional[Union[int, float, List[float]]] = None


InPersonTestType = Literal["mader", "incrementale", "curva_pc", "critical_power", "wingate"]


class InPersonTestEnvelope(BaseModel):
    test_type: InPersonTestType
    timestamp: Optional[str] = None
    athlete: InPersonAthlete = Field(default_factory=InPersonAthlete)
    device: Optional[InPersonDevice] = None
    test_data: InPersonTestData = Field(default_factory=InPersonTestData)

    def to_engine_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)


class PowerDurationPoint(BaseModel):
    """MMP value for a single duration."""

    power_w: Optional[float] = Field(default=None, gt=0)
    value: Optional[float] = Field(default=None, gt=0)

    def watts(self) -> Optional[float]:
        return self.power_w if self.power_w is not None else self.value


class PowerSourceActivity(BaseModel):
    """One activity signature for offset detection."""

    model_config = ConfigDict(extra="allow")

    activity_id: Optional[str] = None
    power_source_id: Optional[str] = None
    source_id: Optional[str] = None
    device_id: Optional[str] = None
    trainer_id: Optional[str] = None
    modality: Optional[str] = None
    discipline: Optional[str] = None
    device_name: Optional[str] = None
    source: Optional[str] = None
    mmp: Dict[str, Union[float, int, PowerDurationPoint]] = Field(default_factory=dict)
    mmp_curve: Dict[str, Union[float, int, PowerDurationPoint]] = Field(default_factory=dict)
    curve: Dict[str, Union[float, int, PowerDurationPoint]] = Field(default_factory=dict)
    power_curve: Dict[str, Union[float, int, PowerDurationPoint]] = Field(default_factory=dict)

    def merged_mmp_dict(self) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for source in (self.mmp, self.mmp_curve, self.curve, self.power_curve):
            merged.update(source)
        return merged

    def to_engine_dict(self) -> Dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        if not data.get("mmp"):
            mmp = self.merged_mmp_dict()
            if mmp:
                data["mmp"] = mmp
        return data


class TwinStateBuildPayload(BaseModel):
    """Input fragments accepted by POST /twin/state/build."""

    model_config = ConfigDict(extra="allow")

    athlete_id: Optional[str] = None
    athlete_profile: Optional[AthleteProfileSnippet] = None
    athlete: Optional[AthleteProfileSnippet] = None
    measured_anchor: Optional[Dict[str, Any]] = None
    anchor: Optional[Dict[str, Any]] = None
    metabolic_snapshot: Optional[Dict[str, Any]] = None
    snapshot: Optional[Dict[str, Any]] = None
    rolling_power_curve: Optional[Dict[str, Any]] = None
    curve: Optional[Dict[str, Any]] = None
    load_state: Optional[Dict[str, Any]] = None
    readiness_state: Optional[Dict[str, Any]] = None
    sensor_quality: Optional[Dict[str, Any]] = None
    warnings: List[str] = Field(default_factory=list)
    event_log: List[Dict[str, Any]] = Field(default_factory=list)
    source: Optional[str] = None

    def to_engine_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)


class TwinStateDocument(BaseModel):
    """Canonical twin_state.v1 blob for update/projection endpoints."""

    model_config = ConfigDict(extra="allow")

    schema_version: Literal["twin_state.v1"] = TWIN_STATE_SCHEMA_VERSION
    athlete_id: str = Field(min_length=1)
    created_at: str
    updated_at: str
    athlete_profile: Dict[str, Any] = Field(default_factory=dict)
    measured_anchor: Dict[str, Any] = Field(default_factory=dict)
    metabolic_snapshot: Dict[str, Any] = Field(default_factory=dict)
    rolling_power_curve: Dict[str, Any] = Field(default_factory=dict)
    load_state: Dict[str, Any] = Field(default_factory=dict)
    readiness_state: Dict[str, Any] = Field(default_factory=dict)
    sensor_quality: Dict[str, Any] = Field(default_factory=dict)
    workout_calendar_state: Dict[str, Any] = Field(default_factory=dict)
    last_compliance_results: List[Dict[str, Any]] = Field(default_factory=list)
    team_calibration_state: Dict[str, Any] = Field(default_factory=dict)
    state_confidence: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    event_log: List[Dict[str, Any]] = Field(default_factory=list)

    def to_engine_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)


class CalendarPlanEvent(BaseModel):
    """One planned workout/assignment in a season projection."""

    model_config = ConfigDict(extra="allow")

    day: Optional[int] = None
    date: Optional[str] = None
    workout: Optional[WorkoutDefinitionInput] = None
    tss: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None

    def to_engine_dict(self) -> Dict[str, Any]:
        out = self.model_dump(exclude_none=True)
        if isinstance(self.workout, WorkoutDefinitionInput):
            out["workout"] = self.workout.to_engine_dict()
        return out


class ComplianceResult(BaseModel):
    """Output shape from POST /workouts/compare."""

    model_config = ConfigDict(extra="allow")

    status: Optional[str] = None
    compliance_score: Optional[float] = Field(default=None, ge=0, le=100)
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)
    discrepancies: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    def to_engine_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)
