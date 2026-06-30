"""Pydantic schemas for chart config validation (chart_config.v1)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class ChartAxisSchema(BaseModel):
    label: Optional[str] = None
    unit: Optional[str] = None
    type: Optional[str] = None
    scale: Optional[str] = None
    format: Optional[str] = None
    domain: Optional[List[float]] = None
    categories: Optional[List[str]] = None


class ChartSeriesSchema(BaseModel):
    name: str
    type: Optional[str] = None
    x: Optional[List[Any]] = None
    y: Optional[List[Any]] = None
    values: Optional[List[float]] = None
    data: Optional[Any] = None
    r: Optional[Any] = None
    color: Optional[str] = None

    model_config = {"extra": "allow"}


class ChartConfigBody(BaseModel):
    """Inner chart config returned to frontends."""

    schema_version: Literal["chart_config.v1"] = "chart_config.v1"
    type: str
    title: Optional[str] = None
    description: Optional[str] = None
    measurement_tier: Optional[str] = None
    x_axis: Optional[ChartAxisSchema] = None
    y_axis: Optional[ChartAxisSchema] = None
    y_axes: Optional[List[ChartAxisSchema]] = None
    series: List[ChartSeriesSchema] = Field(default_factory=list)
    categories: Optional[List[str]] = None
    domain: Optional[List[float]] = None

    model_config = {"extra": "allow"}

    @field_validator("series", mode="before")
    @classmethod
    def drop_null_series_entries(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        return [item for item in value if item is not None]


class ChartConfigEnvelope(BaseModel):
    """Response envelope from build_chart_config / POST /meta/chart-config."""

    status: Literal["success"] = "success"
    chart_type: str
    category: str
    config: ChartConfigBody

    @field_validator("config", mode="before")
    @classmethod
    def coerce_config(cls, value: Any) -> Any:
        if isinstance(value, dict) and "schema_version" not in value:
            value = {**value, "schema_version": "chart_config.v1"}
        return value


def validate_chart_envelope(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a chart config response dict."""
    return ChartConfigEnvelope.model_validate(payload).model_dump(exclude_none=True)
