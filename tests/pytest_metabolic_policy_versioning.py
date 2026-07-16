"""Contracts for versioned metabolic policy and empirical calibration."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json

import pytest

from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_calibration import DEFAULT_METABOLIC_CALIBRATION
from engines.metabolic.metabolic_fit_policy import (
    DEFAULT_METABOLIC_FIT_POLICY,
    MetabolicFitPolicy,
)
from engines.metabolic.metabolic_profiler import MetabolicProfiler


CTX = AthleteContext(gender="MALE", training_years=10, discipline="ROAD")
ALL_ROUNDER_MMP = {
    5: 1100,
    15: 900,
    30: 700,
    60: 520,
    180: 380,
    300: 340,
    600: 310,
    1200: 295,
    1800: 285,
    3600: 270,
}
BIMODAL_MMP = {5: 1100, 15: 1000, 60: 520, 300: 340, 1200: 270, 3600: 240}


def test_default_configuration_manifest_is_versioned_json_safe_and_classified() -> None:
    snap = MetabolicProfiler(72.0, CTX).generate_metabolic_snapshot(ALL_ROUNDER_MMP)

    assert snap["status"] == "success"
    config = snap["model_configuration"]
    assert config["schema_version"] == "1.0"
    assert config["fit_policy"]["version"] == DEFAULT_METABOLIC_FIT_POLICY.version
    assert config["fit_policy"]["classification"] == "software_policy"
    assert (
        config["empirical_calibration"]["version"]
        == DEFAULT_METABOLIC_CALIBRATION.version
    )
    assert (
        config["empirical_calibration"]["classification"]
        == "empirical_calibration"
    )
    assert config["mader_constants"]["classification"] == "physiological_model_constants"
    assert config["regularization_weights"]["classification"] == "fit_regularization"
    json.dumps(config, allow_nan=False)


def test_configuration_manifest_is_attached_to_error_snapshots_too() -> None:
    snap = MetabolicProfiler(72.0, CTX).generate_metabolic_snapshot({60: 400})

    assert snap["status"] == "error"
    assert snap["model_configuration"]["fit_policy"]["version"] == "1.0.0"
    assert snap["model_configuration"]["empirical_calibration"]["version"] == "1.0.0"


def test_policy_is_immutable_and_rejects_invalid_ranges() -> None:
    with pytest.raises(FrozenInstanceError):
        DEFAULT_METABOLIC_FIT_POLICY.bimodality_threshold = 3.8  # type: ignore[misc]

    with pytest.raises(ValueError, match="eta range"):
        MetabolicFitPolicy(minimum_eta=0.30, maximum_eta=0.20)


def test_custom_policy_changes_only_the_declared_auto_strategy_threshold() -> None:
    default_snap = MetabolicProfiler(72.0, CTX).generate_metabolic_snapshot_auto(
        ALL_ROUNDER_MMP
    )
    custom_policy = replace(
        DEFAULT_METABOLIC_FIT_POLICY,
        version="test-bimodality-4.0",
        bimodality_threshold=4.0,
    )
    custom_snap = MetabolicProfiler(
        72.0,
        CTX,
        fit_policy=custom_policy,
    ).generate_metabolic_snapshot_auto(ALL_ROUNDER_MMP)

    assert default_snap["fit_method"] == "joint_auto"
    assert custom_snap["fit_method"] == "segmented"
    assert custom_snap["model_configuration"]["fit_policy"]["version"] == (
        "test-bimodality-4.0"
    )
    assert custom_snap["model_configuration"]["fit_policy"]["fit_strategy"][
        "bimodality_threshold"
    ] == 4.0
    runtime = custom_snap["model_configuration"]["runtime_parameters"][
        "bimodality_threshold"
    ]
    assert runtime == {"value": 4.0, "source": "fit_policy"}


def test_per_call_threshold_override_is_explicit_and_does_not_mutate_policy() -> None:
    profiler = MetabolicProfiler(72.0, CTX)
    snap = profiler.generate_metabolic_snapshot_auto(
        ALL_ROUNDER_MMP,
        bimodal_threshold=4.0,
    )

    assert snap["fit_method"] == "segmented"
    runtime = snap["model_configuration"]["runtime_parameters"][
        "bimodality_threshold"
    ]
    assert runtime == {"value": 4.0, "source": "argument_override"}
    assert profiler.fit_policy.bimodality_threshold == 4.2


def test_segmented_duration_comes_from_policy_and_is_recorded() -> None:
    custom_policy = replace(
        DEFAULT_METABOLIC_FIT_POLICY,
        version="test-aerobic-floor-600",
        segmented_aerobic_min_duration_s=600.0,
    )
    snap = MetabolicProfiler(
        72.0,
        CTX,
        fit_policy=custom_policy,
    ).generate_metabolic_snapshot_segmented(BIMODAL_MMP)

    assert snap["fit_method"] == "joint_fallback"
    assert snap["segmented_detail"]["aerobic_min_duration_s"] == 600.0
    runtime = snap["model_configuration"]["runtime_parameters"][
        "segmented_aerobic_min_duration_s"
    ]
    assert runtime == {"value": 600.0, "source": "fit_policy"}


def test_custom_calibration_is_used_by_apr_mapping_and_versioned() -> None:
    custom_calibration = replace(
        DEFAULT_METABOLIC_CALIBRATION,
        version="test-apr-high-intercept",
        apr_vlamax_high_intercept=0.55,
    )
    default_profiler = MetabolicProfiler(72.0, CTX)
    custom_profiler = MetabolicProfiler(
        72.0,
        CTX,
        calibration=custom_calibration,
    )

    default_band = default_profiler._apr_vlamax_band({5: 900}, map_provisional=350.0)
    custom_band = custom_profiler._apr_vlamax_band({5: 900}, map_provisional=350.0)

    assert default_band is not None and custom_band is not None
    assert custom_band[1] > default_band[1]
    snap = custom_profiler.generate_metabolic_snapshot(ALL_ROUNDER_MMP)
    assert (
        snap["model_configuration"]["empirical_calibration"]["version"]
        == "test-apr-high-intercept"
    )


def test_mader_manifest_includes_numerical_and_pcr_constants_for_reproducibility() -> None:
    config = MetabolicProfiler(72.0, CTX)._model_configuration_manifest()
    mader = config["mader_constants"]

    assert set(
        [
            "mlss_net_frac",
            "eps",
            "softplus_k",
            "w_step",
            "w_min",
            "pcr_prior_min",
            "pcr_prior_max",
        ]
    ).issubset(mader)
