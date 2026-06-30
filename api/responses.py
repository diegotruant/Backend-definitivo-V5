"""Documented HTTP response models for OpenAPI."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str = Field(description="Always 'ok' when the service is up.", examples=["ok"])
    service: str = Field(description="Service identifier.", examples=["digital-twin-api"])
    version: str = Field(description="API semver.", examples=["5.2.6"])


class EnginePayload(BaseModel):
    """Open-ended JSON returned by physiology engines.

    Field semantics, tiers and confidence rules are documented in
    ``docs/FRONTEND_DEVELOPER_GUIDE.md``. Treat unknown keys as forward-compatible.
    """

    model_config = ConfigDict(extra="allow")


class RideIngestResponse(BaseModel):
    curve: Dict[str, Any] = Field(description="Rolling power-duration curve to persist.")
    mmp_for_profiler: Dict[str, float] = Field(description="MMP slice for metabolic profiler.")
    improvements: int = Field(description="Number of duration records improved on this ride.")
    ride_usable: bool = Field(description="Whether the ride should contribute to the curve.")
    profile_should_refresh: bool = Field(description="Whether anchor/snapshot should be recomputed.")
    notes: List[str] = Field(default_factory=list)


class WorkoutPrescribeResponse(BaseModel):
    status: str = Field(examples=["success"])
    prescription: Dict[str, Any]
    athlete_profile_used: Dict[str, Any]


class ErrorResponse(BaseModel):
    detail: Any = Field(description="Human-readable message or structured error object.")
