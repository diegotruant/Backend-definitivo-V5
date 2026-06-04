"""
Metabolic Profiler Engine — PURE PRODUCTION API
Versione: 3.3.1-Tethered + AthleteContext (decoupled context module)
Modulo backend per il Reverse Engineering Fisiologico (MMP -> Fenotipo).
Nessuna dipendenza esterna oltre a numpy e scipy.
"""

import numpy as np
from scipy.optimize import least_squares
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from athlete_context import AthleteContext
from cross_validation_engine import (
    cross_validate_metabolic_profile,
    observed_threshold_power,
)
from metric_contracts import annotate_payload


@dataclass(frozen=True)
class RegularizationWeights:
    vo2_vs_guess: float = 0.5
    vo2_vs_expected_heuristic: float = 0.5
    short_mae_scale: float = 1.8


@dataclass(frozen=True)
class MaderConstants:
    """
    Mader model parameters.
    
    Default values are from Mader & Heck 1986 / Mader 2003. These are
    empirically fitted against a population of trained athletes and
    are NOT universal physiological constants — they're a calibration.
    
    A 2025 Springer review (Nolte et al., EJAP) cites ks1=0.0635, while
    Mader's own work uses ks1=0.0631. The variation reflects how the
    same Hill-equation framework is re-fitted across studies.
    
    For elite endurance athletes with years of structured training, these
    constants may differ measurably due to mitochondrial adaptations and
    glycolytic enzyme expression. Until population-specific calibrations
    exist, the defaults are the best public estimate.
    
    To use different values, pass a custom MaderConstants to MetabolicProfiler:
        custom = MaderConstants(ks1=0.0635, ks2=1.30)
        profiler = MetabolicProfiler(weight=72, mader_constants=custom)
    """
    vo2_basale: float = 3.5
    equiv_o2_la: float = 0.01576
    vol_rel: float = 0.45
    ks1: float = 0.0631   # ox-phos 50% activation (Mader/Heck 1986)
    ks2: float = 1.331    # glycolysis 50% activation (Mader/Heck 1986)
    # Net-production fraction (of peak production rate) that defines the
    # maximal lactate STEADY STATE. MLSS is the highest power at which
    # lactate stays elevated but constant; in this model that corresponds
    # to a small positive net accumulation, NOT the net=0 crossing (which
    # is LT1). Calibrated to 0.05 against real sustained threshold power
    # across multiple athletes. Overridable like the other constants.
    mlss_net_frac: float = 0.05
    eps: float = 1e-9
    softplus_k: float = 120.0

    w_step: float = 10.0
    w_min: float = 50.0

    pcr_multiplier: float = 15.0
    pcr_prior_min: float = 80.0
    pcr_prior_max: float = 280.0
    
    # Provenance label — overwritten when a non-default config is used,
    # so the snapshot can report which calibration was applied.
    _source: str = "mader_heck_1986_default"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "ks1": self.ks1,
            "ks2": self.ks2,
            "vo2_basale": self.vo2_basale,
            "equiv_o2_la": self.equiv_o2_la,
            "vol_rel": self.vol_rel,
            "pcr_multiplier": self.pcr_multiplier,
            "source": self._source,
        }


# =============================================================================
# MMP Expressiveness — physiological coverage of the duration spectrum
# =============================================================================

@dataclass(frozen=True)
class ExpressivenessReport:
    """
    Assesses whether an MMP curve covers the durations needed for a
    reliable fit of each physiological parameter.
    
    Energy-system coverage windows (Buchheit & Laursen, Mader, Coggan):
      - Neuromuscular / alactic: 5s ≤ d ≤ 15s
      - Glycolytic (vLamax-sensitive): 20s ≤ d ≤ 60s
      - VO2max: 180s ≤ d ≤ 480s
      - MLSS/threshold: 1200s ≤ d ≤ 3600s
    
    A parameter cannot be reliably estimated from a curve that is missing
    the corresponding coverage window. The fit will produce a number but
    it's not what the user thinks it is.
    """
    has_neuromuscular: bool       # 5-15s anchor present
    has_glycolytic: bool          # 20-60s anchor present
    has_vo2max: bool              # 180-480s anchor present
    has_threshold: bool           # 1200-3600s anchor present
    
    n_anchors: int
    
    # Which parameters are reliable given the available coverage
    vlamax_reliable: bool         # needs glycolytic
    vo2max_reliable: bool         # needs vo2max + threshold
    mlss_reliable: bool           # needs threshold
    fatmax_reliable: bool         # needs vo2max + threshold (derived from MLSS)
    
    @classmethod
    def from_mmp(cls, mmp: Dict[int, float]) -> "ExpressivenessReport":
        durations = sorted(mmp.keys())
        # Window definitions:
        #   neuromuscular  5-15s    — alactic, sprint anchor
        #   glycolytic    20-60s    — vLamax-informative
        #   vo2max        180-720s  — VO2max-informative
        #                            (extended to 720s so CP12 counts as vo2max
        #                            anchor; classical 3-12min effort range)
        #   threshold    1200-3600s — MLSS-informative
        #                            (classical 20-60min sustained efforts)
        has_neuro = any(5 <= d <= 15 for d in durations)
        has_glyco = any(20 <= d <= 60 for d in durations)
        has_vo2   = any(180 <= d <= 720 for d in durations)
        has_thr   = any(1200 <= d <= 3600 for d in durations)
        
        return cls(
            has_neuromuscular=has_neuro,
            has_glycolytic=has_glyco,
            has_vo2max=has_vo2,
            has_threshold=has_thr,
            n_anchors=len(durations),
            vlamax_reliable=has_glyco,
            vo2max_reliable=has_vo2 and has_thr,
            mlss_reliable=has_thr,
            # FatMax is the power at which fat oxidation peaks, which in
            # the Mader model is computed from MLSS *and* vLamax. So it
            # requires both glycolytic AND threshold coverage to be reliable.
            fatmax_reliable=has_glyco and has_thr,
        )
    
    @property
    def fully_expressive(self) -> bool:
        return (
            self.vlamax_reliable and self.vo2max_reliable
            and self.mlss_reliable and self.fatmax_reliable
        )
    
    def to_dict(self) -> Dict[str, Any]:
        missing = []
        if not self.has_neuromuscular: missing.append("neuromuscular (5-15s)")
        if not self.has_glycolytic: missing.append("glycolytic (20-60s)")
        if not self.has_vo2max: missing.append("vo2max (180-720s)")
        if not self.has_threshold: missing.append("threshold (1200-3600s)")
        
        unreliable = []
        if not self.vlamax_reliable: unreliable.append("vlamax")
        if not self.vo2max_reliable: unreliable.append("vo2max")
        if not self.mlss_reliable: unreliable.append("mlss")
        if not self.fatmax_reliable: unreliable.append("fatmax")
        
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



class MetabolicProfiler:
    def __init__(
        self,
        weight: float,
        context: Optional[AthleteContext] = None,
        mader_constants: Optional[MaderConstants] = None,
    ):
        self.weight = max(40.0, float(weight))
        self.context = context if context is not None else AthleteContext()
        self.const = mader_constants if mader_constants is not None else MaderConstants()
        self.reg = RegularizationWeights()

        fat_pct = float(np.clip(self.context.effective_body_fat(), 3.0, 55.0))
        ffm = self.weight * (1.0 - fat_pct / 100.0)
        self.active_muscle_mass = ffm * self.context.active_muscle_fraction()

    def _coerce_mmp_dict(self, mmp: Dict[Any, Any]) -> Dict[int, float]:
        out: Dict[int, float] = {}
        for k, w in mmp.items():
            if w is None:
                continue
            try:
                wf = float(w)
                if wf <= 0.0:
                    continue
                k_str = str(k).strip().lower()
                if k_str.endswith("s"):
                    sec = int(float(k_str[:-1]))
                elif k_str.endswith("m"):
                    sec = int(float(k_str[:-1]) * 60.0)
                else:
                    sec = int(float(k_str))
                out[sec] = wf
            except (TypeError, ValueError):
                continue
        return dict(sorted(out.items()))

    def _pcr_prior_watts(self) -> float:
        return float(np.clip(
            self.active_muscle_mass * self.const.pcr_multiplier,
            self.const.pcr_prior_min,
            self.const.pcr_prior_max
        ))

    def _metabolic_rates(self, w: np.ndarray, vo2: float, vla: float, eta_base: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        coeff_w_to_vo2 = 10.8 * (0.23 / eta_base)
        vo2_req = self.const.vo2_basale + coeff_w_to_vo2 * (w / self.weight)
        vo2_act = np.minimum(vo2_req, vo2 - self.const.eps)
        denom = np.maximum(self.const.eps, vo2 - vo2_act)
        adp = np.sqrt((self.const.ks1 * vo2_act) / denom)
        vla_prod = vla / (1.0 + (self.const.ks2 / (adp ** 3)))
        vla_elim = (self.const.equiv_o2_la * (vo2_act - self.const.vo2_basale)) / (self.const.vol_rel * 60.0)
        return vo2_act, vla_prod, vla_elim

    def _lactate_kin_tau(self, vo2: float, vla: float) -> float:
        floor = self.context.tau_base_floor()
        tau_base = floor + np.clip(80.0 - vo2, 0.0, 40.0) * 0.4
        return float(np.clip(tau_base + np.clip(vla - 0.30, 0.0, 1.0) * 15.0, 12.0, 65.0))

    def _cap_factor(self, seconds: float) -> float:
        return float(1.5 + 2.5 * np.exp(-seconds / 120.0))

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
        return float(np.clip((vo2 - self.const.vo2_basale) * self.weight / 10.8 * (eta_base / 0.23), 50.0, 2500.0))

    @staticmethod
    def _apr_vlamax_band(mmp: Dict[int, float], map_provisional: float) -> Optional[Tuple[float, float, float]]:
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
        # who can sit near the floor even when a Zwift sprint inflates APR.
        vla_low = float(np.clip(0.10 + 0.12 * max(0.0, apr_ratio - 0.8), 0.10, 0.40))
        vla_high = float(np.clip(0.40 + 0.38 * max(0.0, apr_ratio - 0.8), 0.40, 1.20))
        if vla_high <= vla_low:
            vla_high = vla_low + 0.15
        return (vla_low, vla_high, apr_ratio)

    def _pred_power(self, t: float, la_cap: float, tau: float, map_est: float, w_grid: np.ndarray, vo2_act_grid: np.ndarray, net_grid: np.ndarray) -> float:
        cap_mask = w_grid <= (map_est * self._cap_factor(t))
        if np.count_nonzero(cap_mask) < 10:
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
        w = np.arange(50.0, max(700.0, self.weight * 12.0) + 10.0, 5.0, dtype=float)
        map_est = self._map_estimate(vo2, eta_base)
        vo2_act, p, e = self._metabolic_rates(w, vo2, vla, eta_base)

        valid = vo2_act < (vo2 - 0.1)
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
        w_fat = float(np.mean(w[deficit >= 0.98 * mx])) if mx > 0 else float(w[int(np.argmax(deficit))])

        fat_coef = self.context.fat_oxidation_coefficient()
        cho_coef = self.context.cho_oxidation_coefficient()
        fat_gh = (deficit * self.const.vol_rel / self.const.equiv_o2_la * self.weight / 1000.0) * 60.0 * fat_coef
        cho_gh = ((np.minimum(p, e) * self.const.vol_rel / self.const.equiv_o2_la * self.weight / 1000.0) * 60.0 * cho_coef) + \
                 ((np.maximum(0.0, p - e) * self.const.vol_rel / self.const.equiv_o2_la * self.weight / 1000.0) * 60.0 * cho_coef)

        return w_mlss, w_fat, w, fat_gh, cho_gh

    def _generate_zones(self, w_mlss: float, map_w: float) -> List[Dict[str, Any]]:
        return [
            {"name": "Z1 - Recupero", "minWatt": 0, "maxWatt": round(w_mlss * 0.55)},
            {"name": "Z2 - Endurance", "minWatt": round(w_mlss * 0.55) + 1, "maxWatt": round(w_mlss * 0.75)},
            {"name": "Z3 - Tempo", "minWatt": round(w_mlss * 0.75) + 1, "maxWatt": round(w_mlss * 0.90)},
            {"name": "Z4 - Soglia (MLSS)", "minWatt": round(w_mlss * 0.90) + 1, "maxWatt": round(w_mlss * 1.05)},
            {"name": "Z5 - VO2max", "minWatt": round(w_mlss * 1.05) + 1, "maxWatt": round(map_w)},
        ]

    def _classify_metabolic_phenotype(self, vlamax: float) -> dict:
        endurance_max, allrounder_max = self.context.phenotype_thresholds()
        if vlamax < endurance_max:
            return {"category": "Endurance (Diesel)", "level": "Bassa", "description": "Ideale per endurance pura. Consuma pochi carboidrati, ottima efficienza."}
        elif vlamax <= allrounder_max:
            return {"category": "All-Rounder (Passista)", "level": "Media", "description": "Profilo bilanciato. Ottima resistenza e capacità di gestire cambi di ritmo."}
        else:
            return {"category": "Sprinter (Esplosivo)", "level": "Alta", "description": "Motore glicolitico. Eccellente potenza esplosiva, consuma molti carboidrati."}

    def generate_metabolic_snapshot(
        self,
        mmp_raw: Dict[Any, Any],
        expected_eta: Optional[float] = None,
        measured_lacap: Optional[float] = None,
        mmp_samples: Optional[List[Dict[str, Any]]] = None,
        clean_mmp_first: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate a metabolic snapshot from a power-duration curve (MMP).
        
        Parameters
        ----------
        mmp_raw : dict
            {duration_s_or_str: power_w}. Same as before.
        expected_eta : float, optional
            Override the η resolved from athlete context.
        measured_lacap : float, optional
            Override the inferred lactate capacity.
        mmp_samples : list, optional
            Per-sample provenance: [{duration_s, power_w, filename, date}, ...].
            Used only when clean_mmp_first=True for rolling-window detection.
        clean_mmp_first : bool, default False
            If True, run engines.mmp_quality.clean_mmp() on the input before
            fitting. Drops identical plateaus and rolling-window redundant
            anchors. The audit (which anchors were dropped, what warnings
            remain) is included in the output under "mmp_quality".
        """
        mmp_quality_audit: Optional[Dict[str, Any]] = None
        
        if clean_mmp_first:
            # Local import to avoid hard dependency if user never enables this
            from mmp_quality import analyze_mmp_quality, clean_mmp
            cleaned_dict, mmp_quality_audit = clean_mmp(mmp_raw, mmp_samples)
            mmp = cleaned_dict
            # Add the full report (quality_score, classification, issues)
            full_report = analyze_mmp_quality(mmp_raw, mmp_samples)
            mmp_quality_audit["analysis"] = full_report.to_dict()
        else:
            mmp = self._coerce_mmp_dict(mmp_raw)
        
        # ====================================================================
        # Expressiveness gate (v3.5.0)
        # Before fitting, check that the MMP covers the duration windows
        # required for each parameter. If coverage is missing for a
        # parameter, the corresponding estimate will be flagged unreliable
        # in the output, instead of silently producing a number that
        # depends on a non-existent anchor.
        # ====================================================================
        expressiveness = ExpressivenessReport.from_mmp(mmp)
        
        if len(mmp) < 3:
            return self._finalize_snapshot(
                {"status": "error", "message": "Insufficient MMP anchors. At least 3 durations required."},
                mmp_quality_audit,
            )

        # The Mader model describes the aerobic + glycolytic response; it does
        # not model the pure-alactic (PCr) sprint, so anchors below ~30 s are
        # mispredicted by hundreds of watts and, left in the fit, dominate the
        # residual and drag the optimizer into non-physiological basins. We
        # keep the full curve for APR (which *needs* the sprint anchor) but fit
        # only durations >= sprint_fit_floor_s. If too few remain, we relax the
        # floor so the fit still has >= 3 anchors.
        sprint_fit_floor_s = 30.0
        all_durs = np.array(list(mmp.keys()), dtype=float)
        all_pows = np.array(list(mmp.values()), dtype=float)
        fit_mask = all_durs >= sprint_fit_floor_s
        if int(np.count_nonzero(fit_mask)) < 3:
            fit_mask = np.ones_like(all_durs, dtype=bool)  # relax: too little data
            sprint_fit_floor_s = 0.0
        durs_u = all_durs[fit_mask]
        pows_u = all_pows[fit_mask]

        logt = np.log(np.maximum(durs_u, 1.0))
        weights = 0.35 + 0.65 * (
            np.exp(-0.5 * ((logt - np.log(360.0)) / 0.8) ** 2)
            * np.clip(durs_u / 20.0, 0.25, 1.0)
            * np.clip(900.0 / np.maximum(durs_u, 900.0), 0.6, 1.0)
        )
        weights /= np.max(weights)

        vo2_guess = float(np.clip(max(35.0, min(85.0, (pows_u[int(np.argmax(weights))] / self.weight) * 12.0)), 25.0, 95.0))

        if expected_eta is None:
            expected_eta = self.context.expected_eta()
        fixed_eta = float(np.clip(expected_eta, 0.18, 0.28))
        fixed_pcr = self._pcr_prior_watts()
        vla_init = self.context.vlamax_initial_guess()

        w_grid = np.arange(self.const.w_min, max(2000.0, self.weight * 30.0) + self.const.w_step, self.const.w_step, dtype=float)

        # Aerobic floor: the long-duration power the athlete actually
        # sustained sets a hard physiological lower bound on VO2max. MLSS
        # power demands a certain aerobic supply, and VO2max must exceed it.
        # We compute this from the OBSERVED threshold-window power (a direct
        # measurement, not a model output) and use it to keep the optimizer
        # out of the degenerate basin where it trades a too-low VO2max
        # against an inflated VLamax. (This basin exists for some weight/
        # curve combinations and produced non-physical fits, e.g. an
        # 88 kg athlete sustaining 265 W for 1 h fitting to VO2max≈30.)
        mmp_for_obs = {int(d): float(p) for d, p in zip(durs_u, pows_u) if p > 0}
        obs_thr = observed_threshold_power(mmp_for_obs)
        coeff_w_to_vo2 = 10.8 * (0.23 / fixed_eta)
        if obs_thr is not None and obs_thr > 0:
            # Aerobic demand of sustained threshold power (+ small margin,
            # since VO2max sits above MLSS). Uses the same observable as
            # cross_validation_engine (longest threshold-window effort).
            vo2_floor = self.const.vo2_basale + coeff_w_to_vo2 * (obs_thr / self.weight) * 1.05
        else:
            vo2_floor = 0.0
        mlss_ratio_ceiling = 1.10

        def cost_fn(x: np.ndarray) -> np.ndarray:
            vo2, vla = map(float, x)
            la_cap = float(np.clip(10.0 + (vla - 0.2) * 15.0, 8.0, 30.0)) if measured_lacap is None else measured_lacap

            tau, map_est, vo2_act, net = self._compute_grid_state(vo2, vla, fixed_eta, w_grid)
            preds = np.array([
                self._pred_power(t, la_cap, tau, map_est, w_grid, vo2_act, net)
                for t in durs_u
            ]) + (fixed_pcr * np.exp(-np.maximum(0.0, durs_u - 20.0) / 35.0))

            resid = (preds - pows_u) * weights
            # Fixed-length regularization block: scipy.least_squares requires
            # the same residual dimension on every cost_fn evaluation.
            vo2_floor_pen = (
                (vo2_floor - vo2) * 5.0 if (vo2_floor > 0.0 and vo2 < vo2_floor) else 0.0
            )

            mlss_ceiling_pen = 0.0
            if obs_thr is not None and obs_thr > 0:
                w_mlss_pred, _, _, _, _ = self._calculate_curves(vo2, vla, fixed_eta)
                ratio = float(w_mlss_pred) / obs_thr
                if ratio > mlss_ratio_ceiling:
                    mlss_ceiling_pen = (ratio - mlss_ratio_ceiling) * 55.0

            short_mae_pen = 0.0
            if np.any(durs_u <= 30.0):
                short_mae_pen = (
                    float(np.mean(np.abs(preds[durs_u <= 30.0] - pows_u[durs_u <= 30.0])))
                    * self.reg.short_mae_scale
                )

            reg = [
                (vo2 - vo2_guess) * self.reg.vo2_vs_guess,
                (vo2 - (3.5 + (10.8 * (0.23 / fixed_eta)) * (pows_u[int(np.argmax(weights))] / self.weight)))
                * self.reg.vo2_vs_expected_heuristic,
                vo2_floor_pen,
                mlss_ceiling_pen,
                short_mae_pen,
            ]
            return np.concatenate([resid, np.array(reg)])

        def _fit_from(x0):
            return least_squares(
                cost_fn, x0, bounds=([25.0, 0.10], [95.0, 1.50]), loss="soft_l1"
            )

        try:
            # APR-based VLamax band. The Anaerobic Power Reserve (sprint power
            # minus MAP) tells us which VLamax basin is physiologically
            # admissible. We use a provisional MAP from the aerobic guess to
            # compute it, then prefer the lowest-cost fit whose VLamax lands
            # inside that band — which removes the diesel/sprinter ambiguity
            # the plain lowest-cost rule suffered from.
            map_provisional = self._map_estimate(vo2_guess, fixed_eta)
            apr_band = self._apr_vlamax_band(
                {int(d): float(p) for d, p in zip(all_durs, all_pows) if p > 0},
                map_provisional,
            )

            # Dense, deterministic 2-D start mesh (VO2max x VLamax) so the
            # optimizer visits every physiological basin regardless of how the
            # context-derived guesses land. Without VO2max diversity the fit
            # could miss the MLSS-coherent basin when eta shifts the surface.
            vla_starts = [0.20, 0.35, 0.50, 0.70, 0.90]
            if apr_band is not None:
                vla_lo, vla_hi, _ = apr_band
                vla_starts.append(float(np.clip((vla_lo + vla_hi) / 2.0, 0.10, 1.30)))
            vo2_anchor = float(np.clip(vo2_guess, 25.0, 95.0))
            vo2_floor_start = float(np.clip(max(vo2_floor, vo2_guess) + 5.0, 25.0, 95.0))
            vo2_starts = sorted(set([
                vo2_anchor,
                vo2_floor_start,
                float(np.clip(vo2_anchor - 6.0, 25.0, 95.0)),
                float(np.clip(vo2_anchor + 8.0, 25.0, 95.0)),
            ]))
            start_points = [[vo2c, vlac] for vo2c in vo2_starts for vlac in vla_starts]

            candidates = []  # (cost, vla, vo2, result)
            for x0 in start_points:
                x0c = [float(np.clip(x0[0], 25.0, 95.0)), float(np.clip(x0[1], 0.10, 1.50))]
                try:
                    r = _fit_from(x0c)
                except Exception:
                    continue
                c = float(np.sum(r.fun ** 2))
                candidates.append((c, float(r.x[1]), float(r.x[0]), r))

            if not candidates:
                raise RuntimeError("all starts failed")

            # Basin selection. Two physiological anchors disambiguate the
            # multiple minima of the joint fit:
            #   1. APR band  -> which VLamax range is admissible (sprint-driven)
            #   2. observed threshold power -> what MLSS the athlete actually
            #      sustained, so we reject basins whose predicted MLSS drifts
            #      far from a directly-measured long effort.
            # We score in-band candidates by fit cost plus an MLSS-incoherence
            # penalty, and pick the minimum. This is deterministic and stops
            # the fit from jumping between a diesel and a sprinter solution on
            # the same curve.
            def _basin_score(cost: float, vo2c: float, vlac: float) -> float:
                penalty = 0.0
                if obs_thr is not None and obs_thr > 0:
                    w_mlss_c, _, _, _, _ = self._calculate_curves(vo2c, vlac, fixed_eta)
                    mlss_err = abs(float(w_mlss_c) - obs_thr) / obs_thr
                    penalty += (mlss_err ** 2) * 1.0e6  # MLSS must track observed effort
                # Weak tie-break only: when MLSS and cost genuinely fail to
                # discriminate, nudge toward the APR band centre. Kept small so
                # it never overrides a real cost/MLSS signal (which would bias
                # genuine diesels upward).
                if apr_band is not None:
                    vla_centre = 0.5 * (apr_band[0] + apr_band[1])
                    penalty += ((vlac - vla_centre) ** 2) * 2.0e3
                return cost + penalty

            apr_gated = False
            pool = candidates
            if apr_band is not None:
                vla_lo, vla_hi, _ = apr_band
                in_band = [t for t in candidates if vla_lo <= t[1] <= vla_hi]
                if in_band:
                    pool = in_band
                    apr_gated = True

            best_cost, _, _, best_res = min(
                pool, key=lambda t: _basin_score(t[0], t[2], t[1])
            )
            res = best_res
            vo2, vla = map(float, res.x)

            final_lacap = float(np.clip(10.0 + (vla - 0.2) * 15.0, 8.0, 30.0)) if measured_lacap is None else measured_lacap
            w_mlss, w_fat, w_plot, fat_gh, cho_gh = self._calculate_curves(vo2, vla, fixed_eta)
            map_w = self._map_estimate(vo2, fixed_eta)

            tau, map_est, vo2_act, net = self._compute_grid_state(vo2, vla, fixed_eta, w_grid)
            preds = np.array([
                self._pred_power(t, final_lacap, tau, map_est, w_grid, vo2_act, net)
                for t in durs_u
            ]) + (fixed_pcr * np.exp(-np.maximum(0.0, durs_u - 20.0) / 35.0))

            rel_err = float(np.sqrt(np.mean((preds - pows_u) ** 2))) / max(float(np.mean(pows_u)), 1.0)
            confidence = float(np.clip((1.0 - (np.clip(rel_err, 0.0, 0.25) / 0.25)), 0.05, 1.0))

            step = max(1, len(w_plot) // 40)
            combustion_curve = [
                {
                    "watt": int(w_plot[i]),
                    "fatOxidation": round(float(fat_gh[i]), 1),
                    "carbOxidation": round(float(cho_gh[i]), 1)
                }
                for i in range(0, len(w_plot), step)
            ]

            # Apply expressiveness gating to the output values
            # If the MMP does not cover the window needed for a parameter,
            # set it to None and add a flag. The estimate is preserved
            # in the `unmasked_estimates` field for debugging.
            
            unmasked = {
                "estimated_vo2max": round(vo2, 1),
                "estimated_vlamax_mmol_L_s": round(vla, 4),
                "mlss_power_watts": round(w_mlss, 1),
                "mlss_power_wkg": round(w_mlss / self.weight, 2),
                "fatmax_power_watts": round(w_fat, 1),
                "map_aerobic_watts": round(map_w, 1),
            }
            
            vo2_out = unmasked["estimated_vo2max"] if expressiveness.vo2max_reliable else None
            vla_out = unmasked["estimated_vlamax_mmol_L_s"] if expressiveness.vlamax_reliable else None
            mlss_out = unmasked["mlss_power_watts"] if expressiveness.mlss_reliable else None
            mlss_wkg_out = unmasked["mlss_power_wkg"] if expressiveness.mlss_reliable else None
            fatmax_out = unmasked["fatmax_power_watts"] if expressiveness.fatmax_reliable else None
            
            # Confidence-of-derivation: if any flagship parameter is unreliable,
            # global confidence cannot exceed what the weakest produces.
            if not expressiveness.fully_expressive:
                # Halve the global confidence to reflect masked outputs
                confidence_effective = min(confidence, 0.40)
            else:
                confidence_effective = confidence

            cv_result = cross_validate_metabolic_profile(
                self, mmp, vo2, vla, eta_base=fixed_eta,
            )
            if cv_result.coherence_penalty > 0:
                confidence_effective = float(np.clip(
                    confidence_effective * (1.0 - cv_result.coherence_penalty),
                    0.05,
                    1.0,
                ))

            return self._finalize_snapshot({
                "status": "success",
                "estimated_vo2max": vo2_out,
                "estimated_vlamax_mmol_L_s": vla_out,
                "metabolic_phenotype": self._classify_metabolic_phenotype(vla)
                                       if expressiveness.vlamax_reliable else None,
                "assumed_la_capacity_mmol_L": round(final_lacap, 1),
                "mlss_power_watts": mlss_out,
                "mlss_power_wkg": mlss_wkg_out,
                "fatmax_power_watts": fatmax_out,
                "map_aerobic_watts": round(map_w, 1),  # always shown; deterministic from MMP
                "anaerobic_power_reserve": (
                    {
                        "apr_ratio": round(apr_band[2], 2),
                        "vlamax_band": [round(apr_band[0], 2), round(apr_band[1], 2)],
                        "basin_gated_by_apr": apr_gated,
                    } if apr_band is not None else None
                ),
                "confidence_score": round(confidence_effective, 3),
                "cross_validation": cv_result.to_dict(),
                "expressiveness": expressiveness.to_dict(),
                "unmasked_estimates": unmasked,    # for debugging / audit
                "context_used": {
                    "gender": self.context.effective_gender(),
                    "training_years": self.context.effective_training_years(),
                    "discipline": self.context.effective_discipline(),
                    "body_fat_pct": round(self.context.effective_body_fat(), 1),
                    "resolved_eta": round(fixed_eta, 4),
                    "vlamax_initial_guess": round(vla_init, 3),
                    "phenotype_thresholds": list(self.context.phenotype_thresholds()),
                    "fat_ox_coefficient": self.context.fat_oxidation_coefficient(),
                    "cho_ox_coefficient": self.context.cho_oxidation_coefficient(),
                    "inferred_fields": self.context.inferred_fields(),
                    "mader_constants": self.const.to_dict(),  # for reproducibility
                },
                "zones": self._generate_zones(w_mlss, map_w) if expressiveness.mlss_reliable else None,
                "combustion_curve": combustion_curve if expressiveness.vlamax_reliable else None,
                "calculated_at": datetime.now().isoformat()
            }, mmp_quality_audit)
        except Exception as e:
            return self._finalize_snapshot(
                {"status": "error", "message": str(e)},
                mmp_quality_audit,
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
    ) -> Dict[str, Any]:
        """
        Estimate VLamax from an all-out sprint, Mader-based lactate decomposition.

        This is the direct, gold-standard way to get VLamax: a maximal sprint
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

        # Sprint validity gate. The decomposition only works on a genuine
        # all-out sprint where power is *sustained* near the peak. If the 1 s
        # peak towers over the mean (e.g. a 1 s spike on Zwift, not a real
        # seated 15-20 s effort), the alactic estimate swallows the whole
        # mean and the glycolytic remainder goes to zero or negative — a
        # garbage VLamax. We detect that and refuse, rather than return 0.05.
        sustain_ratio = p_mean_sprint / p_peak_1s
        # A real maximal sprint holds >= ~62% of 1 s peak over 10 s, less for
        # longer windows. Threshold scales down with duration.
        min_sustain = 0.70 - 0.012 * sprint_duration_s  # 10s->0.58, 20s->0.46
        if sustain_ratio < max(0.40, min_sustain):
            return {
                "status": "insufficient_sprint",
                "message": (
                    f"Sprint not maximal/sustained enough for VLamax estimation "
                    f"(mean/peak={sustain_ratio:.2f}, need >= {max(0.40, min_sustain):.2f}). "
                    f"The 1 s peak ({p_peak_1s:.0f} W) likely a momentary spike, not a "
                    f"true all-out effort. Provide a dedicated maximal sprint."
                ),
                "sustain_ratio": round(sustain_ratio, 3),
            }

        amm = active_muscle_mass_kg if active_muscle_mass_kg is not None else self.active_muscle_mass
        vo2_power = vo2max_power_w if vo2max_power_w is not None else self._map_estimate(
            self.context.vlamax_initial_guess() and 50.0 or 50.0, self.context.expected_eta()
        )
        eta = self.context.expected_eta()
        J_PER_MMOL_LACTATE_PER_KG = 63.0  # Mader-consistent energetic equivalent

        def _vlamax_for_tau(tau_alac: float) -> float:
            t = sprint_duration_s
            alac_frac_avg = tau_alac / t * (1.0 - np.exp(-t / tau_alac))
            p_alac_avg = (p_peak_1s * 0.98) * alac_frac_avg
            aero_frac = 1.0 - tau_aerobic_s / t * (1.0 - np.exp(-t / tau_aerobic_s))
            p_aero_avg = vo2_power * aero_frac * 0.5  # VO2 not at steady state
            p_glyc = max(0.0, p_mean_sprint - p_alac_avg - p_aero_avg)
            glyc_metabolic_rate = p_glyc / eta
            return glyc_metabolic_rate / (J_PER_MMOL_LACTATE_PER_KG * amm)

        vlamax_raw = _vlamax_for_tau(tau_alactic_s)
        if vlamax_raw < 0.08:
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

        vlamax = float(np.clip(vlamax_raw, 0.05, 1.50))
        # Sensitivity band from plausible tau_alactic range (12-20 s).
        vla_hi = float(np.clip(_vlamax_for_tau(12.0), 0.05, 1.50))
        vla_lo = float(np.clip(_vlamax_for_tau(20.0), 0.05, 1.50))

        return {
            "status": "success",
            "vlamax_mmol_l_s": round(vlamax, 3),
            "vlamax_range": [round(min(vla_lo, vla_hi), 3), round(max(vla_lo, vla_hi), 3)],
            "method": "sprint_decomposition_mader",
            "inputs": {
                "p_peak_1s": p_peak_1s,
                "p_mean_sprint": p_mean_sprint,
                "sprint_duration_s": sprint_duration_s,
                "vo2max_power_w": round(vo2_power, 1),
                "tau_alactic_s": tau_alactic_s,
                "active_muscle_mass_kg": round(amm, 2),
            },
            "note": (
                "VLamax is sensitive to the alactic time constant; the range "
                "reflects tau_alactic 12-20 s. A measured/structured sprint "
                "protocol narrows this."
            ),
        }

    def generate_metabolic_snapshot_segmented(
        self,
        mmp_raw: Dict[Any, Any],
        aerobic_min_duration_s: float = 120.0,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Domain-separated metabolic snapshot for bimodal phenotypes.

        A single joint fit over the whole power-duration curve forces one
        VO2max to reconcile both an extreme sprint (e.g. 1000+ W at 5 s) and
        a long aerobic effort. For riders whose sprint and aerobic systems
        are very differently developed, that joint fit drags the aerobic
        estimates (MLSS, VO2max) toward the sprint and produces a misleadingly
        low threshold.

        This method fits the two physiological domains separately:

          * Aerobic domain (durations >= aerobic_min_duration_s):
            determines VO2max, MLSS, FatMax, MAP. These are not contaminated
            by the alactic/glycolytic excess of the short efforts.
          * Anaerobic domain (full curve, short anchors dominant):
            determines VLamax and the phenotype classification.

        The two are then merged: aerobic parameters from stage 1, VLamax and
        phenotype from stage 2. The output carries `fit_method: "segmented"`
        and a `segmented_detail` block documenting which anchors fed each
        stage, so the separation is auditable rather than hidden.

        Falls back transparently to the joint fit if the aerobic region has
        too few anchors (< 3 durations >= aerobic_min_duration_s).
        """
        mmp = self._coerce_mmp_dict(mmp_raw)
        aero_mmp = {d: w for d, w in mmp.items() if d >= aerobic_min_duration_s}

        # Not enough long-duration data to isolate the aerobic domain — the
        # joint fit is the honest answer here.
        if len(aero_mmp) < 3:
            joint = self.generate_metabolic_snapshot(mmp_raw, **kwargs)
            if isinstance(joint, dict) and joint.get("status") == "success":
                joint["fit_method"] = "joint_fallback"
                joint["segmented_detail"] = {
                    "reason": "insufficient_aerobic_anchors",
                    "aerobic_anchors": sorted(aero_mmp.keys()),
                    "aerobic_min_duration_s": aerobic_min_duration_s,
                }
            return joint

        # Stage 1 — aerobic domain → VO2max, MLSS, FatMax, MAP
        aero_snap = self.generate_metabolic_snapshot(aero_mmp, **kwargs)
        if aero_snap.get("status") != "success":
            return aero_snap  # propagate the error as-is

        # Stage 2 — full curve → VLamax + phenotype (short anchors dominate)
        full_snap = self.generate_metabolic_snapshot(mmp, **kwargs)

        merged = dict(aero_snap)  # aerobic params win for VO2max/MLSS/FatMax/MAP
        if full_snap.get("status") == "success":
            merged["estimated_vlamax_mmol_L_s"] = full_snap.get("estimated_vlamax_mmol_L_s")
            merged["metabolic_phenotype"] = full_snap.get("metabolic_phenotype")
            merged["assumed_la_capacity_mmol_L"] = full_snap.get("assumed_la_capacity_mmol_L")
            merged["combustion_curve"] = full_snap.get("combustion_curve")

        merged["fit_method"] = "segmented"
        merged["segmented_detail"] = {
            "aerobic_anchors": sorted(aero_mmp.keys()),
            "anaerobic_anchors": sorted(mmp.keys()),
            "aerobic_min_duration_s": aerobic_min_duration_s,
            "vo2max_source": "aerobic_domain",
            "mlss_source": "aerobic_domain",
            "vlamax_source": "full_curve",
            "joint_vo2max": full_snap.get("estimated_vo2max") if full_snap.get("status") == "success" else None,
            "joint_mlss_power_watts": full_snap.get("mlss_power_watts") if full_snap.get("status") == "success" else None,
        }
        return merged

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
        bimodal_threshold: float = 4.2,
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
        mmp = self._coerce_mmp_dict(mmp_raw)
        ratio = self._bimodality_ratio(mmp)

        if ratio is not None and ratio >= bimodal_threshold:
            snap = self.generate_metabolic_snapshot_segmented(mmp_raw, **kwargs)
            snap["bimodality_ratio"] = round(ratio, 2)
            snap["fit_strategy_reason"] = (
                f"bimodal (P_short/P_long={ratio:.2f} >= {bimodal_threshold}): "
                f"segmented to keep sprint from distorting aerobic estimate"
            )
            return snap

        snap = self.generate_metabolic_snapshot(mmp_raw, **kwargs)
        if isinstance(snap, dict) and snap.get("status") == "success":
            snap["fit_method"] = "joint_auto"
            snap["bimodality_ratio"] = round(ratio, 2) if ratio is not None else None
            snap["fit_strategy_reason"] = (
                f"unimodal (P_short/P_long={ratio:.2f} < {bimodal_threshold}): "
                f"joint fit already coherent"
                if ratio is not None else
                "insufficient anchors to judge bimodality; joint fit used"
            )
        return snap

    @staticmethod
    def _finalize_snapshot(snap: Dict[str, Any], audit: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Attach the MMP quality audit if it was produced."""
        if audit is not None:
            snap["mmp_quality"] = audit
        annotate_payload(
            snap,
            module_name="metabolic_profiler",
            method="mader_least_squares",
            confidence_field="confidence_score",
            limitations=(
                ["One or more metabolic outputs were masked by expressiveness gates."]
                if snap.get("expressiveness", {}).get("fully_expressive") is False
                else []
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
        from metabolic_profiler_phenotype import enhance_metabolic_snapshot_with_phenotype
        return enhance_metabolic_snapshot_with_phenotype(
            snapshot,
            phenotype=phenotype,
            weight_kg=self.weight,
            power_30s=power_30s,
            power_1200s=power_1200s,
        )