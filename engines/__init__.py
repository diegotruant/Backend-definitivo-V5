"""Public compatibility facade exposing the stable analytics API."""

import importlib
import sys

_SUBMODULE_ALIASES = [
    "analysis",
    "athlete_context",
    "audit",
    "bayesian_profiler",
    "cardiac_engine",
    "chart_builder",
    "coggan_classifier",
    "cross_validation_engine",
    "data_quality_engine",
    "detraining_engine",
    "durability_engine",
    "efforts_analyzer",
    "explainability_engine",
    "fit_parser",
    "hrv_engine",
    "interval_detector",
    "lab_data",
    "lactate_validation_engine",
    "test_protocols",
    "metabolic_current",
    "metabolic_flexibility_engine",
    "metabolic_kalman",
    "metabolic_profiler",
    "metabolic_profiler_phenotype",
    "metric_contracts",
    "mmp_aggregator",
    "mmp_quality",
    "neural_ode",
    "pedaling_balance",
    "power_engine",
    "race_prediction_engine",
    "thermal_engine",
    "tiers",
    "training_variability_engine",
    "w_prime_balance_engine",
    "zones_engine",
    "workout_summary",
]

for _module_name in _SUBMODULE_ALIASES:
    sys.modules[f"{__name__}.{_module_name}"] = importlib.import_module(_module_name)

from athlete_context import AthleteContext
from bayesian_profiler import (
    BayesianMetabolicSnapshot,
    PosteriorSummary,
    bayesian_metabolic_snapshot,
)
from data_quality_engine import assess_data_quality, clean_workout_data
from detraining_engine import apply_detraining_model, calculate_ctl_atl_tsb
from durability_engine import (
    calculate_durability_index,
    calculate_np_drift,
    generate_hourly_decay_curve,
)
from explainability_engine import (
    calculate_durability_confidence,
    generate_acwr_narrative,
    generate_durability_narrative,
)
from fit_parser import parse_fit_records_enhanced, parse_fit_file_enhanced
from efforts_analyzer import analyze_efforts
from mmp_aggregator import (
    update_power_curve,
    extract_ride_curve,
    curve_to_mmp,
    CurveUpdateResult,
    CurveEntry,
)
from cross_validation_engine import (
    cross_validate_metabolic_profile,
    CrossValidationResult,
)
from lab_data import (
    LabSource,
    LabTestType,
    LabTestResult,
    LactatePoint,
    create_lab_result,
    parse_lab_text,
    parse_lab_pdf,
    validate_lab_result,
)
from lactate_validation_engine import (
    compute_lactate_thresholds,
    steps_from_payload,
    validate_model_against_lactate,
)
from test_protocols import (
    run_critical_power_test,
    run_incremental_test,
    run_mader_test,
    run_power_cadence_test,
    run_test,
    run_wingate_test,
)

# Alias for API / tablet runners
run_in_person_test = run_test
from hrv_engine import analyze_rr_stream, calculate_dfa_alpha1
from interval_detector import (
    Category,
    ClassifiedSession,
    ProtocolCompletenessReport,
    QualifiedAnchor,
    SUBTYPES_FREE,
    SUBTYPES_HIIT,
    SUBTYPES_STEADY,
    SUBTYPES_TEST,
    StimulusVector,
    classify_session,
    protocol_completeness,
)
from metabolic_current import get_current_metabolic_status
from metabolic_flexibility_engine import (
    calculate_metabolic_flexibility_index,
    estimate_fat_oxidation_rate,
)
from metabolic_kalman import (
    AdaptationConfig,
    DailyInput,
    DecayConfig,
    KalmanTrajectory,
    MetabolicKalman,
    MetabolicState,
    process_workout_history,
)
from metabolic_profiler import ExpressivenessReport, MaderConstants, MetabolicProfiler
from metabolic_profiler_phenotype import enhance_metabolic_snapshot_with_phenotype
from metric_contracts import (
    ConfidenceLevel,
    MetricEnvelope,
    MetricUncertainty,
    annotate_payload,
    build_api_contract,
    build_uncertainty,
    metric_envelope,
    normalize_confidence,
    summarize_section_contracts,
)
from mmp_quality import analyze_mmp_quality, clean_mmp, filter_mmp_by_window
from neural_ode import (
    DynamicsTrainingResult,
    NeuralDynamics,
    NeuralPDTrainingResult,
    NeuralPowerDuration,
    TinyMLP,
)
from pedaling_balance import (
    BalanceTrend,
    PedalingBalanceReport,
    analyze_balance_trend,
    analyze_pedaling_balance,
)
from race_prediction_engine import (
    AthleteRaceProfile,
    Climb,
    CoursePoint,
    CourseSegment,
    analyze_course,
    build_course_segments,
    detect_climbs,
    parse_gpx_course,
    simulate_gpx_race,
    simulate_race,
)
from thermal_engine import (
    HeatAcclimationTrend,
    ThermalSessionReport,
    analyze_heat_acclimation,
    analyze_thermal_session,
)
from tiers import (
    DEFAULT_DISPLAY_THRESHOLD,
    ENGINE_TIERS,
    SCOPE,
    Tier,
    annotate,
    mask_low_confidence,
    should_display,
    tier_for,
)
from training_variability_engine import calculate_acwr, calculate_monotony_strain
from w_prime_balance_engine import analyze_w_prime_usage, calculate_w_prime_balance
from workout_summary import build_workout_summary

__all__ = [
    "AdaptationConfig",
    "AthleteContext",
    "AthleteRaceProfile",
    "BalanceTrend",
    "BayesianMetabolicSnapshot",
    "Category",
    "ClassifiedSession",
    "Climb",
    "CoursePoint",
    "CourseSegment",
    "DEFAULT_DISPLAY_THRESHOLD",
    "DailyInput",
    "DecayConfig",
    "DynamicsTrainingResult",
    "ENGINE_TIERS",
    "ExpressivenessReport",
    "HeatAcclimationTrend",
    "KalmanTrajectory",
    "MaderConstants",
    "MetricEnvelope",
    "MetricUncertainty",
    "MetabolicKalman",
    "MetabolicProfiler",
    "MetabolicState",
    "NeuralDynamics",
    "NeuralPDTrainingResult",
    "NeuralPowerDuration",
    "PedalingBalanceReport",
    "PosteriorSummary",
    "ProtocolCompletenessReport",
    "QualifiedAnchor",
    "SCOPE",
    "SUBTYPES_FREE",
    "SUBTYPES_HIIT",
    "SUBTYPES_STEADY",
    "SUBTYPES_TEST",
    "StimulusVector",
    "ThermalSessionReport",
    "Tier",
    "TinyMLP",
    "analyze_balance_trend",
    "analyze_heat_acclimation",
    "analyze_mmp_quality",
    "analyze_pedaling_balance",
    "analyze_rr_stream",
    "analyze_thermal_session",
    "analyze_w_prime_usage",
    "analyze_course",
    "annotate",
    "annotate_payload",
    "apply_detraining_model",
    "assess_data_quality",
    "bayesian_metabolic_snapshot",
    "build_workout_summary",
    "build_api_contract",
    "build_course_segments",
    "build_uncertainty",
    "calculate_acwr",
    "calculate_ctl_atl_tsb",
    "calculate_dfa_alpha1",
    "calculate_durability_confidence",
    "calculate_durability_index",
    "calculate_metabolic_flexibility_index",
    "calculate_monotony_strain",
    "calculate_np_drift",
    "calculate_w_prime_balance",
    "classify_session",
    "clean_mmp",
    "clean_workout_data",
    "ConfidenceLevel",
    "detect_climbs",
    "enhance_metabolic_snapshot_with_phenotype",
    "estimate_fat_oxidation_rate",
    "filter_mmp_by_window",
    "generate_acwr_narrative",
    "generate_durability_narrative",
    "generate_hourly_decay_curve",
    "get_current_metabolic_status",
    "mask_low_confidence",
    "metric_envelope",
    "normalize_confidence",
    "parse_gpx_course",
    "parse_fit_records_enhanced",
    "process_workout_history",
    "protocol_completeness",
    "should_display",
    "simulate_gpx_race",
    "simulate_race",
    "summarize_section_contracts",
    "tier_for",
    "analyze_efforts",
    "parse_fit_file_enhanced",
    "LabSource",
    "LabTestType",
    "LabTestResult",
    "LactatePoint",
    "create_lab_result",
    "parse_lab_text",
    "parse_lab_pdf",
    "validate_lab_result",
    "compute_lactate_thresholds",
    "steps_from_payload",
    "validate_model_against_lactate",
    "run_test",
    "run_in_person_test",
    "run_mader_test",
    "run_incremental_test",
    "run_power_cadence_test",
    "run_critical_power_test",
    "run_wingate_test",
    "cross_validate_metabolic_profile",
    "CrossValidationResult",
    "update_power_curve",
    "extract_ride_curve",
    "curve_to_mmp",
    "CurveUpdateResult",
    "CurveEntry",
]
