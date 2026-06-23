"""Request models for extended engine API coverage."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from api.schemas import AthleteParams, TauModel


class MmpAthleteRequest(BaseModel):
    mmp: Dict[str, float]
    athlete: AthleteParams
    expected_eta: Optional[float] = None
    measured_lacap: Optional[float] = None
    effective_cadence_rpm: Optional[float] = Field(default=None, gt=0, le=220)
    tau_model: Optional[TauModel] = None
    clean_mmp_first: bool = False


class SegmentedSnapshotRequest(MmpAthleteRequest):
    aerobic_min_duration_s: float = Field(default=120.0, ge=30)


class BayesianSnapshotRequest(MmpAthleteRequest):
    n_samples: int = Field(default=4000, ge=500, le=20000)
    n_warmup: int = Field(default=1000, ge=100, le=10000)
    seed: int = 42


class VlamaxSprintRequest(BaseModel):
    athlete: AthleteParams
    p_peak_1s: float = Field(..., gt=0)
    p_mean_sprint: float = Field(..., gt=0)
    sprint_duration_s: float = Field(default=15.0, gt=0, le=60)
    vo2max_power_w: Optional[float] = Field(default=None, gt=0)


class KalmanDailyInputModel(BaseModel):
    date: str
    vo2max_stimulus_min: float = 0.0
    threshold_stimulus_min: float = 0.0
    anaerobic_stimulus_min: float = 0.0
    neuromuscular_stimulus_min: float = 0.0
    test_anchors: Optional[List[List[float]]] = None


class KalmanTrajectoryRequest(BaseModel):
    athlete: AthleteParams
    daily_inputs: List[KalmanDailyInputModel]
    initial_vo2: float = Field(..., gt=20, lt=100)
    initial_vla: float = Field(..., gt=0.05, lt=2.0)
    initial_vo2_std: float = Field(default=5.0, gt=0)
    initial_vla_std: float = Field(default=0.15, gt=0)
    athlete_id: Optional[str] = None


class MetabolicCurrentRequest(BaseModel):
    athlete: AthleteParams
    historical_mmp: Dict[str, float]
    workout_history: List[Dict[str, Any]] = Field(default_factory=list)
    as_of: Optional[str] = None


class DetrainingApplyRequest(BaseModel):
    athlete: AthleteParams
    baseline_snapshot: Dict[str, Any]
    workout_history: List[Dict[str, Any]] = Field(default_factory=list)
    as_of: Optional[str] = None


class CtlAtlTsbRequest(BaseModel):
    tss_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of {date, tss} entries.",
    )


class CrossValidateRequest(MmpAthleteRequest):
    pass


class MmpQualityRequest(BaseModel):
    mmp: Dict[str, float]
    clean: bool = False


class LactateStepModel(BaseModel):
    power_w: float
    lactate_mmol: float
    hr_mean: Optional[float] = None
    cadence_mean: Optional[float] = None
    duration_s: Optional[float] = None


class LactateThresholdsRequest(BaseModel):
    steps: List[LactateStepModel]


class LactateValidateModelRequest(BaseModel):
    athlete: AthleteParams
    steps: List[LactateStepModel]
    mmp: Dict[str, float]
    expected_eta: Optional[float] = None


class VlapeakObservedRequest(BaseModel):
    lactate_pre_mmol: float = Field(..., ge=0)
    lactate_post_mmol: float = Field(..., ge=0)
    duration_s: float = Field(..., gt=0)


class VlapeakValidateRequest(BaseModel):
    vlapeak_observed_mmol_l_s: float = Field(..., gt=0)
    predicted_vlapeak_mmol_l_s: float = Field(..., gt=0)
    model_vlamax_mmol_l_s: Optional[float] = None


class GlycolyticProfileRequest(MmpAthleteRequest):
    pass


class LabTextParseRequest(BaseModel):
    text: str
    source: str = "unknown"


class LabResultValidateRequest(BaseModel):
    lab_result: Dict[str, Any]


class WPrimeBalanceRequest(BaseModel):
    power: List[float] = Field(..., min_length=2)
    cp: float = Field(..., gt=0)
    w_prime: float = Field(..., gt=0)
    dt_s: float = Field(default=1.0, gt=0)
    duration_s: Optional[float] = None
    tau_model: Optional[TauModel] = None
    athlete_profile: Dict[str, Any] = Field(default_factory=dict)


class DurabilityIndexRequest(BaseModel):
    power: List[float] = Field(..., min_length=10)


class ExplainabilityVo2ConfidenceRequest(BaseModel):
    mmp_curve: Dict[str, float]
    efforts_count: int = Field(..., ge=0)
    data_quality_score: float = Field(default=1.0, ge=0, le=1)


class ExplainabilityDurabilityConfidenceRequest(BaseModel):
    duration_hours: float = Field(..., gt=0)
    power_data_completeness: float = Field(default=1.0, ge=0, le=1)


class ExplainabilityAcwrNarrativeRequest(BaseModel):
    acwr_value: float
    risk_level: str
    ctl: float
    atl: float
    tsb: float


class ExplainabilityMetricNarrativeRequest(BaseModel):
    metric_name: str
    value: float
    confidence: Dict[str, Any]
    context: Dict[str, Any] = Field(default_factory=dict)


class ExplainabilityWorkoutSummaryRequest(BaseModel):
    summary: Dict[str, Any]


class AcwrRequest(BaseModel):
    acute_load: float = Field(..., ge=0)
    chronic_load: float = Field(..., ge=0)


class MonotonyStrainRequest(BaseModel):
    daily_tss: List[float] = Field(..., min_length=1)


class ZonesAnalyzeRequest(BaseModel):
    athlete: AthleteParams
    ftp: Optional[float] = None
    lthr: Optional[float] = None
    vt1_w: Optional[float] = None
    vt2_w: Optional[float] = None
    vt1_bpm: Optional[float] = None
    vt2_bpm: Optional[float] = None


class EffortsAnalyzeRequest(BaseModel):
    athlete: AthleteParams
    metabolic_snapshot: Optional[Dict[str, Any]] = None
    cp_w: Optional[float] = None
    w_prime_j: Optional[float] = None


class SessionClassifyRequest(BaseModel):
    athlete: AthleteParams
    ftp: Optional[float] = None


class RaceGpxSimulateRequest(BaseModel):
    gpx_text: str
    weight_kg: float = Field(default=70.0, gt=30, lt=200)
    ftp_w: float = Field(default=250.0, gt=0)
    metabolic_snapshot: Optional[Dict[str, Any]] = None
    bike_weight_kg: float = Field(default=8.0, gt=0)


class RaceGpxAnalyzeRequest(BaseModel):
    gpx_text: str


class IntegrationNormalizeRequest(BaseModel):
    activity: Dict[str, Any]


class IntegrationDeduplicateRequest(BaseModel):
    activities: List[Dict[str, Any]]


class AdaptiveLoadRequest(BaseModel):
    athlete: AthleteParams
    workout_summary: Dict[str, Any] = Field(default_factory=dict)
    ftp: Optional[float] = None
    daily_status: Optional[Dict[str, Any]] = None
    history: Optional[List[Dict[str, Any]]] = None


class ChartConfigRequest(BaseModel):
    chart_type: Literal[
        "mmp",
        "zones",
        "hrv",
        "training_load",
        "detraining",
        "power_duration",
    ]
    payload: Dict[str, Any] = Field(default_factory=dict)


class TwinValidateRequest(BaseModel):
    twin_state: Dict[str, Any]


class WPrimeTauRequest(BaseModel):
    tau_model: TauModel
    athlete_profile: Dict[str, Any] = Field(default_factory=dict)


class PowerSeriesRequest(BaseModel):
    power: List[float] = Field(..., min_length=2)


class TteSustainabilityRequest(BaseModel):
    power: List[float] = Field(..., min_length=10)
    cp: float = Field(..., gt=0)


class HourlyDecayRequest(BaseModel):
    power: List[float] = Field(..., min_length=60)
    ftp: float = Field(..., gt=0)


class DurabilityPrescriptionRequest(BaseModel):
    durability_index: float


class CriticalPowerFitRequest(BaseModel):
    mmp_curve: List[Dict[str, Any]]


class ThermalAcclimationRequest(BaseModel):
    sessions: List[Dict[str, Any]]


class ResilienceRequest(BaseModel):
    mader_durability: Optional[Dict[str, Any]] = None


class MetabolicFlexibilityRequest(BaseModel):
    snapshot: Dict[str, Any]


class CompareSegmentsRequest(BaseModel):
    history: List[Dict[str, Any]]
    new_segments: List[Dict[str, Any]]


class AdaptiveTrendRequest(BaseModel):
    history: List[Dict[str, Any]]


class AdaptiveRecommendationRequest(BaseModel):
    report: Dict[str, Any]


class DurabilityNarrativeRequest(BaseModel):
    payload: Dict[str, Any]


class LabCreateResultRequest(BaseModel):
    test_date: Optional[str] = None
    source: str = "manual_entry"
    vo2max: Optional[float] = None
    vlamax: Optional[float] = None
    mlss_w: Optional[float] = None
    ftp_w: Optional[float] = None
    weight_kg: Optional[float] = None
    notes: str = ""
    extra: Dict[str, Any] = Field(default_factory=dict)
