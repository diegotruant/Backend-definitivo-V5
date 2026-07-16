"""
Metabolic Profiler Engine — PURE PRODUCTION API
Version: 3.3.1-Tethered + AthleteContext (decoupled context module)
Backend module for Physiological Reverse Engineering (MMP -> Phenotype).
No external dependencies beyond numpy and scipy.
"""

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import least_squares

from engines.core.athlete_context import AthleteContext
from engines.core.metric_contracts import annotate_payload
from engines.core.model_safety import finalize_model_metadata
from engines.core.science_contracts import (
    cadence_anchor_metadata,
    vlamax_contract_fields,
    vlamax_limitations,
)
from engines.core.tiers import DEFAULT_DISPLAY_THRESHOLD, should_display
from engines.metabolic.cross_validation_engine import (
    cross_validate_metabolic_profile,
    observed_threshold_power,
)
from engines.metabolic.glycolytic_validation_engine import build_glycolytic_profile
from engines.metabolic.mader_constants import (
    ExpressivenessReport,
    MaderConstants,
    RegularizationWeights,
)
from engines.metabolic.metabolic_calibration import (
    DEFAULT_METABOLIC_CALIBRATION,
    MetabolicCalibration,
)
from engines.metabolic.metabolic_fit_policy import (
    DEFAULT_METABOLIC_FIT_POLICY,
    MetabolicFitPolicy,
)

__all__ = [
    "ExpressivenessReport",
    "MaderConstants",
    "MetabolicCalibration",
    "MetabolicFitPolicy",
    "MetabolicProfiler",
    "RegularizationWeights",
]


logger = logging.getLogger(__name__)


class _MetabolicFitError(RuntimeError):
    """Internal fitting failure whose public representation must stay stable."""


@dataclass
class _PreparedSnapshotInputs:
    """Normalized inputs and audits shared by all fitting stages."""

    mmp: Dict[int, float]
    mmp_quality_audit: Optional[Dict[str, Any]]
    input_audit: Dict[str, Any]
    expressiveness: ExpressivenessReport


@dataclass
class _MetabolicFitContext:
    """Immutable-by-convention numerical inputs for one joint fit."""

    mmp: Dict[int, float]
    all_durs: np.ndarray
    all_pows: np.ndarray
    durs_u: np.ndarray
    pows_u: np.ndarray
    weights: np.ndarray
    sprint_fit_floor_s: float
    vo2_guess: float
    fixed_eta: float
    resolved_measured_lacap: Optional[float]
    fixed_pcr: float
    vla_init: float
    w_grid: np.ndarray
    obs_thr: Optional[float]
    vo2_floor: float
    mlss_ratio_ceiling: float
    input_audit: Dict[str, Any]
    fit_diagnostics: Dict[str, Any]


@dataclass
class _MetabolicFitSelection:
    """Selected optimizer solution and APR metadata."""

    result: Any
    vo2: float
    vlamax: float
    apr_band: Optional[Tuple[float, float, float]]
    apr_gated: bool


@dataclass
class _PreparedSegmentedInputs:
    """Normalized inputs and provenance for the two-stage fit."""

    mmp: Dict[int, float]
    aerobic_mmp: Dict[int, float]
    input_audit: Dict[str, Any]
    aerobic_min_duration_s: float
    aerobic_duration_source: str


@dataclass
class _SegmentedParameterPair:
    """Final parameter pair assembled from the two fitting domains."""

    vo2max: float
    vlamax: float
    fixed_eta: float
    lactate_capacity: float
    context_used: Dict[str, Any]


@dataclass
class _SegmentedDerivedOutputs:
    """Outputs recomputed from the final segmented parameter pair."""

    w_mlss: float
    w_fat: float
    map_w: float
    expressiveness: ExpressivenessReport
    unmasked: Dict[str, Any]
    vo2_out: Optional[float]
    vlamax_out: Optional[float]
    mlss_out: Optional[float]
    mlss_wkg_out: Optional[float]
    fatmax_out: Optional[float]
    cross_validation: Any
    confidence: float
    curve_maximality: Optional[Dict[str, Any]]
    combustion_curve: List[Dict[str, Any]]


class MetabolicProfiler:
    def __init__(
        self,
        weight: float,
        context: Optional[AthleteContext] = None,
        mader_constants: Optional[MaderConstants] = None,
        fit_policy: Optional[MetabolicFitPolicy] = None,
        calibration: Optional[MetabolicCalibration] = None,
    ):
        self.fit_policy = fit_policy if fit_policy is not None else DEFAULT_METABOLIC_FIT_POLICY
        self.calibration = (
            calibration if calibration is not None else DEFAULT_METABOLIC_CALIBRATION
        )
        provided_weight = float(weight)
        self.weight = max(self.fit_policy.minimum_weight_kg, provided_weight)
        self.context = context if context is not None else AthleteContext()
        self.const = mader_constants if mader_constants is not None else MaderConstants()
        self.reg = RegularizationWeights()

        raw_body_fat = getattr(self.context, "body_fat_pct", None)
        effective_fat_pct = float(self.context.effective_body_fat())
        self.body_fat_pct = float(
            np.clip(
                effective_fat_pct,
                self.fit_policy.minimum_body_fat_pct,
                self.fit_policy.maximum_body_fat_pct,
            )
        )
        ffm = self.weight * (1.0 - self.body_fat_pct / 100.0)
        self.active_muscle_mass = ffm * self.context.active_muscle_fraction()
        body_fat_audit = self._numeric_input_audit(
            provided=raw_body_fat,
            used=self.body_fat_pct,
            source="athlete_context",
            minimum=self.fit_policy.minimum_body_fat_pct,
            maximum=self.fit_policy.maximum_body_fat_pct,
        )
        try:
            raw_body_fat_is_valid = raw_body_fat is not None and np.isfinite(float(raw_body_fat))
        except (TypeError, ValueError):
            raw_body_fat_is_valid = False
        if not raw_body_fat_is_valid:
            body_fat_audit.update(
                {
                    "status": "defaulted",
                    "source": "athlete_context_default",
                }
            )
        self._constructor_input_audit = {
            "weight_kg": self._numeric_input_audit(
                provided=provided_weight,
                used=self.weight,
                source="constructor_argument",
                minimum=self.fit_policy.minimum_weight_kg,
                maximum=None,
            ),
            "body_fat_pct": body_fat_audit,
        }

    def _model_configuration_manifest(self) -> Dict[str, Any]:
        """Return the versioned configuration needed to reproduce a snapshot."""
        return {
            "schema_version": "1.0",
            "fit_policy": self.fit_policy.to_dict(),
            "empirical_calibration": self.calibration.to_dict(),
            "mader_constants": self.const.to_dict(),
            "regularization_weights": self.reg.to_dict(),
            "runtime_parameters": {},
        }

    def _record_runtime_parameter(
        self,
        snap: Dict[str, Any],
        *,
        name: str,
        value: Any,
        source: str,
    ) -> Dict[str, Any]:
        """Attach an effective per-call override without mutating shared policy."""
        configuration = snap.setdefault(
            "model_configuration",
            self._model_configuration_manifest(),
        )
        runtime = configuration.setdefault("runtime_parameters", {})
        runtime[name] = {"value": value, "source": source}
        return snap

    @staticmethod
    def _json_safe_input_value(value: Any) -> Any:
        """Return a compact JSON-safe representation for input audit details."""
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, (float, np.floating)):
            numeric = float(value)
            return numeric if np.isfinite(numeric) else repr(numeric)
        try:
            text = repr(value)
        except Exception:
            text = f"<{type(value).__name__}>"
        return text if len(text) <= 120 else f"{text[:117]}..."

    @staticmethod
    def _numeric_input_audit(
        *,
        provided: Any,
        used: Optional[float],
        source: str,
        minimum: Optional[float],
        maximum: Optional[float],
    ) -> Dict[str, Any]:
        """Describe whether a numeric input was accepted, clipped or inferred."""
        if provided is None:
            status = "resolved" if used is not None else "inferred_during_fit"
        else:
            try:
                provided_numeric = float(provided)
            except (TypeError, ValueError):
                provided_numeric = None
            status = (
                "accepted"
                if provided_numeric is not None
                and used is not None
                and np.isfinite(provided_numeric)
                and np.isclose(provided_numeric, used, rtol=0.0, atol=1e-12)
                else "clipped"
            )
        return {
            "provided": MetabolicProfiler._json_safe_input_value(provided),
            "used": MetabolicProfiler._json_safe_input_value(used),
            "source": source,
            "status": status,
            "supported_range": {"min": minimum, "max": maximum},
        }

    def _base_input_audit(
        self,
        *,
        mmp_raw: Any,
        expected_eta: Any,
        measured_lacap: Any,
    ) -> Dict[str, Any]:
        """Create the per-call audit shell before MMP normalization and fitting."""
        provided_anchor_count = len(mmp_raw) if isinstance(mmp_raw, dict) else None
        return {
            "schema_version": "1.0",
            "has_adjustments": any(
                item.get("status") == "clipped"
                for item in self._constructor_input_audit.values()
            ),
            "summary": {
                "clipped_fields": [
                    field
                    for field, item in self._constructor_input_audit.items()
                    if item.get("status") == "clipped"
                ],
                "discarded_mmp_anchors": 0,
                "duplicate_mmp_durations": 0,
                "quality_cleaner_removed_mmp_anchors": 0,
            },
            "athlete": {
                field: dict(item)
                for field, item in self._constructor_input_audit.items()
            },
            "model_inputs": {
                "expected_eta": {
                    "provided": self._json_safe_input_value(expected_eta),
                    "used": None,
                    "source": "argument" if expected_eta is not None else "athlete_context",
                    "status": "pending_resolution",
                    "supported_range": {
                        "min": self.fit_policy.minimum_eta,
                        "max": self.fit_policy.maximum_eta,
                    },
                },
                "measured_lacap_mmol_L": {
                    "provided": self._json_safe_input_value(measured_lacap),
                    "used": None,
                    "source": "argument" if measured_lacap is not None else "model_inferred",
                    "status": (
                        "pending_resolution"
                        if measured_lacap is not None
                        else "inferred_during_fit"
                    ),
                    "supported_range": {
                        "min": self.fit_policy.minimum_lacap_mmol_l,
                        "max": self.fit_policy.maximum_lacap_mmol_l,
                    },
                },
            },
            "mmp": {
                "input_type": type(mmp_raw).__name__,
                "provided_anchor_count": provided_anchor_count,
                "valid_anchor_observations": 0,
                "accepted_anchor_count": 0,
                "used_anchor_count": 0,
                "discarded_anchor_count": 0,
                "duplicate_duration_count": 0,
                "normalized_key_count": 0,
                "duplicate_resolution": "last_value_wins",
                "clean_mmp_first": False,
                "quality_cleaner_removed_anchor_count": 0,
                "discarded_anchors": [],
                "duplicate_durations": [],
                "details_truncated": False,
            },
        }

    @staticmethod
    def _refresh_input_audit_summary(input_audit: Dict[str, Any]) -> None:
        """Synchronize compact summary fields after an audit section changes."""
        clipped_fields: List[str] = []
        for section_name in ("athlete", "model_inputs"):
            for field, item in (input_audit.get(section_name) or {}).items():
                if isinstance(item, dict) and item.get("status") == "clipped":
                    clipped_fields.append(field)
        mmp_audit = input_audit.get("mmp") or {}
        discarded = int(mmp_audit.get("discarded_anchor_count") or 0)
        duplicates = int(mmp_audit.get("duplicate_duration_count") or 0)
        cleaner_removed = int(mmp_audit.get("quality_cleaner_removed_anchor_count") or 0)
        input_audit["summary"] = {
            "clipped_fields": clipped_fields,
            "discarded_mmp_anchors": discarded,
            "duplicate_mmp_durations": duplicates,
            "quality_cleaner_removed_mmp_anchors": cleaner_removed,
        }
        input_audit["has_adjustments"] = bool(
            clipped_fields or discarded or duplicates or cleaner_removed
        )

    @staticmethod
    def _merge_stage_input_audit(
        target: Dict[str, Any],
        stage_audit: Any,
    ) -> Dict[str, Any]:
        """Merge resolved model fields into a full-raw audit without losing MMP provenance."""
        if not isinstance(stage_audit, dict):
            return target
        if isinstance(stage_audit.get("model_inputs"), dict):
            target["model_inputs"] = {
                field: dict(item) if isinstance(item, dict) else item
                for field, item in stage_audit["model_inputs"].items()
            }
        stage_mmp = stage_audit.get("mmp") or {}
        target_mmp = target.get("mmp") or {}
        for field in (
            "clean_mmp_first",
            "quality_cleaner_removed_anchor_count",
            "used_anchor_count",
        ):
            if field in stage_mmp:
                target_mmp[field] = stage_mmp[field]
        target["mmp"] = target_mmp
        MetabolicProfiler._refresh_input_audit_summary(target)
        return target

    @staticmethod
    def _optimizer_diagnostics(result: Any) -> Dict[str, Any]:
        """Return a compact, JSON-safe summary of a SciPy least-squares result."""

        def _finite_float(value: Any) -> Optional[float]:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return None
            return numeric if np.isfinite(numeric) else None

        status = getattr(result, "status", None)
        nfev = getattr(result, "nfev", None)
        njev = getattr(result, "njev", None)
        return {
            "converged": bool(getattr(result, "success", False)),
            "status_code": int(status) if status is not None else None,
            "function_evaluations": int(nfev) if nfev is not None else None,
            "jacobian_evaluations": int(njev) if njev is not None else None,
            "optimality": _finite_float(getattr(result, "optimality", None)),
            "cost": _finite_float(getattr(result, "cost", None)),
        }

    @staticmethod
    def _fit_diagnostic_quality_flags(diagnostics: Any) -> List[str]:
        """Translate joint or segmented fit diagnostics into model quality flags."""
        if not isinstance(diagnostics, dict):
            return []

        flags: set[str] = set()
        selected_optimizer = diagnostics.get("selected_optimizer") or {}
        if selected_optimizer and selected_optimizer.get("converged") is False:
            flags.add("selected_optimizer_not_converged")

        if any(
            int(diagnostics.get(field) or 0) > 0
            for field in (
                "exception_starts",
                "invalid_result_starts",
                "nonconverged_starts",
            )
        ):
            flags.add("multistart_partial_failures")

        for stage in ("aerobic_stage", "full_curve_stage"):
            flags.update(MetabolicProfiler._fit_diagnostic_quality_flags(diagnostics.get(stage)))
        return sorted(flags)

    def _coerce_mmp_dict_with_audit(
        self,
        mmp: Dict[Any, Any],
        input_audit: Optional[Dict[str, Any]] = None,
    ) -> Dict[int, float]:
        """Normalize MMP anchors while recording discarded and duplicate inputs."""
        if not isinstance(mmp, dict):
            raise TypeError("MMP input must be a dictionary")

        out: Dict[int, float] = {}
        source_keys: Dict[int, str] = {}
        valid_observations = 0
        normalized_key_count = 0
        discarded: List[Dict[str, Any]] = []
        duplicates: List[Dict[str, Any]] = []
        detail_limit = self.fit_policy.input_audit_detail_limit

        def _append_limited(target: List[Dict[str, Any]], detail: Dict[str, Any]) -> None:
            if len(target) < detail_limit:
                target.append(detail)

        for k, w in mmp.items():
            key_repr = str(self._json_safe_input_value(k))
            if w is None:
                _append_limited(
                    discarded,
                    {"key": key_repr, "provided_power": None, "reason": "missing_power"},
                )
                continue
            try:
                wf = float(w)
            except (TypeError, ValueError):
                _append_limited(
                    discarded,
                    {
                        "key": key_repr,
                        "provided_power": self._json_safe_input_value(w),
                        "reason": "invalid_power",
                    },
                )
                continue
            if not np.isfinite(wf) or wf <= 0.0:
                _append_limited(
                    discarded,
                    {
                        "key": key_repr,
                        "provided_power": self._json_safe_input_value(w),
                        "reason": "non_positive_or_non_finite_power",
                    },
                )
                continue

            try:
                k_str = str(k).strip().lower()
                if k_str.endswith("s"):
                    sec = int(float(k_str[:-1]))
                elif k_str.endswith("m"):
                    sec = int(float(k_str[:-1]) * 60.0)
                else:
                    sec = int(float(k_str))
            except (TypeError, ValueError):
                _append_limited(
                    discarded,
                    {
                        "key": key_repr,
                        "provided_power": self._json_safe_input_value(w),
                        "reason": "invalid_duration",
                    },
                )
                continue

            if sec <= 0:
                _append_limited(
                    discarded,
                    {
                        "key": key_repr,
                        "provided_power": self._json_safe_input_value(w),
                        "normalized_duration_s": sec,
                        "reason": "non_positive_duration",
                    },
                )
                continue

            valid_observations += 1
            if not (
                isinstance(k, int)
                and not isinstance(k, bool)
                and int(k) == sec
            ):
                normalized_key_count += 1

            if sec in out:
                _append_limited(
                    duplicates,
                    {
                        "duration_s": sec,
                        "previous_key": source_keys.get(sec),
                        "previous_power_w": out[sec],
                        "replacement_key": key_repr,
                        "replacement_power_w": wf,
                        "resolution": "last_value_wins",
                    },
                )
            out[sec] = wf
            source_keys[sec] = key_repr

        if input_audit is not None:
            mmp_audit = input_audit["mmp"]
            mmp_audit.update(
                {
                    "valid_anchor_observations": valid_observations,
                    "accepted_anchor_count": len(out),
                    "used_anchor_count": len(out),
                    "discarded_anchor_count": len(mmp) - valid_observations,
                    "duplicate_duration_count": valid_observations - len(out),
                    "normalized_key_count": normalized_key_count,
                    "discarded_anchors": discarded,
                    "duplicate_durations": duplicates,
                    "details_truncated": (
                        (len(mmp) - valid_observations) > len(discarded)
                        or (valid_observations - len(out)) > len(duplicates)
                    ),
                }
            )
            self._refresh_input_audit_summary(input_audit)
        return dict(sorted(out.items()))

    def _coerce_mmp_dict(self, mmp: Dict[Any, Any]) -> Dict[int, float]:
        return self._coerce_mmp_dict_with_audit(mmp)

    def _pcr_prior_watts(self) -> float:
        return float(np.clip(
            self.active_muscle_mass * self.const.pcr_multiplier,
            self.const.pcr_prior_min,
            self.const.pcr_prior_max
        ))

    def _metabolic_rates(self, w: np.ndarray, vo2: float, vla: float, eta_base: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        coeff_w_to_vo2 = (
            self.calibration.watts_to_vo2_coefficient
            * (self.calibration.reference_efficiency / eta_base)
        )
        vo2_req = self.const.vo2_basale + coeff_w_to_vo2 * (w / self.weight)
        vo2_act = np.minimum(vo2_req, vo2 - self.const.eps)
        denom = np.maximum(self.const.eps, vo2 - vo2_act)
        adp = np.sqrt((self.const.ks1 * vo2_act) / denom)
        vla_prod = vla / (1.0 + (self.const.ks2 / (adp ** 3)))
        vla_elim = (self.const.equiv_o2_la * (vo2_act - self.const.vo2_basale)) / (self.const.vol_rel * 60.0)
        return vo2_act, vla_prod, vla_elim

    def _lactate_kin_tau(self, vo2: float, vla: float) -> float:
        floor = self.context.tau_base_floor()
        tau_base = floor + np.clip(
            self.calibration.tau_vo2_anchor - vo2,
            0.0,
            self.calibration.tau_vo2_span,
        ) * self.calibration.tau_vo2_slope
        return float(
            np.clip(
                tau_base
                + np.clip(
                    vla - self.calibration.tau_vlamax_anchor,
                    0.0,
                    self.calibration.tau_vlamax_span,
                )
                * self.calibration.tau_vlamax_slope,
                self.calibration.tau_min_s,
                self.calibration.tau_max_s,
            )
        )

    def _cap_factor(self, seconds: float) -> float:
        return float(
            self.calibration.cap_factor_base
            + self.calibration.cap_factor_amplitude
            * np.exp(-seconds / self.calibration.cap_factor_decay_s)
        )

    def _solve_root_last_crossing(self, diff: np.ndarray, w: np.ndarray) -> float:
        if diff.size < 2:
            return float(w[0]) if w.size else 0.0
        idxs = np.where(np.diff(np.sign(diff)))[0]
        if idxs.size:
            idx = int(idxs[-1])
            d1, d2 = float(diff[idx]), float(diff[idx + 1])
            denom = d2 - d1
            if abs(denom) < 1e-9:
                return (float(w[idx]) + float(w[idx + 1])) / 2.0
            return float(w[idx]) - d1 * (float(w[idx + 1]) - float(w[idx])) / denom
        if np.all(diff > 0):
            return float(w[0])
        if np.all(diff < 0):
            return float(w[-1])
        return float(w[int(np.argmin(np.abs(diff)))])

    def _map_estimate(self, vo2: float, eta_base: float) -> float:
        return float(
            np.clip(
                (vo2 - self.const.vo2_basale)
                * self.weight
                / self.calibration.watts_to_vo2_coefficient
                * (eta_base / self.calibration.reference_efficiency),
                self.calibration.map_power_min_w,
                self.calibration.map_power_max_w,
            )
        )

    def _apr_vlamax_band(self, mmp: Dict[int, float], map_provisional: float) -> Optional[Tuple[float, float, float]]:
        """
        Expected VLamax band from the Anaerobic Power Reserve.

        APR = P_sprint - MAP  is the purely-anaerobic power window above the
        maximal aerobic power. It and VLamax are different expressions of the
        same axis — glycolytic/alactic capacity as *power* — so a large APR is
        physiologically incompatible with a low VLamax, and vice versa. We use
        the APR (a directly observed quantity from the sprint anchor) to bound
        which VLamax basin the fit is allowed to settle in, breaking the
        multiple-minima ambiguity that makes the joint fit jump between a
        "diesel" and a "sprinter" solution on the same curve.

        The mapping is expressed against the APR-to-MAP ratio (dimensionless),
        which normalises for athlete size:

            apr_ratio = (P_sprint - MAP) / MAP

        Calibration anchors (broadly consistent with Sanders/Heijboer-style
        APR work and with Mader VLamax ranges):
            apr_ratio <= 0.8   -> diesel        VLamax ~ [0.10, 0.40]
            apr_ratio  ~ 1.5   -> all-rounder   VLamax ~ [0.35, 0.60]
            apr_ratio >= 2.2   -> explosive      VLamax ~ [0.55, 1.10]

        Returns (vla_low, vla_high, apr_ratio) or None if no sprint anchor.
        """
        p_sprint = mmp.get(1) or mmp.get(5) or mmp.get(10)
        if not p_sprint or map_provisional <= 0:
            return None
        apr_ratio = (float(p_sprint) - map_provisional) / map_provisional
        # Piecewise-linear band: a gentle floor (rules out implausibly high
        # VLamax only weakly at the bottom) and a firm ceiling (a low APR
        # makes a high VLamax physiologically impossible). This is a CEILING
        # constraint by design — it excludes the impossible corner (high
        # VLamax + low sprint) without forcing a value on genuine diesels,
        # who can sit near the floor even when a virtual platform sprint inflates APR.
        apr_excess = max(0.0, apr_ratio - self.calibration.apr_ratio_anchor)
        vla_low = float(
            np.clip(
                self.calibration.apr_vlamax_low_intercept
                + self.calibration.apr_vlamax_low_slope * apr_excess,
                *self.calibration.apr_vlamax_low_bounds,
            )
        )
        vla_high = float(
            np.clip(
                self.calibration.apr_vlamax_high_intercept
                + self.calibration.apr_vlamax_high_slope * apr_excess,
                *self.calibration.apr_vlamax_high_bounds,
            )
        )
        if vla_high <= vla_low:
            vla_high = vla_low + self.calibration.apr_vlamax_minimum_band_width
        return (vla_low, vla_high, apr_ratio)

    def _pred_power(self, t: float, la_cap: float, tau: float, map_est: float, w_grid: np.ndarray, vo2_act_grid: np.ndarray, net_grid: np.ndarray) -> float:
        cap_mask = w_grid <= (map_est * self._cap_factor(t))
        if np.count_nonzero(cap_mask) < self.fit_policy.minimum_prediction_grid_points:
            cap_mask = np.ones_like(w_grid, dtype=bool)
        w, net_w, vo2_gap = w_grid[cap_mask], net_grid[cap_mask], vo2_act_grid[cap_mask] - self.const.vo2_basale

        vla_e_ss = (vo2_gap * self.const.equiv_o2_la) / (self.const.vol_rel * 60.0)
        la_kin_tax = vla_e_ss * tau * (1.0 - np.exp(-t / tau)) / t
        target = np.maximum(self.const.eps, (la_cap / t) - la_kin_tax)
        return self._solve_root_last_crossing(net_w - target, w)

    def _compute_grid_state(self, vo2: float, vla: float, eta_base: float, w_grid: np.ndarray):
        tau, map_est = self._lactate_kin_tau(vo2, vla), self._map_estimate(vo2, eta_base)
        vo2_act, vla_p, vla_e = self._metabolic_rates(w_grid, vo2, vla, eta_base)
        z = self.const.softplus_k * (vla_p - vla_e)
        net = np.maximum(self.const.eps, (np.log1p(np.exp(-np.abs(z))) + np.maximum(z, 0.0)) / self.const.softplus_k)
        return tau, map_est, vo2_act, net

    def _calculate_curves(self, vo2: float, vla: float, eta_base: float):
        w: np.ndarray = np.arange(
            self.calibration.curve_power_min_w,
            max(
                self.calibration.curve_power_floor_max_w,
                self.weight * self.calibration.curve_power_per_kg_max,
            )
            + self.calibration.curve_power_step_w * 2.0,
            self.calibration.curve_power_step_w,
            dtype=float,
        )
        vo2_act, p, e = self._metabolic_rates(w, vo2, vla, eta_base)

        valid = vo2_act < (vo2 - self.calibration.curve_vo2_margin)
        w, p, e, vo2_act = w[valid], p[valid], e[valid], vo2_act[valid]

        # MLSS = Maximal Lactate Steady State: the highest power at which
        # blood lactate stabilizes at an elevated-but-constant level (~OBLA).
        # This is NOT the point where net production first crosses zero —
        # that crossing is LT1 (the aerobic threshold), where lactate just
        # begins to rise above baseline. Using net=0 systematically placed
        # MLSS ~15-25% below the athlete's real sustained threshold power
        # (e.g. a rider holding 255 W for 60 min was assigned MLSS≈210 W).
        #
        # In Mader's framework the maximal steady state sits where net
        # accumulation reaches the small positive rate the body can still
        # clear at constant elevated lactate. Calibrated against real
        # sustained power across 4 independent athletes, that rate is ~5%
        # of peak production — landing MLSS inside the physiological band
        # [60-min power, 20-min power] for every athlete tested.
        net_prod = p - e
        mlss_net_threshold = self.const.mlss_net_frac * float(np.max(p)) if p.size else 0.0
        _above = np.where(net_prod >= mlss_net_threshold)[0]
        w_mlss = float(w[_above[0]]) if _above.size else float(w[int(np.argmin(np.abs(net_prod)))])
        deficit = np.maximum(0.0, e - p)
        mx = float(np.max(deficit))
        w_fat = (
            float(
                np.mean(
                    w[deficit >= self.calibration.fatmax_peak_fraction * mx]
                )
            )
            if mx > 0
            else float(w[int(np.argmax(deficit))])
        )

        fat_coef = self.context.fat_oxidation_coefficient()
        cho_coef = self.context.cho_oxidation_coefficient()
        fat_gh = (deficit * self.const.vol_rel / self.const.equiv_o2_la * self.weight / 1000.0) * 60.0 * fat_coef
        cho_gh = ((np.minimum(p, e) * self.const.vol_rel / self.const.equiv_o2_la * self.weight / 1000.0) * 60.0 * cho_coef) + \
                 ((np.maximum(0.0, p - e) * self.const.vol_rel / self.const.equiv_o2_la * self.weight / 1000.0) * 60.0 * cho_coef)

        return w_mlss, w_fat, w, fat_gh, cho_gh

    def _generate_zones(self, w_mlss: float, map_w: float) -> List[Dict[str, Any]]:
        return [
            {"name": "Z1 - Recovery", "minWatt": 0, "maxWatt": round(w_mlss * 0.55)},
            {"name": "Z2 - Endurance", "minWatt": round(w_mlss * 0.55) + 1, "maxWatt": round(w_mlss * 0.75)},
            {"name": "Z3 - Tempo", "minWatt": round(w_mlss * 0.75) + 1, "maxWatt": round(w_mlss * 0.90)},
            {"name": "Z4 - Threshold (MLSS)", "minWatt": round(w_mlss * 0.90) + 1, "maxWatt": round(w_mlss * 1.05)},
            {"name": "Z5 - VO2max", "minWatt": round(w_mlss * 1.05) + 1, "maxWatt": round(map_w)},
        ]

    def _classify_metabolic_phenotype(self, vlamax: float) -> dict:
        endurance_max, allrounder_max = self.context.phenotype_thresholds()
        if vlamax < endurance_max:
            return {"category": "Endurance (Diesel)", "level": "Low", "description": "Ideal for pure endurance. Low carbohydrate demand, excellent efficiency."}
        elif vlamax <= allrounder_max:
            return {"category": "All-Rounder (Passista)", "level": "Moderate", "description": "Balanced profile. Strong endurance and good ability to handle pace changes."}
        else:
            return {"category": "Sprinter (Explosive)", "level": "High", "description": "Glycolytic engine. Excellent explosive power, high carbohydrate demand."}

    def generate_metabolic_snapshot(
        self,
        mmp_raw: Dict[Any, Any],
        expected_eta: Optional[float] = None,
        measured_lacap: Optional[float] = None,
        mmp_samples: Optional[List[Dict[str, Any]]] = None,
        clean_mmp_first: bool = False,
        effective_cadence_rpm: Optional[float] = None,
        cadence_anchor_status: str = "unknown",
    ) -> Dict[str, Any]:
        """Public, exception-safe entry point for metabolic snapshot generation."""
        fallback_input_audit = self._base_input_audit(
            mmp_raw=mmp_raw,
            expected_eta=expected_eta,
            measured_lacap=measured_lacap,
        )
        try:
            return self._generate_metabolic_snapshot_impl(
                mmp_raw,
                expected_eta=expected_eta,
                measured_lacap=measured_lacap,
                mmp_samples=mmp_samples,
                clean_mmp_first=clean_mmp_first,
                effective_cadence_rpm=effective_cadence_rpm,
                cadence_anchor_status=cadence_anchor_status,
            )
        except Exception:
            input_anchor_count = len(mmp_raw) if isinstance(mmp_raw, dict) else None
            logger.exception(
                "metabolic_snapshot_input_processing_failed",
                extra={
                    "input_type": type(mmp_raw).__name__,
                    "input_anchor_count": input_anchor_count,
                    "clean_mmp_first": clean_mmp_first,
                },
            )
            return self._finalize_snapshot(
                {
                    "status": "error",
                    "error_code": "metabolic_input_processing_failed",
                    "message": "Metabolic snapshot input could not be processed.",
                    "input_audit": fallback_input_audit,
                    "fit_diagnostics": {
                        "fit_method": "joint",
                        "input_anchor_count": input_anchor_count,
                        "attempted_starts": 0,
                        "candidate_starts": 0,
                        "converged_starts": 0,
                        "nonconverged_starts": 0,
                        "exception_starts": 0,
                        "invalid_result_starts": 0,
                    },
                },
                None,
                effective_cadence_rpm=effective_cadence_rpm,
                cadence_anchor_status=cadence_anchor_status,
            )

    def _prepare_snapshot_inputs(
        self,
        mmp_raw: Dict[Any, Any],
        *,
        expected_eta: Optional[float],
        measured_lacap: Optional[float],
        mmp_samples: Optional[List[Dict[str, Any]]],
        clean_mmp_first: bool,
    ) -> _PreparedSnapshotInputs:
        """Normalize the MMP and build the expressiveness and input audits."""
        mmp_quality_audit: Optional[Dict[str, Any]] = None
        input_audit = self._base_input_audit(
            mmp_raw=mmp_raw,
            expected_eta=expected_eta,
            measured_lacap=measured_lacap,
        )
        normalized_mmp = self._coerce_mmp_dict_with_audit(mmp_raw, input_audit)

        if clean_mmp_first:
            # Local import to avoid a hard dependency when cleaning is disabled.
            from engines.performance.mmp_quality import analyze_mmp_quality, clean_mmp

            cleaned_dict, mmp_quality_audit = clean_mmp(mmp_raw, mmp_samples)
            mmp = cleaned_dict
            input_audit["mmp"]["clean_mmp_first"] = True
            input_audit["mmp"]["used_anchor_count"] = len(mmp)
            input_audit["mmp"]["quality_cleaner_removed_anchor_count"] = max(
                0,
                len(normalized_mmp) - len(mmp),
            )
            full_report = analyze_mmp_quality(mmp_raw, mmp_samples)
            mmp_quality_audit["analysis"] = full_report.to_dict()
        else:
            mmp = normalized_mmp
            input_audit["mmp"]["clean_mmp_first"] = False

        self._refresh_input_audit_summary(input_audit)
        return _PreparedSnapshotInputs(
            mmp=mmp,
            mmp_quality_audit=mmp_quality_audit,
            input_audit=input_audit,
            expressiveness=ExpressivenessReport.from_mmp(mmp),
        )

    def _build_fit_context(
        self,
        prepared: _PreparedSnapshotInputs,
        *,
        expected_eta: Optional[float],
        measured_lacap: Optional[float],
    ) -> _MetabolicFitContext:
        """Resolve arrays, weights, bounds and observed anchors for one fit."""
        mmp = prepared.mmp
        input_audit = prepared.input_audit
        sprint_fit_floor_s = self.fit_policy.sprint_fit_floor_s
        all_durs = np.array(list(mmp.keys()), dtype=float)
        all_pows = np.array(list(mmp.values()), dtype=float)
        fit_mask = all_durs >= sprint_fit_floor_s
        if int(np.count_nonzero(fit_mask)) < self.fit_policy.minimum_fit_anchors:
            fit_mask = np.ones_like(all_durs, dtype=bool)
            sprint_fit_floor_s = 0.0
        durs_u = all_durs[fit_mask]
        pows_u = all_pows[fit_mask]

        logt = np.log(np.maximum(durs_u, 1.0))
        weights = self.calibration.weight_baseline + self.calibration.weight_peak_amplitude * (
            np.exp(
                -0.5
                * (
                    (logt - np.log(self.calibration.weight_peak_duration_s))
                    / self.calibration.weight_log_sigma
                )
                ** 2
            )
            * np.clip(
                durs_u / self.calibration.weight_short_reference_s,
                self.calibration.weight_short_min,
                1.0,
            )
            * np.clip(
                self.calibration.weight_long_reference_s
                / np.maximum(durs_u, self.calibration.weight_long_reference_s),
                self.calibration.weight_long_min,
                1.0,
            )
        )
        weights /= np.max(weights)

        vo2_guess = float(
            np.clip(
                max(
                    self.calibration.vo2_guess_floor,
                    min(
                        self.calibration.vo2_guess_ceiling,
                        (pows_u[int(np.argmax(weights))] / self.weight)
                        * self.calibration.vo2_guess_power_multiplier,
                    ),
                ),
                self.fit_policy.optimizer_vo2_min,
                self.fit_policy.optimizer_vo2_max,
            )
        )

        eta_provided = expected_eta
        eta_resolved = (
            float(self.context.expected_eta())
            if expected_eta is None
            else float(expected_eta)
        )
        fixed_eta = float(
            np.clip(
                eta_resolved,
                self.fit_policy.minimum_eta,
                self.fit_policy.maximum_eta,
            )
        )
        input_audit["model_inputs"]["expected_eta"] = self._numeric_input_audit(
            provided=eta_provided,
            used=fixed_eta,
            source="athlete_context" if eta_provided is None else "argument",
            minimum=self.fit_policy.minimum_eta,
            maximum=self.fit_policy.maximum_eta,
        )

        resolved_measured_lacap: Optional[float] = None
        if measured_lacap is not None:
            measured_lacap_numeric = float(measured_lacap)
            resolved_measured_lacap = float(
                np.clip(
                    measured_lacap_numeric,
                    self.fit_policy.minimum_lacap_mmol_l,
                    self.fit_policy.maximum_lacap_mmol_l,
                )
            )
            input_audit["model_inputs"]["measured_lacap_mmol_L"] = (
                self._numeric_input_audit(
                    provided=measured_lacap_numeric,
                    used=resolved_measured_lacap,
                    source="argument",
                    minimum=self.fit_policy.minimum_lacap_mmol_l,
                    maximum=self.fit_policy.maximum_lacap_mmol_l,
                )
            )
        self._refresh_input_audit_summary(input_audit)

        fixed_pcr = self._pcr_prior_watts()
        vla_init = self.context.vlamax_initial_guess()
        w_grid: np.ndarray = np.arange(
            self.const.w_min,
            max(
                self.calibration.fit_grid_floor_max_w,
                self.weight * self.calibration.fit_grid_power_per_kg_max,
            )
            + self.const.w_step,
            self.const.w_step,
            dtype=float,
        )

        mmp_for_obs = {int(d): float(p) for d, p in zip(durs_u, pows_u) if p > 0}
        obs_thr = observed_threshold_power(mmp_for_obs)
        coeff_w_to_vo2 = (
            self.calibration.watts_to_vo2_coefficient
            * (self.calibration.reference_efficiency / fixed_eta)
        )
        if obs_thr is not None and obs_thr > 0:
            vo2_floor = (
                self.const.vo2_basale
                + coeff_w_to_vo2
                * (obs_thr / self.weight)
                * self.calibration.observed_threshold_vo2_margin
            )
        else:
            vo2_floor = 0.0

        fit_diagnostics: Dict[str, Any] = {
            "fit_method": "joint",
            "input_anchor_count": len(mmp),
            "fit_anchor_count": int(durs_u.size),
            "sprint_fit_floor_s": sprint_fit_floor_s,
            "attempted_starts": 0,
            "candidate_starts": 0,
            "converged_starts": 0,
            "nonconverged_starts": 0,
            "exception_starts": 0,
            "invalid_result_starts": 0,
            "apr_gate_applied": False,
        }
        return _MetabolicFitContext(
            mmp=mmp,
            all_durs=all_durs,
            all_pows=all_pows,
            durs_u=durs_u,
            pows_u=pows_u,
            weights=weights,
            sprint_fit_floor_s=sprint_fit_floor_s,
            vo2_guess=vo2_guess,
            fixed_eta=fixed_eta,
            resolved_measured_lacap=resolved_measured_lacap,
            fixed_pcr=fixed_pcr,
            vla_init=vla_init,
            w_grid=w_grid,
            obs_thr=obs_thr,
            vo2_floor=vo2_floor,
            mlss_ratio_ceiling=self.calibration.mlss_observed_ratio_ceiling,
            input_audit=input_audit,
            fit_diagnostics=fit_diagnostics,
        )

    def _resolve_lacap(
        self,
        vlamax: float,
        measured_lacap: Optional[float],
    ) -> float:
        """Resolve inferred or measured lactate capacity with policy bounds."""
        if measured_lacap is not None:
            return measured_lacap
        return float(
            np.clip(
                self.calibration.lacap_intercept
                + (vlamax - self.calibration.lacap_vlamax_anchor)
                * self.calibration.lacap_vlamax_slope,
                self.fit_policy.minimum_lacap_mmol_l,
                self.fit_policy.maximum_lacap_mmol_l,
            )
        )

    def _predict_fit_powers(
        self,
        context: _MetabolicFitContext,
        *,
        vo2: float,
        vlamax: float,
        lacap: float,
    ) -> np.ndarray:
        """Predict powers at the fit durations using the current model state."""
        tau, map_est, vo2_act, net = self._compute_grid_state(
            vo2,
            vlamax,
            context.fixed_eta,
            context.w_grid,
        )
        return np.array(
            [
                self._pred_power(
                    t,
                    lacap,
                    tau,
                    map_est,
                    context.w_grid,
                    vo2_act,
                    net,
                )
                for t in context.durs_u
            ]
        ) + (
            context.fixed_pcr
            * np.exp(
                -np.maximum(
                    0.0,
                    context.durs_u - self.calibration.pcr_decay_start_s,
                )
                / self.calibration.pcr_decay_tau_s
            )
        )

    def _fit_residuals(
        self,
        x: np.ndarray,
        context: _MetabolicFitContext,
    ) -> np.ndarray:
        """Return weighted residuals plus fixed-length physiological penalties."""
        vo2, vlamax = map(float, x)
        lacap = self._resolve_lacap(vlamax, context.resolved_measured_lacap)
        preds = self._predict_fit_powers(
            context,
            vo2=vo2,
            vlamax=vlamax,
            lacap=lacap,
        )
        resid = (preds - context.pows_u) * context.weights
        vo2_floor_pen = (
            (context.vo2_floor - vo2) * self.calibration.vo2_floor_penalty_scale
            if context.vo2_floor > 0.0 and vo2 < context.vo2_floor
            else 0.0
        )

        mlss_ceiling_pen = 0.0
        if context.obs_thr is not None and context.obs_thr > 0:
            w_mlss_pred, _, _, _, _ = self._calculate_curves(
                vo2,
                vlamax,
                context.fixed_eta,
            )
            ratio = float(w_mlss_pred) / context.obs_thr
            if ratio > context.mlss_ratio_ceiling:
                mlss_ceiling_pen = (
                    (ratio - context.mlss_ratio_ceiling)
                    * self.calibration.mlss_ceiling_penalty_scale
                )

        short_mae_pen = 0.0
        short_mask = context.durs_u <= self.calibration.short_mae_duration_s
        if np.any(short_mask):
            short_mae_pen = (
                float(np.mean(np.abs(preds[short_mask] - context.pows_u[short_mask])))
                * self.reg.short_mae_scale
            )

        expected_vo2 = (
            self.const.vo2_basale
            + (
                self.calibration.watts_to_vo2_coefficient
                * (self.calibration.reference_efficiency / context.fixed_eta)
            )
            * (context.pows_u[int(np.argmax(context.weights))] / self.weight)
        )
        reg = [
            (vo2 - context.vo2_guess) * self.reg.vo2_vs_guess,
            (vo2 - expected_vo2) * self.reg.vo2_vs_expected_heuristic,
            vo2_floor_pen,
            mlss_ceiling_pen,
            short_mae_pen,
        ]
        return np.concatenate([resid, np.array(reg)])

    def _fit_basin_score(
        self,
        *,
        cost: float,
        vo2: float,
        vlamax: float,
        context: _MetabolicFitContext,
        apr_band: Optional[Tuple[float, float, float]],
    ) -> float:
        """Score an optimizer basin against observed threshold and APR anchors."""
        penalty = 0.0
        if context.obs_thr is not None and context.obs_thr > 0:
            w_mlss, _, _, _, _ = self._calculate_curves(
                vo2,
                vlamax,
                context.fixed_eta,
            )
            mlss_err = abs(float(w_mlss) - context.obs_thr) / context.obs_thr
            penalty += (mlss_err ** 2) * self.calibration.mlss_basin_penalty_scale
        if apr_band is not None:
            vla_centre = 0.5 * (apr_band[0] + apr_band[1])
            penalty += (
                (vlamax - vla_centre) ** 2
                * self.calibration.apr_centre_tiebreak_scale
            )
        return cost + penalty

    def _run_multistart_fit(
        self,
        context: _MetabolicFitContext,
    ) -> _MetabolicFitSelection:
        """Run deterministic multi-start optimization and select one basin."""
        map_provisional = self._map_estimate(context.vo2_guess, context.fixed_eta)
        apr_band = self._apr_vlamax_band(
            {
                int(d): float(p)
                for d, p in zip(context.all_durs, context.all_pows)
                if p > 0
            },
            map_provisional,
        )

        vla_starts = list(self.calibration.vlamax_starts)
        if apr_band is not None:
            vla_lo, vla_hi, _ = apr_band
            vla_starts.append(
                float(
                    np.clip(
                        (vla_lo + vla_hi) / 2.0,
                        self.calibration.apr_midpoint_start_min,
                        self.calibration.apr_midpoint_start_max,
                    )
                )
            )
        vo2_anchor = float(
            np.clip(
                context.vo2_guess,
                self.fit_policy.optimizer_vo2_min,
                self.fit_policy.optimizer_vo2_max,
            )
        )
        vo2_floor_start = float(
            np.clip(
                max(context.vo2_floor, context.vo2_guess)
                + self.calibration.vo2_floor_start_offset,
                self.fit_policy.optimizer_vo2_min,
                self.fit_policy.optimizer_vo2_max,
            )
        )
        vo2_starts = sorted(
            set(
                [
                    vo2_anchor,
                    vo2_floor_start,
                    float(
                        np.clip(
                            vo2_anchor + self.calibration.vo2_lower_start_offset,
                            self.fit_policy.optimizer_vo2_min,
                            self.fit_policy.optimizer_vo2_max,
                        )
                    ),
                    float(
                        np.clip(
                            vo2_anchor + self.calibration.vo2_upper_start_offset,
                            self.fit_policy.optimizer_vo2_min,
                            self.fit_policy.optimizer_vo2_max,
                        )
                    ),
                ]
            )
        )
        start_points = [
            [vo2_start, vlamax_start]
            for vo2_start in vo2_starts
            for vlamax_start in vla_starts
        ]
        diagnostics = context.fit_diagnostics
        diagnostics["attempted_starts"] = len(start_points)
        candidates = []

        for start in start_points:
            clipped_start = [
                float(
                    np.clip(
                        start[0],
                        self.fit_policy.optimizer_vo2_min,
                        self.fit_policy.optimizer_vo2_max,
                    )
                ),
                float(
                    np.clip(
                        start[1],
                        self.fit_policy.optimizer_vlamax_min,
                        self.fit_policy.optimizer_vlamax_max,
                    )
                ),
            ]
            try:
                result = least_squares(
                    lambda x: self._fit_residuals(x, context),
                    clipped_start,
                    bounds=(
                        [
                            self.fit_policy.optimizer_vo2_min,
                            self.fit_policy.optimizer_vlamax_min,
                        ],
                        [
                            self.fit_policy.optimizer_vo2_max,
                            self.fit_policy.optimizer_vlamax_max,
                        ],
                    ),
                    loss="soft_l1",
                )
            except Exception as exc:
                diagnostics["exception_starts"] += 1
                logger.debug(
                    "metabolic_fit_start_failed",
                    exc_info=True,
                    extra={
                        "fit_start_vo2": clipped_start[0],
                        "fit_start_vlamax": clipped_start[1],
                        "exception_type": type(exc).__name__,
                    },
                )
                continue

            try:
                result_x = np.asarray(getattr(result, "x", []), dtype=float)
                result_fun = np.asarray(getattr(result, "fun", []), dtype=float)
            except (TypeError, ValueError):
                diagnostics["invalid_result_starts"] += 1
                logger.warning(
                    "metabolic_fit_start_returned_unreadable_result",
                    extra={
                        "fit_start_vo2": clipped_start[0],
                        "fit_start_vlamax": clipped_start[1],
                    },
                )
                continue
            if (
                result_x.size != 2
                or result_fun.size == 0
                or not np.all(np.isfinite(result_x))
                or not np.all(np.isfinite(result_fun))
            ):
                diagnostics["invalid_result_starts"] += 1
                logger.warning(
                    "metabolic_fit_start_returned_invalid_result",
                    extra={
                        "fit_start_vo2": clipped_start[0],
                        "fit_start_vlamax": clipped_start[1],
                    },
                )
                continue

            if bool(getattr(result, "success", False)):
                diagnostics["converged_starts"] += 1
            else:
                diagnostics["nonconverged_starts"] += 1
            cost = float(np.sum(result.fun ** 2))
            candidates.append(
                (cost, float(result.x[1]), float(result.x[0]), result, clipped_start)
            )

        diagnostics["candidate_starts"] = len(candidates)
        if (
            diagnostics["exception_starts"]
            or diagnostics["invalid_result_starts"]
            or diagnostics["nonconverged_starts"]
        ):
            logger.warning(
                "metabolic_multistart_fit_completed_with_partial_failures",
                extra={
                    "attempted_starts": diagnostics["attempted_starts"],
                    "candidate_starts": diagnostics["candidate_starts"],
                    "converged_starts": diagnostics["converged_starts"],
                    "nonconverged_starts": diagnostics["nonconverged_starts"],
                    "exception_starts": diagnostics["exception_starts"],
                    "invalid_result_starts": diagnostics["invalid_result_starts"],
                },
            )
        if not candidates:
            raise _MetabolicFitError("No finite optimizer candidates were produced.")

        apr_gated = False
        pool = candidates
        if apr_band is not None:
            vla_lo, vla_hi, _ = apr_band
            in_band = [item for item in candidates if vla_lo <= item[1] <= vla_hi]
            if in_band:
                pool = in_band
                apr_gated = True

        best_cost, best_vla, best_vo2, best_result, best_start = min(
            pool,
            key=lambda item: self._fit_basin_score(
                cost=item[0],
                vo2=item[2],
                vlamax=item[1],
                context=context,
                apr_band=apr_band,
            ),
        )
        diagnostics.update(
            {
                "apr_gate_applied": apr_gated,
                "candidate_pool_size": len(pool),
                "selected_start": [round(float(value), 4) for value in best_start],
                "selected_residual_cost": round(best_cost, 6),
                "selected_basin_score": round(
                    self._fit_basin_score(
                        cost=best_cost,
                        vo2=best_vo2,
                        vlamax=best_vla,
                        context=context,
                        apr_band=apr_band,
                    ),
                    6,
                ),
                "selected_optimizer": self._optimizer_diagnostics(best_result),
            }
        )
        return _MetabolicFitSelection(
            result=best_result,
            vo2=float(best_result.x[0]),
            vlamax=float(best_result.x[1]),
            apr_band=apr_band,
            apr_gated=apr_gated,
        )

    def _build_success_snapshot(
        self,
        prepared: _PreparedSnapshotInputs,
        context: _MetabolicFitContext,
        selection: _MetabolicFitSelection,
    ) -> Dict[str, Any]:
        """Derive, validate and serialize outputs from the selected fit."""
        mmp = prepared.mmp
        expressiveness = prepared.expressiveness
        input_audit = prepared.input_audit
        vo2 = selection.vo2
        vlamax = selection.vlamax
        final_lacap = self._resolve_lacap(
            vlamax,
            context.resolved_measured_lacap,
        )
        if context.resolved_measured_lacap is None:
            input_audit["model_inputs"]["measured_lacap_mmol_L"].update(
                {
                    "used": round(final_lacap, 6),
                    "status": "inferred_during_fit",
                }
            )
        self._refresh_input_audit_summary(input_audit)

        w_mlss, w_fat, w_plot, fat_gh, cho_gh = self._calculate_curves(
            vo2,
            vlamax,
            context.fixed_eta,
        )
        map_w = self._map_estimate(vo2, context.fixed_eta)
        preds = self._predict_fit_powers(
            context,
            vo2=vo2,
            vlamax=vlamax,
            lacap=final_lacap,
        )
        rel_err = float(np.sqrt(np.mean((preds - context.pows_u) ** 2))) / max(
            float(np.mean(context.pows_u)),
            1.0,
        )
        confidence = float(
            np.clip(
                1.0
                - (
                    np.clip(
                        rel_err,
                        0.0,
                        self.fit_policy.relative_error_full_scale,
                    )
                    / self.fit_policy.relative_error_full_scale
                ),
                self.fit_policy.minimum_confidence,
                self.fit_policy.maximum_confidence,
            )
        )
        step = max(1, len(w_plot) // self.fit_policy.combustion_curve_max_points)
        combustion_curve = [
            {
                "watt": int(w_plot[index]),
                "fatOxidation": round(float(fat_gh[index]), 1),
                "carbOxidation": round(float(cho_gh[index]), 1),
            }
            for index in range(0, len(w_plot), step)
        ]

        unmasked = {
            "estimated_vo2max": round(vo2, 1),
            "estimated_vlamax_mmol_L_s": round(vlamax, 4),
            "mlss_power_watts": round(w_mlss, 1),
            "mlss_power_wkg": round(w_mlss / self.weight, 2),
            "fatmax_power_watts": round(w_fat, 1),
            "map_aerobic_watts": round(map_w, 1),
        }
        vo2_out = unmasked["estimated_vo2max"] if expressiveness.vo2max_reliable else None
        vla_out = (
            unmasked["estimated_vlamax_mmol_L_s"]
            if expressiveness.vlamax_reliable
            else None
        )
        mlss_out = unmasked["mlss_power_watts"] if expressiveness.mlss_reliable else None
        mlss_wkg_out = unmasked["mlss_power_wkg"] if expressiveness.mlss_reliable else None
        fatmax_out = (
            unmasked["fatmax_power_watts"] if expressiveness.fatmax_reliable else None
        )
        confidence_effective = (
            min(confidence, self.fit_policy.incomplete_expressiveness_confidence_cap)
            if not expressiveness.fully_expressive
            else confidence
        )

        cv_result = cross_validate_metabolic_profile(
            self,
            mmp,
            vo2,
            vlamax,
            eta_base=context.fixed_eta,
        )
        if cv_result.coherence_penalty > 0:
            confidence_effective = float(
                np.clip(
                    confidence_effective * (1.0 - cv_result.coherence_penalty),
                    self.fit_policy.minimum_confidence,
                    self.fit_policy.maximum_confidence,
                )
            )

        maximality_flag = None
        p_short = mmp.get(5) or mmp.get(10) or mmp.get(1)
        p_long = mmp.get(1200) or mmp.get(1800) or mmp.get(3600) or mmp.get(720)
        if p_short and p_long and p_long > 0:
            se_ratio = float(p_short) / float(p_long)
            if se_ratio < self.fit_policy.curve_maximality_floor:
                maximality_flag = {
                    "plausible_maximal": False,
                    "sprint_endurance_ratio": round(se_ratio, 2),
                    "reason": (
                        f"Sprint/endurance ratio {se_ratio:.2f} is below the physical "
                        f"floor (~{self.fit_policy.curve_maximality_floor:g}): "
                        "short-duration efforts look sub-maximal. "
                        "VLamax and VO2max are likely under-estimated; treat the "
                        "profile as indicative only and obtain a maximal sprint + "
                        "short CP efforts for a reliable anchor."
                    ),
                }
                confidence_effective = min(
                    confidence_effective,
                    self.fit_policy.submaximal_curve_confidence_cap,
                )

        end_max, all_max = self.context.phenotype_thresholds()
        apr_band = selection.apr_band
        snapshot: Dict[str, Any] = {
            "status": "success",
            "input_audit": input_audit,
            "estimated_vo2max": vo2_out,
            "estimated_vlamax_mmol_L_s": vla_out,
            "metabolic_phenotype": (
                self._classify_metabolic_phenotype(vlamax)
                if expressiveness.vlamax_reliable
                else None
            ),
            "assumed_la_capacity_mmol_L": round(final_lacap, 1),
            "mlss_power_watts": mlss_out,
            "mlss_power_wkg": mlss_wkg_out,
            "fatmax_power_watts": fatmax_out,
            "map_aerobic_watts": round(map_w, 1),
            "anaerobic_power_reserve": (
                {
                    "apr_ratio": round(apr_band[2], 2),
                    "vlamax_band": [round(apr_band[0], 2), round(apr_band[1], 2)],
                    "basin_gated_by_apr": selection.apr_gated,
                }
                if apr_band is not None
                else None
            ),
            "confidence_score": round(confidence_effective, 3),
            "fit_diagnostics": context.fit_diagnostics,
            "cross_validation": cv_result.to_dict(),
            "expressiveness": expressiveness.to_dict(),
            "curve_maximality": maximality_flag,
            "unmasked_estimates": unmasked,
            "context_used": {
                "gender": self.context.effective_gender(),
                "training_years": self.context.effective_training_years(),
                "discipline": self.context.effective_discipline(),
                "body_fat_pct": round(self.body_fat_pct, 1),
                "resolved_eta": round(context.fixed_eta, 4),
                "vlamax_initial_guess": round(context.vla_init, 3),
                "phenotype_thresholds": list(self.context.phenotype_thresholds()),
                "fat_ox_coefficient": self.context.fat_oxidation_coefficient(),
                "cho_ox_coefficient": self.context.cho_oxidation_coefficient(),
                "inferred_fields": self.context.inferred_fields(),
                "mader_constants": self.const.to_dict(),
            },
            "zones": (
                self._generate_zones(w_mlss, map_w)
                if expressiveness.mlss_reliable
                else None
            ),
            "combustion_curve": (
                combustion_curve if expressiveness.vlamax_reliable else None
            ),
            "calculated_at": datetime.now().isoformat(),
        }
        snapshot["glycolytic_profile"] = build_glycolytic_profile(
            snapshot,
            profiler=self,
            mmp={int(key): float(value) for key, value in mmp.items()},
            endurance_max=end_max,
            allrounder_max=all_max,
        )
        return snapshot

    def _generate_metabolic_snapshot_impl(
        self,
        mmp_raw: Dict[Any, Any],
        expected_eta: Optional[float] = None,
        measured_lacap: Optional[float] = None,
        mmp_samples: Optional[List[Dict[str, Any]]] = None,
        clean_mmp_first: bool = False,
        effective_cadence_rpm: Optional[float] = None,
        cadence_anchor_status: str = "unknown",
    ) -> Dict[str, Any]:
        """Generate a metabolic snapshot by coordinating typed helper stages."""
        prepared = self._prepare_snapshot_inputs(
            mmp_raw,
            expected_eta=expected_eta,
            measured_lacap=measured_lacap,
            mmp_samples=mmp_samples,
            clean_mmp_first=clean_mmp_first,
        )
        if len(prepared.mmp) < self.fit_policy.minimum_mmp_anchors:
            return self._finalize_snapshot(
                {
                    "status": "error",
                    "error_code": "insufficient_mmp_anchors",
                    "message": (
                        "Insufficient MMP anchors. At least "
                        f"{self.fit_policy.minimum_mmp_anchors} durations required."
                    ),
                    "input_audit": prepared.input_audit,
                    "fit_diagnostics": {
                        "fit_method": "joint",
                        "input_anchor_count": len(prepared.mmp),
                        "attempted_starts": 0,
                        "candidate_starts": 0,
                        "converged_starts": 0,
                        "nonconverged_starts": 0,
                        "exception_starts": 0,
                        "invalid_result_starts": 0,
                    },
                },
                prepared.mmp_quality_audit,
            )

        context = self._build_fit_context(
            prepared,
            expected_eta=expected_eta,
            measured_lacap=measured_lacap,
        )
        try:
            selection = self._run_multistart_fit(context)
            snapshot = self._build_success_snapshot(prepared, context, selection)
            return self._finalize_snapshot(
                snapshot,
                prepared.mmp_quality_audit,
                effective_cadence_rpm=effective_cadence_rpm,
                cadence_anchor_status=cadence_anchor_status,
            )
        except _MetabolicFitError:
            logger.warning(
                "metabolic_fit_failed",
                exc_info=True,
                extra={
                    "input_anchor_count": len(prepared.mmp),
                    "fit_anchor_count": int(context.durs_u.size),
                    "attempted_starts": context.fit_diagnostics["attempted_starts"],
                    "candidate_starts": context.fit_diagnostics["candidate_starts"],
                },
            )
            return self._finalize_snapshot(
                {
                    "status": "error",
                    "error_code": "metabolic_fit_failed",
                    "message": "Metabolic model fitting could not produce a valid solution.",
                    "input_audit": prepared.input_audit,
                    "fit_diagnostics": context.fit_diagnostics,
                },
                prepared.mmp_quality_audit,
                effective_cadence_rpm=effective_cadence_rpm,
                cadence_anchor_status=cadence_anchor_status,
            )
        except Exception:
            logger.exception(
                "metabolic_snapshot_generation_failed",
                extra={
                    "input_anchor_count": len(prepared.mmp),
                    "fit_anchor_count": int(context.durs_u.size),
                    "attempted_starts": context.fit_diagnostics["attempted_starts"],
                    "candidate_starts": context.fit_diagnostics["candidate_starts"],
                },
            )
            return self._finalize_snapshot(
                {
                    "status": "error",
                    "error_code": "metabolic_snapshot_failed",
                    "message": "Metabolic snapshot generation failed. Check server logs for details.",
                    "input_audit": prepared.input_audit,
                    "fit_diagnostics": context.fit_diagnostics,
                },
                prepared.mmp_quality_audit,
                effective_cadence_rpm=effective_cadence_rpm,
                cadence_anchor_status=cadence_anchor_status,
            )

    def vlamax_from_sprint(
        self,
        p_peak_1s: float,
        p_mean_sprint: float,
        sprint_duration_s: float = 20.0,
        vo2max_power_w: Optional[float] = None,
        tau_alactic_s: float = 15.0,
        tau_aerobic_s: float = 30.0,
        active_muscle_mass_kg: Optional[float] = None,
        *,
        t_p_peak_s: Optional[float] = None,
        peak_3s_w: Optional[float] = None,
        peak_5s_w: Optional[float] = None,
        neuromuscular_peak_w: Optional[float] = None,
        power: Optional[List[float]] = None,
        dt_s: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Estimate VLamax from an all-out sprint, Mader-based lactate decomposition.

        This is a model-based sprint-decomposition estimate of VLamax: a maximal sprint
        of ~15-25 s isolates the glycolytic system. We decompose the mean
        sprint power into three contributions and convert the glycolytic part
        into a lactate-production rate:

            P_sprint = P_alactic(t) + P_aerobic(t) + P_glycolytic

          * P_alactic: the PCr/neuromuscular component. Its instantaneous
            ceiling is ~the 1 s peak; over the sprint it decays with
            tau_alactic, so the time-averaged contribution is
            P_peak * tau/T * (1 - exp(-T/tau)).
          * P_aerobic: VO2 kinetics are slow, so only a fraction of the
            athlete's aerobic ceiling is online during a short sprint.
          * P_glycolytic: the remainder, which is sustained by lactate
            production. Converted to a metabolic rate (via eta) and then to
            mmol lactate per litre per second over the active muscle mass.

        Validated against the FLOW lab test for this athlete profile
        (sprint 20 s = 864 W, 1 s peak = 1099 W -> VLamax 0.61 measured;
        this method returns ~0.61).

        IMPORTANT — tau_alactic sensitivity: VLamax is strongly sensitive to
        the alactic time constant (a 10->25 s change moves VLamax from ~0.97
        to ~0.21). The 15 s default matches the validated profile but varies
        between athletes; this is exactly why a protocol that constrains the
        alactic component (e.g. a separate short maximal effort) gives a more
        reliable VLamax than a single sprint. The returned dict therefore
        includes a sensitivity range, not just a point value.
        """
        if p_peak_1s <= 0 or p_mean_sprint <= 0:
            return {"status": "error", "message": "Sprint powers must be positive."}

        from engines.performance.sprint_peak_analysis import neuromuscular_peak_for_decomposition

        peak_ctx = neuromuscular_peak_for_decomposition(
            p_peak_1s=p_peak_1s,
            p_mean_sprint=p_mean_sprint,
            sprint_duration_s=sprint_duration_s,
            t_p_peak_s=t_p_peak_s,
            peak_3s_w=peak_3s_w,
            peak_5s_w=peak_5s_w,
            neuromuscular_peak_w=neuromuscular_peak_w,
            power=power,
            dt_s=dt_s,
        )
        p_neuro = float(peak_ctx["neuromuscular_peak_w"])
        sustain_ratio = float(peak_ctx["sustain_ratio"])
        quality_flags = list(peak_ctx.get("quality_flags") or [])

        # Sprint validity gate. The decomposition only works on a genuine
        # all-out sprint where power is *sustained* near the neuromuscular
        # ceiling (instantaneous 1 s peak for early recruiters; best 3–5 s
        # rolling peak when motor recruitment is delayed).
        min_sustain = (
            self.calibration.sprint_min_sustain_intercept
            - self.calibration.sprint_min_sustain_duration_slope * sprint_duration_s
        )
        required_sustain = max(
            self.calibration.sprint_min_sustain_floor,
            min_sustain,
        )
        if sustain_ratio < required_sustain:
            return {
                "status": "insufficient_sprint",
                "message": (
                    f"Sprint not maximal/sustained enough for VLamax estimation "
                    f"(mean/peak={sustain_ratio:.2f}, need >= {required_sustain:.2f}). "
                    f"The neuromuscular peak ({p_neuro:.0f} W) likely a momentary spike, not a "
                    f"true all-out effort. Provide a dedicated maximal sprint."
                ),
                "sustain_ratio": round(sustain_ratio, 3),
                "sprint_peak_contract": peak_ctx.get("sprint_peak_contract"),
            }

        amm = active_muscle_mass_kg if active_muscle_mass_kg is not None else self.active_muscle_mass
        vo2_power = (
            float(vo2max_power_w)
            if vo2max_power_w is not None
            else self._map_estimate(
                50.0,
                self.context.expected_eta(),
            )
        )
        eta = self.context.expected_eta()

        def _vlamax_for_tau(tau_alac: float) -> float:
            t = sprint_duration_s
            alac_frac_avg = tau_alac / t * (1.0 - np.exp(-t / tau_alac))
            p_alac_avg = (
                p_neuro * self.calibration.sprint_neuromuscular_scale
            ) * alac_frac_avg
            aero_frac = 1.0 - tau_aerobic_s / t * (1.0 - np.exp(-t / tau_aerobic_s))
            p_aero_avg = (
                vo2_power
                * aero_frac
                * self.calibration.sprint_aerobic_contribution_scale
            )  # VO2 not at steady state
            p_glyc = max(0.0, p_mean_sprint - p_alac_avg - p_aero_avg)
            glyc_metabolic_rate = p_glyc / eta
            return glyc_metabolic_rate / (
                self.calibration.energy_j_per_mmol_lactate_per_kg * amm
            )

        vlamax_raw = _vlamax_for_tau(tau_alactic_s)
        if vlamax_raw < self.calibration.sprint_min_resolved_vlamax:
            # Decomposition collapsed (glycolytic remainder ~0): the inputs
            # don't isolate the glycolytic system cleanly. Don't fabricate.
            return {
                "status": "insufficient_sprint",
                "message": (
                    "Glycolytic component of the sprint resolved to ~0; cannot "
                    "estimate VLamax. Sprint likely too short, sub-maximal, or "
                    "peak/mean inconsistent."
                ),
            }

        vlamax = float(
            np.clip(vlamax_raw, *self.calibration.sprint_vlamax_bounds)
        )
        # Sensitivity band from the configured plausible tau_alactic range.
        tau_low, tau_high = self.calibration.sprint_tau_sensitivity_bounds_s
        vla_hi = float(
            np.clip(
                _vlamax_for_tau(tau_low),
                *self.calibration.sprint_vlamax_bounds,
            )
        )
        vla_lo = float(
            np.clip(
                _vlamax_for_tau(tau_high),
                *self.calibration.sprint_vlamax_bounds,
            )
        )

        payload = {
            "status": "success",
            "vlamax_mmol_l_s": round(vlamax, 3),
            "vlamax_range": [round(min(vla_lo, vla_hi), 3), round(max(vla_lo, vla_hi), 3)],
            "method": "sprint_decomposition_mader",
            "inputs": {
                "p_peak_1s": p_peak_1s,
                "p_mean_sprint": p_mean_sprint,
                "sprint_duration_s": sprint_duration_s,
                "neuromuscular_peak_w": round(p_neuro, 1),
                "vo2max_power_w": round(vo2_power, 1),
                "tau_alactic_s": tau_alactic_s,
                "active_muscle_mass_kg": round(amm, 2),
            },
            "sprint_peak_contract": peak_ctx.get("sprint_peak_contract"),
            "quality_flags": quality_flags,
            "sustain_ratio": round(sustain_ratio, 3),
            "note": (
                "VLamax is sensitive to the alactic time constant; the range "
                f"reflects tau_alactic {tau_low:g}-{tau_high:g} s. "
                "Delayed motor recruitment uses "
                "the best 3–5 s rolling peak as the neuromuscular ceiling."
            ),
            "limitations": vlamax_limitations(),
        }
        payload["model_configuration"] = self._model_configuration_manifest()
        payload.update(vlamax_contract_fields())
        return payload

    def _prepare_segmented_inputs(
        self,
        mmp_raw: Dict[Any, Any],
        aerobic_min_duration_s: Optional[float],
        kwargs: Dict[str, Any],
    ) -> _PreparedSegmentedInputs:
        """Normalize a full MMP and isolate the aerobic fitting domain."""
        aerobic_duration_source = (
            "fit_policy" if aerobic_min_duration_s is None else "argument_override"
        )
        effective_min_duration = (
            self.fit_policy.segmented_aerobic_min_duration_s
            if aerobic_min_duration_s is None
            else aerobic_min_duration_s
        )
        input_audit = self._base_input_audit(
            mmp_raw=mmp_raw,
            expected_eta=kwargs.get("expected_eta"),
            measured_lacap=kwargs.get("measured_lacap"),
        )
        mmp = self._coerce_mmp_dict_with_audit(mmp_raw, input_audit)
        aerobic_mmp = {
            duration: power for duration, power in mmp.items() if duration >= effective_min_duration
        }
        return _PreparedSegmentedInputs(
            mmp=mmp,
            aerobic_mmp=aerobic_mmp,
            input_audit=input_audit,
            aerobic_min_duration_s=effective_min_duration,
            aerobic_duration_source=aerobic_duration_source,
        )

    def _record_segmented_runtime(
        self,
        snapshot: Dict[str, Any],
        prepared: _PreparedSegmentedInputs,
    ) -> Dict[str, Any]:
        """Record the effective segmented duration threshold in the manifest."""
        return self._record_runtime_parameter(
            snapshot,
            name="segmented_aerobic_min_duration_s",
            value=prepared.aerobic_min_duration_s,
            source=prepared.aerobic_duration_source,
        )

    @staticmethod
    def _segmented_fit_diagnostics(
        aerobic_snapshot: Optional[Dict[str, Any]],
        full_curve_snapshot: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build the stable public diagnostic envelope for both stages."""
        return {
            "fit_method": "segmented",
            "aerobic_stage": (
                aerobic_snapshot.get("fit_diagnostics") if aerobic_snapshot is not None else None
            ),
            "full_curve_stage": (
                full_curve_snapshot.get("fit_diagnostics")
                if full_curve_snapshot is not None
                else None
            ),
        }

    def _segmented_joint_fallback(
        self,
        prepared: _PreparedSegmentedInputs,
        mmp_raw: Dict[Any, Any],
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Use the joint fit when the aerobic domain cannot stand alone."""
        joint = self.generate_metabolic_snapshot(mmp_raw, **kwargs)
        if isinstance(joint, dict) and joint.get("status") == "success":
            joint["fit_method"] = "joint_fallback"
            joint_diagnostics = dict(joint.get("fit_diagnostics") or {})
            joint_diagnostics["fit_method"] = "joint_fallback"
            joint["fit_diagnostics"] = joint_diagnostics
            joint["segmented_detail"] = {
                "reason": "insufficient_aerobic_anchors",
                "aerobic_anchors": sorted(prepared.aerobic_mmp.keys()),
                "aerobic_min_duration_s": prepared.aerobic_min_duration_s,
            }
        return self._record_segmented_runtime(joint, prepared)

    def _segmented_aerobic_stage_error(
        self,
        prepared: _PreparedSegmentedInputs,
        aerobic_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Preserve an aerobic-stage failure with full raw-input provenance."""
        aerobic_snapshot.setdefault("error_code", "segmented_aerobic_fit_failed")
        aerobic_snapshot["input_audit"] = self._merge_stage_input_audit(
            prepared.input_audit,
            aerobic_snapshot.get("input_audit"),
        )
        aerobic_snapshot["fit_diagnostics"] = self._segmented_fit_diagnostics(
            aerobic_snapshot,
            None,
        )
        aerobic_snapshot["segmented_detail"] = {
            "aerobic_stage_status": aerobic_snapshot.get("status", "error"),
            "full_curve_stage_status": "not_run",
            "aerobic_anchors": sorted(prepared.aerobic_mmp.keys()),
            "full_curve_anchors": sorted(prepared.mmp.keys()),
            "aerobic_min_duration_s": prepared.aerobic_min_duration_s,
        }
        return aerobic_snapshot

    def _segmented_full_stage_error(
        self,
        prepared: _PreparedSegmentedInputs,
        aerobic_snapshot: Dict[str, Any],
        full_curve_snapshot: Dict[str, Any],
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return a stable error when the second fitting stage fails."""
        input_audit = self._merge_stage_input_audit(
            prepared.input_audit,
            full_curve_snapshot.get("input_audit"),
        )
        return self._finalize_snapshot(
            {
                "status": "error",
                "error_code": "segmented_full_curve_fit_failed",
                "message": "Segmented metabolic fit could not complete the full-curve stage.",
                "input_audit": input_audit,
                "fit_diagnostics": self._segmented_fit_diagnostics(
                    aerobic_snapshot,
                    full_curve_snapshot,
                ),
                "segmented_detail": {
                    "aerobic_stage_status": "success",
                    "full_curve_stage_status": full_curve_snapshot.get("status", "error"),
                    "aerobic_anchors": sorted(prepared.aerobic_mmp.keys()),
                    "full_curve_anchors": sorted(prepared.mmp.keys()),
                    "aerobic_min_duration_s": prepared.aerobic_min_duration_s,
                },
            },
            full_curve_snapshot.get("mmp_quality") or aerobic_snapshot.get("mmp_quality"),
            effective_cadence_rpm=kwargs.get("effective_cadence_rpm"),
            cadence_anchor_status=str(kwargs.get("cadence_anchor_status") or "unknown"),
        )

    def _resolve_segmented_parameter_pair(
        self,
        aerobic_snapshot: Dict[str, Any],
        full_curve_snapshot: Dict[str, Any],
    ) -> Optional[_SegmentedParameterPair]:
        """Combine aerobic VO2max and full-curve VLamax into one model pair."""
        aerobic_unmasked = aerobic_snapshot.get("unmasked_estimates") or {}
        full_unmasked = full_curve_snapshot.get("unmasked_estimates") or {}
        vo2_value = aerobic_unmasked.get(
            "estimated_vo2max",
            aerobic_snapshot.get("estimated_vo2max"),
        )
        vlamax_value = full_unmasked.get(
            "estimated_vlamax_mmol_L_s",
            full_curve_snapshot.get("estimated_vlamax_mmol_L_s"),
        )
        if vo2_value is None or vlamax_value is None:
            return None

        vo2max = float(vo2_value)
        vlamax = float(vlamax_value)
        context_used = dict(
            aerobic_snapshot.get("context_used") or full_curve_snapshot.get("context_used") or {}
        )
        fixed_eta = float(context_used.get("resolved_eta", self.context.expected_eta()))
        lactate_capacity = float(
            full_curve_snapshot.get("assumed_la_capacity_mmol_L")
            or aerobic_snapshot.get("assumed_la_capacity_mmol_L")
            or np.clip(
                self.calibration.lacap_intercept
                + (vlamax - self.calibration.lacap_vlamax_anchor)
                * self.calibration.lacap_vlamax_slope,
                self.fit_policy.minimum_lacap_mmol_l,
                self.fit_policy.maximum_lacap_mmol_l,
            )
        )
        return _SegmentedParameterPair(
            vo2max=vo2max,
            vlamax=vlamax,
            fixed_eta=fixed_eta,
            lactate_capacity=lactate_capacity,
            context_used=context_used,
        )

    def _segmented_missing_parameter_error(
        self,
        prepared: _PreparedSegmentedInputs,
        aerobic_snapshot: Dict[str, Any],
        full_curve_snapshot: Dict[str, Any],
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Report a completed two-stage fit that lacks one final parameter."""
        aerobic_unmasked = aerobic_snapshot.get("unmasked_estimates") or {}
        full_unmasked = full_curve_snapshot.get("unmasked_estimates") or {}
        vo2_available = (
            aerobic_unmasked.get(
                "estimated_vo2max",
                aerobic_snapshot.get("estimated_vo2max"),
            )
            is not None
        )
        vlamax_available = (
            full_unmasked.get(
                "estimated_vlamax_mmol_L_s",
                full_curve_snapshot.get("estimated_vlamax_mmol_L_s"),
            )
            is not None
        )
        input_audit = self._merge_stage_input_audit(
            prepared.input_audit,
            full_curve_snapshot.get("input_audit"),
        )
        return self._finalize_snapshot(
            {
                "status": "error",
                "error_code": "segmented_parameter_missing",
                "message": "Segmented fit completed but did not produce both model parameters.",
                "input_audit": input_audit,
                "fit_diagnostics": self._segmented_fit_diagnostics(
                    aerobic_snapshot,
                    full_curve_snapshot,
                ),
                "segmented_detail": {
                    "aerobic_stage_status": "success",
                    "full_curve_stage_status": "success",
                    "aerobic_vo2max_available": vo2_available,
                    "full_curve_vlamax_available": vlamax_available,
                },
            },
            full_curve_snapshot.get("mmp_quality") or aerobic_snapshot.get("mmp_quality"),
            effective_cadence_rpm=kwargs.get("effective_cadence_rpm"),
            cadence_anchor_status=str(kwargs.get("cadence_anchor_status") or "unknown"),
        )

    def _calculate_segmented_confidence(
        self,
        *,
        expressiveness: ExpressivenessReport,
        cross_validation: Any,
        aerobic_snapshot: Dict[str, Any],
        full_curve_snapshot: Dict[str, Any],
    ) -> float:
        """Combine stage scores without double-applying coherence penalties."""
        stage_confidences = [
            float(value)
            for value in (
                aerobic_snapshot.get("confidence_score"),
                full_curve_snapshot.get("confidence_score"),
            )
            if value is not None
        ]
        confidence = (
            min(stage_confidences) if stage_confidences else self.fit_policy.minimum_confidence
        )
        if not expressiveness.fully_expressive:
            confidence = min(
                confidence,
                self.fit_policy.incomplete_expressiveness_confidence_cap,
            )

        stage_penalty = max(
            float((aerobic_snapshot.get("cross_validation") or {}).get("coherence_penalty") or 0.0),
            float(
                (full_curve_snapshot.get("cross_validation") or {}).get("coherence_penalty") or 0.0
            ),
        )
        incremental_penalty = max(
            0.0,
            float(cross_validation.coherence_penalty) - stage_penalty,
        )
        if incremental_penalty > 0:
            confidence *= 1.0 - incremental_penalty

        curve_maximality = full_curve_snapshot.get("curve_maximality")
        if (curve_maximality or {}).get("plausible_maximal") is False:
            confidence = min(
                confidence,
                self.fit_policy.submaximal_curve_confidence_cap,
            )
        return float(
            np.clip(
                confidence,
                self.fit_policy.minimum_confidence,
                self.fit_policy.maximum_confidence,
            )
        )

    def _derive_segmented_outputs(
        self,
        prepared: _PreparedSegmentedInputs,
        parameters: _SegmentedParameterPair,
        aerobic_snapshot: Dict[str, Any],
        full_curve_snapshot: Dict[str, Any],
    ) -> _SegmentedDerivedOutputs:
        """Recompute every coupled output from the final parameter pair."""
        w_mlss, w_fat, w_plot, fat_gh, cho_gh = self._calculate_curves(
            parameters.vo2max,
            parameters.vlamax,
            parameters.fixed_eta,
        )
        map_w = self._map_estimate(parameters.vo2max, parameters.fixed_eta)
        expressiveness = ExpressivenessReport.from_mmp(prepared.mmp)
        unmasked = {
            "estimated_vo2max": round(parameters.vo2max, 1),
            "estimated_vlamax_mmol_L_s": round(parameters.vlamax, 4),
            "mlss_power_watts": round(w_mlss, 1),
            "mlss_power_wkg": round(w_mlss / self.weight, 2),
            "fatmax_power_watts": round(w_fat, 1),
            "map_aerobic_watts": round(map_w, 1),
        }
        cross_validation = cross_validate_metabolic_profile(
            self,
            prepared.mmp,
            parameters.vo2max,
            parameters.vlamax,
            eta_base=parameters.fixed_eta,
        )
        confidence = self._calculate_segmented_confidence(
            expressiveness=expressiveness,
            cross_validation=cross_validation,
            aerobic_snapshot=aerobic_snapshot,
            full_curve_snapshot=full_curve_snapshot,
        )
        step = max(
            1,
            len(w_plot) // self.fit_policy.combustion_curve_max_points,
        )
        combustion_curve = [
            {
                "watt": int(w_plot[index]),
                "fatOxidation": round(float(fat_gh[index]), 1),
                "carbOxidation": round(float(cho_gh[index]), 1),
            }
            for index in range(0, len(w_plot), step)
        ]
        return _SegmentedDerivedOutputs(
            w_mlss=w_mlss,
            w_fat=w_fat,
            map_w=map_w,
            expressiveness=expressiveness,
            unmasked=unmasked,
            vo2_out=(unmasked["estimated_vo2max"] if expressiveness.vo2max_reliable else None),
            vlamax_out=(
                unmasked["estimated_vlamax_mmol_L_s"] if expressiveness.vlamax_reliable else None
            ),
            mlss_out=(unmasked["mlss_power_watts"] if expressiveness.mlss_reliable else None),
            mlss_wkg_out=(unmasked["mlss_power_wkg"] if expressiveness.mlss_reliable else None),
            fatmax_out=(unmasked["fatmax_power_watts"] if expressiveness.fatmax_reliable else None),
            cross_validation=cross_validation,
            confidence=confidence,
            curve_maximality=full_curve_snapshot.get("curve_maximality"),
            combustion_curve=combustion_curve,
        )

    def _build_segmented_success_snapshot(
        self,
        prepared: _PreparedSegmentedInputs,
        parameters: _SegmentedParameterPair,
        derived: _SegmentedDerivedOutputs,
        aerobic_snapshot: Dict[str, Any],
        full_curve_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Assemble the public success payload from recomputed outputs."""
        end_max, all_max = self.context.phenotype_thresholds()
        input_audit = self._merge_stage_input_audit(
            prepared.input_audit,
            full_curve_snapshot.get("input_audit"),
        )
        merged = dict(aerobic_snapshot)
        merged.pop("mmp_quality", None)
        merged.update(
            {
                "status": "success",
                "input_audit": input_audit,
                "estimated_vo2max": derived.vo2_out,
                "estimated_vlamax_mmol_L_s": derived.vlamax_out,
                "metabolic_phenotype": (
                    self._classify_metabolic_phenotype(parameters.vlamax)
                    if derived.expressiveness.vlamax_reliable
                    else None
                ),
                "assumed_la_capacity_mmol_L": round(parameters.lactate_capacity, 1),
                "mlss_power_watts": derived.mlss_out,
                "mlss_power_wkg": derived.mlss_wkg_out,
                "fatmax_power_watts": derived.fatmax_out,
                "map_aerobic_watts": round(derived.map_w, 1),
                "anaerobic_power_reserve": full_curve_snapshot.get("anaerobic_power_reserve"),
                "confidence_score": round(derived.confidence, 3),
                "fit_diagnostics": {
                    **self._segmented_fit_diagnostics(aerobic_snapshot, full_curve_snapshot),
                    "combined_parameter_sources": {
                        "vo2max": "aerobic_stage",
                        "vlamax": "full_curve_stage",
                    },
                },
                "cross_validation": derived.cross_validation.to_dict(),
                "expressiveness": derived.expressiveness.to_dict(),
                "curve_maximality": derived.curve_maximality,
                "unmasked_estimates": derived.unmasked,
                "context_used": parameters.context_used,
                "zones": (
                    self._generate_zones(derived.w_mlss, derived.map_w)
                    if derived.expressiveness.mlss_reliable
                    else None
                ),
                "combustion_curve": (
                    derived.combustion_curve if derived.expressiveness.vlamax_reliable else None
                ),
                "calculated_at": datetime.now().isoformat(),
                "fit_method": "segmented",
                "segmented_detail": {
                    "aerobic_anchors": sorted(prepared.aerobic_mmp.keys()),
                    "anaerobic_anchors": sorted(prepared.mmp.keys()),
                    "full_curve_anchors": sorted(prepared.mmp.keys()),
                    "aerobic_min_duration_s": prepared.aerobic_min_duration_s,
                    "aerobic_stage_status": "success",
                    "full_curve_stage_status": "success",
                    "aerobic_stage_confidence": float(
                        aerobic_snapshot.get("confidence_score") or 0.0
                    ),
                    "full_curve_stage_confidence": float(
                        full_curve_snapshot.get("confidence_score") or 0.0
                    ),
                    "confidence_strategy": "minimum_of_stage_scores",
                    "combined_cross_validation_penalty": round(
                        float(derived.cross_validation.coherence_penalty), 3
                    ),
                    "vo2max_source": "aerobic_domain",
                    "vlamax_source": "full_curve",
                    "mlss_source": "recomputed_segmented_parameter_pair",
                    "fatmax_source": "recomputed_segmented_parameter_pair",
                    "combustion_curve_source": "recomputed_segmented_parameter_pair",
                    "joint_vo2max": full_curve_snapshot.get("estimated_vo2max"),
                    "joint_mlss_power_watts": full_curve_snapshot.get("mlss_power_watts"),
                },
            }
        )
        merged["glycolytic_profile"] = build_glycolytic_profile(
            merged,
            profiler=self,
            mmp={int(key): float(value) for key, value in prepared.mmp.items()},
            endurance_max=end_max,
            allrounder_max=all_max,
        )
        return merged

    def generate_metabolic_snapshot_segmented(
        self,
        mmp_raw: Dict[Any, Any],
        aerobic_min_duration_s: Optional[float] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Build a domain-separated snapshot for bimodal power-duration curves.

        Stage 1 fits the aerobic anchors and supplies VO2max. Stage 2 fits the
        full curve and supplies VLamax. Because MLSS, FatMax, substrate curves
        and validation are coupled to both parameters, every dependent output
        is rebuilt from the final (aerobic VO2max, full-curve VLamax) pair.

        Falls back transparently to the joint fit when fewer than three
        aerobic anchors are available.
        """
        prepared = self._prepare_segmented_inputs(mmp_raw, aerobic_min_duration_s, kwargs)
        if len(prepared.aerobic_mmp) < self.fit_policy.minimum_fit_anchors:
            return self._segmented_joint_fallback(prepared, mmp_raw, kwargs)

        aerobic_snapshot = self.generate_metabolic_snapshot(prepared.aerobic_mmp, **kwargs)
        if aerobic_snapshot.get("status") != "success":
            return self._segmented_aerobic_stage_error(prepared, aerobic_snapshot)

        full_curve_snapshot = self.generate_metabolic_snapshot(prepared.mmp, **kwargs)
        if full_curve_snapshot.get("status") != "success":
            return self._segmented_full_stage_error(
                prepared,
                aerobic_snapshot,
                full_curve_snapshot,
                kwargs,
            )

        parameters = self._resolve_segmented_parameter_pair(aerobic_snapshot, full_curve_snapshot)
        if parameters is None:
            return self._segmented_missing_parameter_error(
                prepared,
                aerobic_snapshot,
                full_curve_snapshot,
                kwargs,
            )

        derived = self._derive_segmented_outputs(
            prepared,
            parameters,
            aerobic_snapshot,
            full_curve_snapshot,
        )
        merged = self._build_segmented_success_snapshot(
            prepared,
            parameters,
            derived,
            aerobic_snapshot,
            full_curve_snapshot,
        )
        finalized = self._finalize_snapshot(
            merged,
            full_curve_snapshot.get("mmp_quality") or aerobic_snapshot.get("mmp_quality"),
            effective_cadence_rpm=kwargs.get("effective_cadence_rpm"),
            cadence_anchor_status=str(kwargs.get("cadence_anchor_status") or "unknown"),
        )
        return self._record_segmented_runtime(finalized, prepared)

    @staticmethod
    def _bimodality_ratio(mmp: Dict[int, float]) -> Optional[float]:
        """
        Sprint-to-endurance power ratio, a cheap bimodality detector.

        A "diesel" rider's power-duration curve decays smoothly: the ratio of
        a very-short peak (~5 s) to a long aerobic effort (~60 min) sits
        around 2.5-4. A bimodal rider — a large alactic/glycolytic sprint
        sitting on top of a comparatively modest aerobic base — pushes that
        ratio higher. Above ~4.2 the joint fit starts trading aerobic
        accuracy for the sprint, and the segmented fit becomes worth it.

        Returns None if the curve lacks the anchors to judge.
        """
        p_short = mmp.get(5) or mmp.get(10) or mmp.get(15)
        p_long = mmp.get(3600) or mmp.get(1800) or mmp.get(1200)
        if not p_short or not p_long or p_long <= 0:
            return None
        return float(p_short) / float(p_long)

    def generate_metabolic_snapshot_auto(
        self,
        mmp_raw: Dict[Any, Any],
        bimodal_threshold: Optional[float] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Pick the fit strategy automatically from the curve's shape.

        Segmenting the fit by physiological domain fixes the case where an
        extreme sprint distorts the aerobic estimate — but only helps when
        that distortion is actually present. For a smoothly-decaying diesel
        curve the joint fit is already correct, and segmenting would inflate
        VO2max/MLSS by extrapolating from long anchors alone. So:

          * ratio >= bimodal_threshold  -> segmented fit (de-contaminate aerobic)
          * ratio <  bimodal_threshold  -> joint fit (already coherent)

        The chosen path and the measured ratio are recorded under
        `fit_method` / `bimodality_ratio` so the decision is transparent.
        """
        threshold_source = "fit_policy" if bimodal_threshold is None else "argument_override"
        effective_bimodal_threshold = (
            self.fit_policy.bimodality_threshold
            if bimodal_threshold is None
            else float(bimodal_threshold)
        )
        mmp = self._coerce_mmp_dict(mmp_raw)
        ratio = self._bimodality_ratio(mmp)

        if ratio is not None and ratio >= effective_bimodal_threshold:
            snap = self.generate_metabolic_snapshot_segmented(mmp_raw, **kwargs)
            snap["bimodality_ratio"] = round(ratio, 2)
            snap["fit_strategy_reason"] = (
                f"bimodal (P_short/P_long={ratio:.2f} >= "
                f"{effective_bimodal_threshold}): "
                f"segmented to keep sprint from distorting aerobic estimate"
            )
            return self._record_runtime_parameter(
                snap,
                name="bimodality_threshold",
                value=effective_bimodal_threshold,
                source=threshold_source,
            )

        snap = self.generate_metabolic_snapshot(mmp_raw, **kwargs)
        if isinstance(snap, dict) and snap.get("status") == "success":
            snap["fit_method"] = "joint_auto"
            snap["bimodality_ratio"] = round(ratio, 2) if ratio is not None else None
            snap["fit_strategy_reason"] = (
                f"unimodal (P_short/P_long={ratio:.2f} < "
                f"{effective_bimodal_threshold}): "
                f"joint fit already coherent"
                if ratio is not None else
                "insufficient anchors to judge bimodality; joint fit used"
            )
        return self._record_runtime_parameter(
            snap,
            name="bimodality_threshold",
            value=effective_bimodal_threshold,
            source=threshold_source,
        )

    def _finalize_snapshot(
        self,
        snap: Dict[str, Any],
        audit: Optional[Dict[str, Any]],
        *,
        effective_cadence_rpm: Optional[float] = None,
        cadence_anchor_status: str = "unknown",
    ) -> Dict[str, Any]:
        """Attach model configuration, quality metadata and optional MMP audit."""
        snap.setdefault("model_configuration", self._model_configuration_manifest())
        extra_limits: List[str] = []
        if snap.get("status") == "success":
            snap.update(vlamax_contract_fields())
            snap["cadence_anchor"] = cadence_anchor_metadata(
                effective_cadence_rpm=effective_cadence_rpm,
                cadence_anchor_status=cadence_anchor_status,
            )
            extra_limits = vlamax_limitations(effective_cadence_rpm=effective_cadence_rpm)
            expressiveness = snap.get("expressiveness", {}) or {}
            missing_inputs = list(expressiveness.get("missing_windows") or [])
            quality_flags: List[str] = []
            if not expressiveness.get("fully_expressive", True):
                quality_flags.append("expressiveness_limited")
            curve_maximality = snap.get("curve_maximality") or {}
            if curve_maximality.get("plausible_maximal") is False:
                quality_flags.append("curve_likely_submaximal")
            quality_flags.extend(
                MetabolicProfiler._fit_diagnostic_quality_flags(
                    snap.get("fit_diagnostics")
                )
            )
            input_audit = snap.get("input_audit") or {}
            input_summary = input_audit.get("summary") or {}
            if input_audit.get("has_adjustments"):
                quality_flags.append("input_adjustments_applied")
            if input_summary.get("clipped_fields"):
                quality_flags.append("input_clipping_applied")
            if (
                int(input_summary.get("discarded_mmp_anchors") or 0) > 0
                or int(input_summary.get("quality_cleaner_removed_mmp_anchors") or 0) > 0
            ):
                quality_flags.append("mmp_anchors_discarded")
            if int(input_summary.get("duplicate_mmp_durations") or 0) > 0:
                quality_flags.append("mmp_duplicate_durations_resolved")
            confidence_score = float(snap.get("confidence_score") or 0.0)
            snap["model_metadata"] = finalize_model_metadata(
                assumptions=[
                    "mader_joint_fit_is_model_based_not_direct_measurement",
                    "metabolic_outputs_depend_on_anchor_quality",
                ],
                missing_inputs=missing_inputs,
                quality_flags=quality_flags,
                confidence=confidence_score,
            )
            show_values = should_display(confidence_score, DEFAULT_DISPLAY_THRESHOLD)
            flagship_fields = [
                "estimated_vo2max",
                "estimated_vlamax_mmol_L_s",
                "mlss_power_watts",
                "fatmax_power_watts",
            ]
            snap["ui_display"] = {
                "show_values": show_values,
                "threshold": DEFAULT_DISPLAY_THRESHOLD,
                "recommended_mask_fields": (
                    [] if show_values else [f for f in flagship_fields if snap.get(f) is not None]
                ),
                "reason": (
                    "confidence_above_threshold"
                    if show_values
                    else "confidence_below_threshold_use_placeholder"
                ),
            }
        else:
            snap["model_metadata"] = finalize_model_metadata(
                assumptions=["snapshot_generation_failed_before_model_convergence"],
                missing_inputs=[],
                quality_flags=["engine_error"],
                confidence=0.0,
            )
        if audit is not None:
            snap["mmp_quality"] = audit
        if extra_limits:
            snap["limitations"] = extra_limits
        annotate_payload(
            snap,
            module_name="metabolic_profiler",
            method="mader_least_squares",
            confidence_field="confidence_score",
            limitations=(
                extra_limits
                + (
                    ["One or more metabolic outputs were masked by expressiveness gates."]
                    if snap.get("expressiveness", {}).get("fully_expressive") is False
                    else []
                )
            ),
        )
        return snap

    def enhance_with_phenotype(
        self,
        snapshot: Dict[str, Any],
        phenotype: Optional[str] = None,
        power_30s: Optional[float] = None,
        power_1200s: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Add phenotype-adaptive PCr modeling to an existing snapshot.
        
        Convenience method that wraps the standalone
        `metabolic_profiler_phenotype.enhance_metabolic_snapshot_with_phenotype()`
        function and supplies the athlete weight automatically (since this
        profiler instance already has it).
        
        Parameters
        ----------
        snapshot : dict
            Output from self.generate_metabolic_snapshot().
        phenotype : str, optional
            One of SPRINTER, TT_CLIMBER, PURSUITER, ALL_ROUNDER.
            If None or unknown, falls back to DEFAULT parameters.
        power_30s, power_1200s : float, optional
            Reference powers for the sprint/threshold energy-contribution
            examples. If None, derived from MLSS (1.5×MLSS for sprint,
            MLSS for threshold).
        
        Returns
        -------
        dict
            The same snapshot with `phenotype_pcr_params` and
            `energy_contributions` sections added (in-place mutation +
            return for chaining).
        
        Tier: HEURISTIC (phenotype PCr capacities are rule-of-thumb).
        """
        # Local import to avoid circular reference at module load
        from engines.metabolic.metabolic_profiler_phenotype import enhance_metabolic_snapshot_with_phenotype
        return enhance_metabolic_snapshot_with_phenotype(
            snapshot,
            phenotype=phenotype,
            weight_kg=self.weight,
            power_30s=power_30s,
            power_1200s=power_1200s,
        )
