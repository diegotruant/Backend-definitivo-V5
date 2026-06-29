"""Request schemas for strength prescription endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from api.domain_schemas import AthleteProfileSnippet


class UpcomingBikeSession(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Optional[str] = Field(default=None, description="e.g. vo2max, race, endurance")
    session_type: Optional[str] = None
    scheduled_at: Optional[str] = None


class StrengthPrescriptionRequest(BaseModel):
    """Physiology-first strength prescription for cyclists."""

    model_config = ConfigDict(extra="allow")

    athlete: AthleteProfileSnippet
    twin_state: Optional[Dict[str, Any]] = None
    metabolic_snapshot: Optional[Dict[str, Any]] = None
    metabolic_curves: Optional[Dict[str, Any]] = None
    load_state: Optional[Dict[str, Any]] = None
    readiness_state: Optional[Dict[str, Any]] = None
    mmp: Optional[Dict[str, Any]] = Field(default=None, description="Optional MMP for torque/sprint classification.")
    goal: Literal["climbing", "sprint", "time_trial", "granfondo", "general_performance"] = "general_performance"
    season_phase: Literal["off_season", "base", "build", "race", "taper"] = "base"
    gym_experience: Literal["novice", "intermediate", "advanced"] = "intermediate"
    equipment: List[str] = Field(default_factory=lambda: ["barbell", "dumbbells"])
    days_available: int = Field(default=2, ge=1, le=4)
    injury_flags: List[str] = Field(default_factory=list)
    body_mass_strategy: Literal["maintain", "reduce", "increase"] = "maintain"
    upcoming_bike_sessions: List[UpcomingBikeSession] = Field(default_factory=list)
