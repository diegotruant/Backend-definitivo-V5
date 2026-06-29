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
