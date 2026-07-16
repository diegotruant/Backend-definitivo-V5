"""Mader model constants and MMP expressiveness reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class RegularizationWeights:
    vo2_vs_guess: float = 0.5
    vo2_vs_expected_heuristic: float = 0.5
    short_mae_scale: float = 1.8

    def to_dict(self) -> Dict[str, Any]:
        return {
            "classification": "fit_regularization",
            "vo2_vs_guess": self.vo2_vs_guess,
            "vo2_vs_expected_heuristic": self.vo2_vs_expected_heuristic,
            "short_mae_scale": self.short_mae_scale,
        }


@dataclass(frozen=True)
class MaderConstants:
    """
    Mader model parameters.

    Default values are from Mader & Heck 1986 / Mader 2003.
    """

    vo2_basale: float = 3.5
    equiv_o2_la: float = 0.01576
    vol_rel: float = 0.45
    ks1: float = 0.0631
    ks2: float = 1.331
    mlss_net_frac: float = 0.05
    eps: float = 1e-9
    softplus_k: float = 120.0
    w_step: float = 10.0
    w_min: float = 50.0
    pcr_multiplier: float = 15.0
    pcr_prior_min: float = 80.0
    pcr_prior_max: float = 280.0
    _source: str = "mader_heck_1986_default"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "classification": "physiological_model_constants",
            "ks1": self.ks1,
            "ks2": self.ks2,
            "vo2_basale": self.vo2_basale,
            "equiv_o2_la": self.equiv_o2_la,
            "vol_rel": self.vol_rel,
            "mlss_net_frac": self.mlss_net_frac,
            "eps": self.eps,
            "softplus_k": self.softplus_k,
            "w_step": self.w_step,
            "w_min": self.w_min,
            "pcr_multiplier": self.pcr_multiplier,
            "pcr_prior_min": self.pcr_prior_min,
            "pcr_prior_max": self.pcr_prior_max,
            "source": self._source,
        }


@dataclass(frozen=True)
class ExpressivenessReport:
    """Assesses whether an MMP curve covers durations needed for reliable fitting."""

    has_neuromuscular: bool
    has_glycolytic: bool
    has_vo2max: bool
    has_threshold: bool
    n_anchors: int
    vlamax_reliable: bool
    vo2max_reliable: bool
    mlss_reliable: bool
    fatmax_reliable: bool

    @classmethod
    def from_mmp(cls, mmp: Dict[int, float]) -> "ExpressivenessReport":
        durations = sorted(mmp.keys())
        has_neuro = any(5 <= d <= 15 for d in durations)
        has_glyco = any(20 <= d <= 60 for d in durations)
        has_vo2 = any(180 <= d <= 720 for d in durations)
        has_thr = any(1200 <= d <= 3600 for d in durations)
        return cls(
            has_neuromuscular=has_neuro,
            has_glycolytic=has_glyco,
            has_vo2max=has_vo2,
            has_threshold=has_thr,
            n_anchors=len(durations),
            vlamax_reliable=has_glyco,
            vo2max_reliable=has_vo2 and has_thr,
            mlss_reliable=has_thr,
            fatmax_reliable=has_glyco and has_thr,
        )

    @property
    def fully_expressive(self) -> bool:
        return (
            self.vlamax_reliable
            and self.vo2max_reliable
            and self.mlss_reliable
            and self.fatmax_reliable
        )

    def to_dict(self) -> Dict[str, Any]:
        missing = []
        if not self.has_neuromuscular:
            missing.append("neuromuscular (5-15s)")
        if not self.has_glycolytic:
            missing.append("glycolytic (20-60s)")
        if not self.has_vo2max:
            missing.append("vo2max (180-720s)")
        if not self.has_threshold:
            missing.append("threshold (1200-3600s)")

        unreliable = []
        if not self.vlamax_reliable:
            unreliable.append("vlamax")
        if not self.vo2max_reliable:
            unreliable.append("vo2max")
        if not self.mlss_reliable:
            unreliable.append("mlss")
        if not self.fatmax_reliable:
            unreliable.append("fatmax")

        return {
            "coverage": {
                "neuromuscular_5_15s": self.has_neuromuscular,
                "glycolytic_20_60s": self.has_glycolytic,
                "vo2max_180_720s": self.has_vo2max,
                "threshold_1200_3600s": self.has_threshold,
            },
            "reliability": {
                "vlamax": self.vlamax_reliable,
                "vo2max": self.vo2max_reliable,
                "mlss": self.mlss_reliable,
                "fatmax": self.fatmax_reliable,
            },
            "n_anchors": self.n_anchors,
            "missing_windows": missing,
            "unreliable_parameters": unreliable,
            "fully_expressive": len(unreliable) == 0,
            "tier": "REFERENCE",
        }
