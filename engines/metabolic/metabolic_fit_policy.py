"""Versioned software policy for the metabolic profiler.

These values govern input handling, fitting strategy and output exposure. They
are operational decisions, not universal physiological constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class MetabolicFitPolicy:
    """Operational rules used by :class:`MetabolicProfiler`.

    The defaults reproduce the production behavior that existed before this
    policy object was introduced. Changing a value is therefore an explicit,
    versionable product decision and should be accompanied by regression and
    sensitivity tests.
    """

    version: str = "1.0.0"
    schema_version: str = "1.0"

    # Supported input ranges.
    minimum_weight_kg: float = 40.0
    minimum_body_fat_pct: float = 3.0
    maximum_body_fat_pct: float = 55.0
    minimum_eta: float = 0.18
    maximum_eta: float = 0.28
    minimum_lacap_mmol_l: float = 8.0
    maximum_lacap_mmol_l: float = 30.0

    # Curve coverage and strategy selection.
    minimum_mmp_anchors: int = 3
    minimum_fit_anchors: int = 3
    sprint_fit_floor_s: float = 30.0
    segmented_aerobic_min_duration_s: float = 120.0
    bimodality_threshold: float = 4.2
    curve_maximality_floor: float = 2.2

    # Optimizer domain and deterministic output limits.
    optimizer_vo2_min: float = 25.0
    optimizer_vo2_max: float = 95.0
    optimizer_vlamax_min: float = 0.10
    optimizer_vlamax_max: float = 1.50
    minimum_prediction_grid_points: int = 10
    combustion_curve_max_points: int = 40
    input_audit_detail_limit: int = 100

    # Derivation-quality scoring policy. These are not statistical confidence
    # intervals; they control presentation and conservative score caps.
    relative_error_full_scale: float = 0.25
    minimum_confidence: float = 0.05
    maximum_confidence: float = 1.0
    incomplete_expressiveness_confidence_cap: float = 0.40
    submaximal_curve_confidence_cap: float = 0.15

    def __post_init__(self) -> None:
        if self.minimum_weight_kg <= 0:
            raise ValueError("minimum_weight_kg must be positive")
        if self.minimum_body_fat_pct >= self.maximum_body_fat_pct:
            raise ValueError("body-fat range is invalid")
        if self.minimum_eta >= self.maximum_eta:
            raise ValueError("eta range is invalid")
        if self.minimum_lacap_mmol_l >= self.maximum_lacap_mmol_l:
            raise ValueError("lactate-capacity range is invalid")
        if self.minimum_mmp_anchors < 3 or self.minimum_fit_anchors < 3:
            raise ValueError("at least three anchors are required for fitting")
        if self.optimizer_vo2_min >= self.optimizer_vo2_max:
            raise ValueError("VO2 optimizer bounds are invalid")
        if self.optimizer_vlamax_min >= self.optimizer_vlamax_max:
            raise ValueError("VLamax optimizer bounds are invalid")
        if not 0.0 < self.minimum_confidence <= self.maximum_confidence <= 1.0:
            raise ValueError("confidence bounds must satisfy 0 < min <= max <= 1")
        if self.combustion_curve_max_points < 1:
            raise ValueError("combustion_curve_max_points must be positive")

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable JSON-safe representation for audit/reproducibility."""
        return {
            "schema_version": self.schema_version,
            "version": self.version,
            "classification": "software_policy",
            "input_ranges": {
                "minimum_weight_kg": self.minimum_weight_kg,
                "body_fat_pct": [self.minimum_body_fat_pct, self.maximum_body_fat_pct],
                "eta": [self.minimum_eta, self.maximum_eta],
                "lacap_mmol_l": [
                    self.minimum_lacap_mmol_l,
                    self.maximum_lacap_mmol_l,
                ],
            },
            "fit_strategy": {
                "minimum_mmp_anchors": self.minimum_mmp_anchors,
                "minimum_fit_anchors": self.minimum_fit_anchors,
                "sprint_fit_floor_s": self.sprint_fit_floor_s,
                "segmented_aerobic_min_duration_s": self.segmented_aerobic_min_duration_s,
                "bimodality_threshold": self.bimodality_threshold,
                "curve_maximality_floor": self.curve_maximality_floor,
            },
            "optimizer_domain": {
                "vo2": [self.optimizer_vo2_min, self.optimizer_vo2_max],
                "vlamax": [self.optimizer_vlamax_min, self.optimizer_vlamax_max],
                "minimum_prediction_grid_points": self.minimum_prediction_grid_points,
            },
            "output_policy": {
                "combustion_curve_max_points": self.combustion_curve_max_points,
                "input_audit_detail_limit": self.input_audit_detail_limit,
                "relative_error_full_scale": self.relative_error_full_scale,
                "confidence_range": [self.minimum_confidence, self.maximum_confidence],
                "incomplete_expressiveness_confidence_cap": (
                    self.incomplete_expressiveness_confidence_cap
                ),
                "submaximal_curve_confidence_cap": self.submaximal_curve_confidence_cap,
            },
        }


DEFAULT_METABOLIC_FIT_POLICY = MetabolicFitPolicy()
