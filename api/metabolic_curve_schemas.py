"""Request schemas for coach-facing metabolic curves."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from api.schemas import AthleteParams

CurveName = Literal[
    "vo2_demand",
    "substrate_oxidation",
    "lactate",
    "energy_contribution_by_duration",
]


class MetabolicCurveLactateStepModel(BaseModel):
    power_w: float = Field(..., gt=0)
    lactate_mmol: float = Field(..., gt=0)
    hr_mean: Optional[float] = Field(default=None, gt=0)
    heart_rate_bpm: Optional[float] = Field(default=None, gt=0)
    cadence_mean: Optional[float] = Field(default=None, gt=0)
    duration_s: Optional[float] = Field(default=None, gt=0)


class MetabolicCurvesRequest(BaseModel):
    athlete: AthleteParams
    mmp: Dict[str, float] = Field(default_factory=dict)
    metabolic_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional precomputed metabolic snapshot. If omitted, the service builds one from MMP.",
    )
    expected_eta: Optional[float] = Field(
        default=None,
        gt=0.10,
        lt=0.35,
        description="Gross efficiency used for VO2 demand estimates.",
    )
    measured_lacap: Optional[float] = None
    effective_cadence_rpm: Optional[float] = Field(default=None, gt=0, le=220)
    clean_mmp_first: bool = False
    power_points: Optional[List[float]] = Field(
        default=None,
        description="Optional watt anchors for generated power-domain curves.",
    )
    lactate_steps: Optional[List[MetabolicCurveLactateStepModel]] = None
    durations_s: Optional[List[float]] = Field(
        default=None,
        description="Optional durations for energy contribution curve.",
    )
    include_curves: Optional[List[CurveName]] = Field(
        default=None,
        description="Subset of curves to generate. Defaults to all coach-critical curves.",
    )
