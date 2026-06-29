"""Request schemas for performance fueling targets (not diets)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from api.domain_schemas import AthleteProfileSnippet


class PerformanceFuelingRequest(BaseModel):
    """Performance fueling availability targets linked to TwinState."""

    model_config = ConfigDict(extra="allow")

    athlete: AthleteProfileSnippet
    twin_state: Optional[Dict[str, Any]] = None
    metabolic_snapshot: Optional[Dict[str, Any]] = None
    metabolic_curves: Optional[Dict[str, Any]] = None
    load_state: Optional[Dict[str, Any]] = None
    readiness_state: Optional[Dict[str, Any]] = None
    strength_prescription: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional output from strength prescription to align fueling with gym load.",
    )
    session_context: str = Field(
        default="bike_endurance",
        description="e.g. bike_endurance, gym_strength, gym_strength + bike_endurance",
    )
    injury_flags: List[str] = Field(default_factory=list)
    power_series: Optional[List[float]] = Field(
        default=None,
        description="Optional power stream to estimate session CHO demand when curves are not precomputed.",
    )
