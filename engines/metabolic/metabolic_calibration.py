"""Versioned empirical calibration used by the metabolic profiler.

The values in this module reproduce the existing production tuning. They are
kept separate from Mader model constants and from software policy so future
validation can change one layer without silently changing the others.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class MetabolicCalibration:
    """Empirical tuning parameters for fitting and sprint decomposition."""

    version: str = "1.0.0"
    schema_version: str = "1.0"
    source: str = "production_tuning_pre_policy_extraction"
    validation_status: str = "internal_empirical_calibration"

    # Mechanical power <-> oxygen-demand conversion.
    watts_to_vo2_coefficient: float = 10.8
    reference_efficiency: float = 0.23
    map_power_min_w: float = 50.0
    map_power_max_w: float = 2500.0

    # Lactate kinetics and duration power cap.
    tau_vo2_anchor: float = 80.0
    tau_vo2_span: float = 40.0
    tau_vo2_slope: float = 0.4
    tau_vlamax_anchor: float = 0.30
    tau_vlamax_span: float = 1.0
    tau_vlamax_slope: float = 15.0
    tau_min_s: float = 12.0
    tau_max_s: float = 65.0
    cap_factor_base: float = 1.5
    cap_factor_amplitude: float = 2.5
    cap_factor_decay_s: float = 120.0

    # APR -> admissible VLamax basin mapping.
    apr_ratio_anchor: float = 0.8
    apr_vlamax_low_intercept: float = 0.10
    apr_vlamax_low_slope: float = 0.12
    apr_vlamax_low_bounds: Tuple[float, float] = (0.10, 0.40)
    apr_vlamax_high_intercept: float = 0.40
    apr_vlamax_high_slope: float = 0.38
    apr_vlamax_high_bounds: Tuple[float, float] = (0.40, 1.20)
    apr_vlamax_minimum_band_width: float = 0.15

    # Fit weighting and initial conditions.
    weight_baseline: float = 0.35
    weight_peak_amplitude: float = 0.65
    weight_peak_duration_s: float = 360.0
    weight_log_sigma: float = 0.8
    weight_short_reference_s: float = 20.0
    weight_short_min: float = 0.25
    weight_long_reference_s: float = 900.0
    weight_long_min: float = 0.60
    vo2_guess_floor: float = 35.0
    vo2_guess_ceiling: float = 85.0
    vo2_guess_power_multiplier: float = 12.0
    fit_grid_floor_max_w: float = 2000.0
    fit_grid_power_per_kg_max: float = 30.0
    short_mae_duration_s: float = 30.0

    # Physiological coherence anchors and regularization penalties.
    observed_threshold_vo2_margin: float = 1.05
    mlss_observed_ratio_ceiling: float = 1.10
    vo2_floor_penalty_scale: float = 5.0
    mlss_ceiling_penalty_scale: float = 55.0
    mlss_basin_penalty_scale: float = 1.0e6
    apr_centre_tiebreak_scale: float = 2.0e3

    # Lactate-capacity and residual PCr contribution.
    lacap_intercept: float = 10.0
    lacap_vlamax_anchor: float = 0.20
    lacap_vlamax_slope: float = 15.0
    pcr_decay_start_s: float = 20.0
    pcr_decay_tau_s: float = 35.0

    # Deterministic multi-start mesh.
    vlamax_starts: Tuple[float, ...] = (0.20, 0.35, 0.50, 0.70, 0.90)
    apr_midpoint_start_min: float = 0.10
    apr_midpoint_start_max: float = 1.30
    vo2_floor_start_offset: float = 5.0
    vo2_lower_start_offset: float = -6.0
    vo2_upper_start_offset: float = 8.0

    # Curve/output calibration.
    curve_power_min_w: float = 50.0
    curve_power_floor_max_w: float = 700.0
    curve_power_per_kg_max: float = 12.0
    curve_power_step_w: float = 5.0
    curve_vo2_margin: float = 0.10
    fatmax_peak_fraction: float = 0.98

    # Direct sprint-decomposition calibration.
    sprint_min_sustain_intercept: float = 0.70
    sprint_min_sustain_duration_slope: float = 0.012
    sprint_min_sustain_floor: float = 0.40
    sprint_neuromuscular_scale: float = 0.98
    sprint_aerobic_contribution_scale: float = 0.50
    energy_j_per_mmol_lactate_per_kg: float = 63.0
    sprint_min_resolved_vlamax: float = 0.08
    sprint_vlamax_bounds: Tuple[float, float] = (0.05, 1.50)
    sprint_tau_sensitivity_bounds_s: Tuple[float, float] = (12.0, 20.0)

    def __post_init__(self) -> None:
        if self.watts_to_vo2_coefficient <= 0 or self.reference_efficiency <= 0:
            raise ValueError("power-to-VO2 conversion must be positive")
        if self.map_power_min_w >= self.map_power_max_w:
            raise ValueError("MAP power bounds are invalid")
        if self.tau_min_s >= self.tau_max_s:
            raise ValueError("tau bounds are invalid")
        if self.apr_vlamax_low_bounds[0] >= self.apr_vlamax_low_bounds[1]:
            raise ValueError("APR low-band bounds are invalid")
        if self.apr_vlamax_high_bounds[0] >= self.apr_vlamax_high_bounds[1]:
            raise ValueError("APR high-band bounds are invalid")
        if not self.vlamax_starts:
            raise ValueError("vlamax_starts cannot be empty")
        if self.curve_power_step_w <= 0:
            raise ValueError("curve_power_step_w must be positive")
        if self.sprint_vlamax_bounds[0] >= self.sprint_vlamax_bounds[1]:
            raise ValueError("sprint VLamax bounds are invalid")

    def to_dict(self) -> Dict[str, Any]:
        """Return the calibration manifest used to reproduce an estimate."""
        return {
            "schema_version": self.schema_version,
            "version": self.version,
            "classification": "empirical_calibration",
            "source": self.source,
            "validation_status": self.validation_status,
            "power_oxygen_conversion": {
                "watts_to_vo2_coefficient": self.watts_to_vo2_coefficient,
                "reference_efficiency": self.reference_efficiency,
                "map_power_bounds_w": [self.map_power_min_w, self.map_power_max_w],
            },
            "apr_vlamax_mapping": {
                "apr_ratio_anchor": self.apr_ratio_anchor,
                "low_intercept": self.apr_vlamax_low_intercept,
                "low_slope": self.apr_vlamax_low_slope,
                "low_bounds": list(self.apr_vlamax_low_bounds),
                "high_intercept": self.apr_vlamax_high_intercept,
                "high_slope": self.apr_vlamax_high_slope,
                "high_bounds": list(self.apr_vlamax_high_bounds),
                "minimum_band_width": self.apr_vlamax_minimum_band_width,
            },
            "fit_weighting": {
                "baseline": self.weight_baseline,
                "peak_amplitude": self.weight_peak_amplitude,
                "peak_duration_s": self.weight_peak_duration_s,
                "log_sigma": self.weight_log_sigma,
                "short_reference_s": self.weight_short_reference_s,
                "short_min": self.weight_short_min,
                "long_reference_s": self.weight_long_reference_s,
                "long_min": self.weight_long_min,
                "fit_grid_floor_max_w": self.fit_grid_floor_max_w,
                "fit_grid_power_per_kg_max": self.fit_grid_power_per_kg_max,
                "short_mae_duration_s": self.short_mae_duration_s,
            },
            "coherence": {
                "observed_threshold_vo2_margin": self.observed_threshold_vo2_margin,
                "mlss_observed_ratio_ceiling": self.mlss_observed_ratio_ceiling,
                "vo2_floor_penalty_scale": self.vo2_floor_penalty_scale,
                "mlss_ceiling_penalty_scale": self.mlss_ceiling_penalty_scale,
                "mlss_basin_penalty_scale": self.mlss_basin_penalty_scale,
                "apr_centre_tiebreak_scale": self.apr_centre_tiebreak_scale,
            },
            "lacap_pcr": {
                "lacap_intercept": self.lacap_intercept,
                "lacap_vlamax_anchor": self.lacap_vlamax_anchor,
                "lacap_vlamax_slope": self.lacap_vlamax_slope,
                "pcr_decay_start_s": self.pcr_decay_start_s,
                "pcr_decay_tau_s": self.pcr_decay_tau_s,
            },
            "multi_start": {
                "vlamax_starts": list(self.vlamax_starts),
                "vo2_floor_start_offset": self.vo2_floor_start_offset,
                "vo2_lower_start_offset": self.vo2_lower_start_offset,
                "vo2_upper_start_offset": self.vo2_upper_start_offset,
            },
            "sprint_decomposition": {
                "minimum_sustain_intercept": self.sprint_min_sustain_intercept,
                "minimum_sustain_duration_slope": self.sprint_min_sustain_duration_slope,
                "minimum_sustain_floor": self.sprint_min_sustain_floor,
                "neuromuscular_scale": self.sprint_neuromuscular_scale,
                "aerobic_contribution_scale": self.sprint_aerobic_contribution_scale,
                "energy_j_per_mmol_lactate_per_kg": (
                    self.energy_j_per_mmol_lactate_per_kg
                ),
                "minimum_resolved_vlamax": self.sprint_min_resolved_vlamax,
                "vlamax_bounds": list(self.sprint_vlamax_bounds),
                "tau_sensitivity_bounds_s": list(self.sprint_tau_sensitivity_bounds_s),
            },
        }


DEFAULT_METABOLIC_CALIBRATION = MetabolicCalibration()
