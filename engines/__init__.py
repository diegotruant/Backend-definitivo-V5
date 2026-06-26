"""Public compatibility facade exposing the stable analytics API."""

import importlib
import sys
import types
import warnings

# Canonical locations for each module after the subpackage reorganisation.
# Maps short name → new fully-qualified module path.
_SUBPACKAGE_MAP: dict[str, str] = {
    # core
    "analysis": "engines.core.analysis",
    "athlete_context": "engines.core.athlete_context",
    "athlete_physiological_prior": "engines.core.athlete_physiological_prior",
    "audit": "engines.core.audit",
    "data_quality_engine": "engines.core.data_quality_engine",
    "metric_contracts": "engines.core.metric_contracts",
    "tiers": "engines.core.tiers",
    # metabolic
    "bayesian_profiler": "engines.metabolic.bayesian_profiler",
    "coggan_classifier": "engines.metabolic.coggan_classifier",
    "cross_validation_engine": "engines.metabolic.cross_validation_engine",
    "detraining_engine": "engines.metabolic.detraining_engine",
    "lab_data": "engines.metabolic.lab_data",
    "lactate_validation_engine": "engines.metabolic.lactate_validation_engine",
    "metabolic_current": "engines.metabolic.metabolic_current",
    "metabolic_flexibility_engine": "engines.metabolic.metabolic_flexibility_engine",
    "metabolic_kalman": "engines.metabolic.metabolic_kalman",
    "metabolic_profiler": "engines.metabolic.metabolic_profiler",
    "metabolic_profiler_phenotype": "engines.metabolic.metabolic_profiler_phenotype",
    "zones_engine": "engines.metabolic.zones_engine",
    # performance
    "durability_engine": "engines.performance.durability_engine",
    "efforts_analyzer": "engines.performance.efforts_analyzer",
    "interval_detector": "engines.performance.interval_detector",
    "mader_durability": "engines.performance.mader_durability",
    "mader_residual_mlp": "engines.performance.mader_residual_mlp",
    "mmp_aggregator": "engines.performance.mmp_aggregator",
    "mmp_quality": "engines.performance.mmp_quality",
    "neural_ode": "engines.performance.mader_residual_mlp",
    "power_engine": "engines.performance.power_engine",
    "race_prediction_engine": "engines.performance.race_prediction_engine",
    "test_protocols": "engines.performance.test_protocols",
    "training_variability_engine": "engines.performance.training_variability_engine",
    "w_prime_balance_engine": "engines.performance.w_prime_balance_engine",
    # recovery
    "cardiac_engine": "engines.recovery.cardiac_engine",
    "explainability_engine": "engines.recovery.explainability_engine",
    "hrv_engine": "engines.recovery.hrv_engine",
    "pedaling_balance": "engines.recovery.pedaling_balance",
    "thermal_engine": "engines.recovery.thermal_engine",
    # io
    "activity_charts": "engines.io.activity_charts",
    "chart_builder": "engines.io.chart_builder",
    "fit_parser": "engines.io.fit_parser",
    "profile_anchor_flow": "engines.io.profile_anchor_flow",
    "session_router": "engines.io.session_router",
    "workout_summary": "engines.io.workout_summary",
}

_LEGACY_BOOTSTRAP = True


class _LegacyModule(types.ModuleType):
    """Warn when flat legacy imports are used outside the engines bootstrap."""

    def __init__(self, name: str, canonical: str, module: types.ModuleType):
        super().__init__(name)
        self.__dict__.update(module.__dict__)
        self.__name__ = name
        self._canonical = canonical
        self._warned = False

    def __getattribute__(self, name: str):
        if name not in {
            "_canonical",
            "_warned",
            "__dict__",
            "__name__",
            "__file__",
            "__loader__",
            "__spec__",
            "__path__",
            "__package__",
        }:
            if not _LEGACY_BOOTSTRAP and not object.__getattribute__(self, "_warned"):
                warnings.warn(
                    (
                        f"Flat import '{object.__getattribute__(self, '__name__')}' is deprecated; "
                        f"use '{object.__getattribute__(self, '_canonical')}' instead."
                    ),
                    DeprecationWarning,
                    stacklevel=2,
                )
                object.__setattr__(self, "_warned", True)
        return super().__getattribute__(name)


# Register backward-compat aliases so that both
#   `from engines.fit_parser import X`  (old style)
#   `import fit_parser` / `from fit_parser import X`  (flat legacy style)
# continue to resolve after the subpackage reorganisation.
for _short, _canonical in _SUBPACKAGE_MAP.items():
    _mod = importlib.import_module(_canonical)
    sys.modules[f"engines.{_short}"] = _mod
    sys.modules[_short] = _LegacyModule(_short, _canonical, _mod)

_LEGACY_BOOTSTRAP = False

from engines.core.athlete_context import AthleteContext
from engines.metabolic.bayesian_profiler import (
    BayesianMetabolicSnapshot,
    PosteriorSummary,
    bayesian_metabolic_snapshot,
)
from engines.core.data_quality_engine import assess_data_quality, clean_workout_data
from engines.metabolic.detraining_engine import apply_detraining_model, calculate_ctl_atl_tsb
from engines.performance.durability_engine import (
    calculate_durability_index,
    calculate_np_drift,
    generate_hourly_decay_curve,
)
from engines.performance.mader_durability import (
    DurabilityAthleteParams,
    MaderDurabilityEngine,
    compute_session_durability,
    from_metabolic_snapshot,
    sustainability_targets,
)
from engines.recovery.explainability_engine import (
    calculate_durability_confidence,
    generate_acwr_narrative,
    generate_durability_narrative,
)
from engines.io.fit_parser import parse_fit_records_enhanced, parse_fit_file_enhanced
from engines.performance.efforts_analyzer import analyze_efforts
from engines.performance.mmp_aggregator import (
    update_power_curve,
    extract_ride_curve,
    curve_to_mmp,
    CurveUpdateResult,
    CurveEntry,
)
from engines.metabolic.cross_validation_engine import (
    cross_validate_metabolic_profile,
    CrossValidationResult,
)
from engines.metabolic.lab_data import (
    LabSource,
    LabTestType,
    LabTestResult,
    LactatePoint,
    create_lab_result,
    parse_lab_text,
    parse_lab_pdf,
    validate_lab_result,
)
from engines.metabolic.lactate_validation_engine import (
    LactateStep,
    LactateThresholds,
    compute_lactate_thresholds,
    steps_from_payload,
    validate_model_against_lactate,
)
from engines.performance.test_protocols import (
    run_critical_power_test,
    run_incremental_test,
    run_mader_test,
    run_power_cadence_test,
    run_test,
    run_wingate_test,
)

# Alias for API / tablet runners
run_in_person_test = run_test
# analyze_rr_stream / calculate_dfa_alpha1 exported lazily — see __getattr__ at bottom
from engines.performance.interval_detector import (
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
from engines.metabolic.metabolic_flexibility_engine import (
    calculate_metabolic_flexibility_index,
    estimate_fat_oxidation_rate,
)
from engines.metabolic.metabolic_kalman import (
    AdaptationConfig,
    DailyInput,
    DecayConfig,
    KalmanTrajectory,
    MetabolicKalman,
    MetabolicState,
    process_workout_history,
)
from engines.metabolic.metabolic_profiler import ExpressivenessReport, MaderConstants, MetabolicProfiler
from engines.metabolic.metabolic_profiler_phenotype import enhance_metabolic_snapshot_with_phenotype
from engines.core.metric_contracts import (
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
from engines.performance.mmp_quality import analyze_mmp_quality, clean_mmp, filter_mmp_by_window
from engines.performance.mader_residual_mlp import (
    DynamicsTrainingResult,
    NeuralDynamics,
    NeuralPDTrainingResult,
    NeuralPowerDuration,
    TinyMLP,
)
from engines.recovery.pedaling_balance import (
    BalanceTrend,
    PedalingBalanceReport,
    analyze_balance_trend,
    analyze_pedaling_balance,
)
from engines.performance.race_prediction_engine import (
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
from engines.recovery.thermal_engine import (
    HeatAcclimationTrend,
    ThermalSessionReport,
    analyze_heat_acclimation,
    analyze_thermal_session,
)
from engines.core.tiers import (
    DEFAULT_DISPLAY_THRESHOLD,
    ENGINE_TIERS,
    SCOPE,
    Tier,
    annotate,
    mask_low_confidence,
    should_display,
    tier_for,
)
from engines.performance.training_variability_engine import calculate_acwr, calculate_monotony_strain
from engines.performance.w_prime_balance_engine import analyze_w_prime_usage, calculate_w_prime_balance
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
    "compute_session_durability",
    "calculate_durability_index",
    "DurabilityAthleteParams",
    "from_metabolic_snapshot",
    "MaderDurabilityEngine",
    "sustainability_targets",
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
    "LactateStep",
    "LactateThresholds",
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

from engines.metabolic.metabolic_current import get_current_metabolic_status
from engines.io.workout_summary import build_workout_summary

# Lazy re-exports for hrv_engine (kept lazy to limit import-time coupling).
_LAZY_EXPORTS = {
    "analyze_rr_stream": ("engines.recovery.hrv_engine", "analyze_rr_stream"),
    "calculate_dfa_alpha1": ("engines.recovery.hrv_engine", "calculate_dfa_alpha1"),
}


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr = _LAZY_EXPORTS[name]
        mod = importlib.import_module(module_name)
        obj = getattr(mod, attr)
        globals()[name] = obj
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
