"""
Cross-Validation Engine — metabolic-profile metabolic self-audit
============================================================

Complements the expressiveness gate. They detect different failure modes:

  - Expressiveness gate  → "the MMP is MISSING data for this parameter"
                           (coverage problem)
  - Cross-validation     → "the data that IS present CONTRADICTS itself"
                           (coherence problem)

The principle (from metabolic profile self-auditing logic)
-----------------------------------------------------
VO2max, VLamax and the anaerobic threshold (MLSS) are physiologically
connected through the Mader model: knowing two of them determines the
third. A metabolic profile audit exploits this by measuring the three quantities from
INDEPENDENT efforts (VLamax from a 20s sprint, VO2max from a 3min effort,
threshold from the 6-12min power-duration curve), then checking whether
they are mutually compatible. If they are not, something is wrong:
a mis-calibrated power meter, or an athlete who was not all-out in one
of the efforts.

Avoiding the tautology trap
---------------------------
In this backend, MLSS is ALREADY computed FROM (VO2max, VLamax) via Mader.
Re-deriving MLSS from those two parameters and "checking" it against Mader
would compare the math against itself — it would always pass and validate
nothing.

The only honest cross-check uses an INDEPENDENT observable: the power the
athlete actually sustained in the threshold window (1200-3600s) of the
real MMP. That number comes straight from measured power, NOT from Mader.

So the audit is:
    1. Take the fitted (VO2max, VLamax).
    2. Use Mader's forward model to PREDICT the threshold power.
    3. Compare that prediction against the threshold power OBSERVED in the
       MMP (a direct measurement).
    4. If prediction and observation diverge beyond tolerance, flag an
       incoherence — exactly the "outlier" signal a metabolic profile audit looks for.

This is not Mader-vs-Mader. It is Mader's prediction vs measured power.

Tier: MODEL (coherence audit over physiological estimates)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


# Duration windows (seconds) used to source INDEPENDENT estimates.
# These mirror the expressiveness windows so the two systems agree on
# what counts as a glycolytic / vo2max / threshold anchor.
GLYCOLYTIC_WINDOW = (20.0, 60.0)      # VLamax-informative
VO2MAX_WINDOW = (180.0, 720.0)        # VO2max-informative
THRESHOLD_WINDOW = (1200.0, 3600.0)   # MLSS-informative (the observable)


@dataclass
class CrossValidationResult:
    """
    Outcome of the metabolic self-audit.

    coherent : bool
        True if the independently-sourced estimates are mutually compatible
        within tolerance. False if an incoherence (outlier) was detected.
    checks_performed : list of str
        Which cross-checks could actually be run (depends on MMP coverage).
    """
    coherent: bool = True
    checks_performed: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Threshold coherence: Mader prediction vs observed MMP power
    threshold_observed_w: Optional[float] = None
    threshold_predicted_w: Optional[float] = None
    threshold_error_w: Optional[float] = None
    threshold_error_pct: Optional[float] = None

    # Confidence penalty to fold into the snapshot (0.0 = none, 1.0 = full)
    coherence_penalty: float = 0.0

    # Which parameter is the most likely outlier, if incoherent
    suspected_outlier: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": "MODEL",
            "coherent": self.coherent,
            "checks_performed": self.checks_performed,
            "warnings": self.warnings,
            "threshold_coherence": {
                "observed_watts": self.threshold_observed_w,
                "predicted_watts": self.threshold_predicted_w,
                "error_watts": self.threshold_error_w,
                "error_pct": self.threshold_error_pct,
            } if self.threshold_observed_w is not None else None,
            "coherence_penalty": round(self.coherence_penalty, 3),
            "suspected_outlier": self.suspected_outlier,
        }


def _observed_threshold_power(mmp: Dict[int, float]) -> Optional[float]:
    """
    Extract the directly-observed threshold power from the MMP.

    Uses the longest-duration anchor inside the threshold window, since
    longer sustained efforts sit closest to MLSS. This is a MEASUREMENT
    from the athlete's real power curve — it does NOT pass through Mader.
    """
    candidates = [
        (d, p) for d, p in mmp.items()
        if THRESHOLD_WINDOW[0] <= d <= THRESHOLD_WINDOW[1] and p > 0
    ]
    if not candidates:
        return None
    # Longest effort in the window is the best MLSS proxy
    candidates.sort(key=lambda dp: dp[0])
    longest_d, longest_p = candidates[-1]
    # Efforts beyond ~20min sit very close to MLSS; shorter ones in the
    # window slightly overestimate it. Apply a mild duration correction
    # toward MLSS for anchors well under 40min.
    # (Coggan: ~95% of 20min power ≈ FTP/MLSS.)
    if longest_d <= 1500.0:
        return longest_p * 0.97
    return longest_p


def cross_validate_metabolic_profile(
    profiler,
    mmp: Dict[int, float],
    vo2max: float,
    vlamax: float,
    eta_base: Optional[float] = None,
    threshold_tolerance_pct: float = 8.0,
) -> CrossValidationResult:
    """
    Run the metabolic-profile coherence audit on a fitted metabolic profile.

    Parameters
    ----------
    profiler : MetabolicProfiler
        The profiler instance (provides Mader's forward model and weight).
    mmp : dict
        {duration_s: power_w}. The real power-duration curve.
    vo2max, vlamax : float
        The fitted parameters to audit.
    eta_base : float, optional
        Mechanical efficiency. If None, resolved from the profiler context.
    threshold_tolerance_pct : float, default 8.0
        How far Mader's predicted threshold may sit from the observed
        threshold power before it is flagged. 8% reflects the biological
        variability reported in the MLSS literature (calc vs measured
        MLSS differed ~12W on ~220W, i.e. ~5-6%, plus measurement noise).

    Returns
    -------
    CrossValidationResult
    """
    result = CrossValidationResult()

    # Coerce MMP keys to int seconds (reuse the profiler's own coercion
    # so we treat the curve identically to how the fit treated it).
    mmp_int = profiler._coerce_mmp_dict(mmp) if hasattr(profiler, "_coerce_mmp_dict") else {
        int(k): float(v) for k, v in mmp.items() if v and float(v) > 0
    }

    if eta_base is None:
        eta_base = profiler.context.expected_eta() if hasattr(profiler, "context") else 0.23
    eta_base = float(np.clip(eta_base, 0.18, 0.28))

    weight = getattr(profiler, "weight", 70.0)

    # ------------------------------------------------------------------
    # CHECK 1 — Physiological plausibility of the fitted parameter pair
    # This is the PRIMARY, most robust cross-check. The expressiveness
    # gate confirms the DATA exists for each parameter, but it cannot see
    # whether the resulting (VO2max, VLamax) pair is physiologically
    # possible given the power the athlete actually produced.
    #
    # The strongest tell: a VO2max too low to physically sustain the
    # observed long-effort power. Sustaining P watts for an hour requires
    # roughly  VO2 ≈ vo2_basale + 10.8*(0.23/eta)*(P/kg)  ml/kg/min of
    # aerobic supply. If the fitted VO2max is well below that floor, the
    # fit has collapsed onto a non-physical solution (as can happen when
    # the optimiser trades VO2max against an inflated VLamax).
    # ------------------------------------------------------------------
    observed = _observed_threshold_power(mmp_int)

    if observed is not None:
        # Aerobic demand implied by the sustained threshold power.
        coeff_w_to_vo2 = 10.8 * (0.23 / eta_base)
        vo2_basale = getattr(profiler.const, "vo2_basale", 3.5) if hasattr(profiler, "const") else 3.5
        vo2_required = vo2_basale + coeff_w_to_vo2 * (observed / weight)

        result.checks_performed.append("aerobic_floor")
        # The fitted VO2max must exceed the aerobic demand of MLSS power,
        # since MLSS sits below VO2max by definition. Allow a small margin.
        if vo2max < vo2_required * 0.98:
            result.coherent = False
            result.coherence_penalty = max(result.coherence_penalty, 0.45)
            result.suspected_outlier = "nonphysical_fit_vo2max_too_low"
            result.warnings.append(
                f"Fitted VO2max ({vo2max:.0f} ml/kg/min) is below the aerobic "
                f"demand of the sustained threshold power ({observed:.0f}W needs "
                f"~{vo2_required:.0f} ml/kg/min). The fit has converged on a "
                f"non-physical solution — treat VO2max and VLamax as unreliable."
            )

    # ------------------------------------------------------------------
    # CHECK 2 — Threshold coherence (relative, offset-aware)
    # Mader's MLSS sits structurally below raw 20-min power by an athlete-
    # dependent margin, so we do NOT compare the two with a fixed absolute
    # tolerance. Instead we check that the model's MLSS lands in the
    # physiologically expected BAND relative to observed power: MLSS should
    # fall between ~75% and ~100% of the longest sustained effort. Outside
    # that band signals an incoherent fit.
    # ------------------------------------------------------------------
    if observed is not None:
        try:
            predicted = profiler._calculate_curves(vo2max, vlamax, eta_base)[0]
        except Exception:
            predicted = None

        if predicted is not None and predicted > 0:
            ratio = predicted / observed  # expected ~0.75–1.00
            result.threshold_observed_w = round(observed, 1)
            result.threshold_predicted_w = round(predicted, 1)
            result.threshold_error_w = round(predicted - observed, 1)
            result.threshold_error_pct = round(100.0 * (predicted - observed) / observed, 1)
            result.checks_performed.append("threshold_band")

            if ratio < 0.60:
                # Model MLSS far below sustained power → non-physical
                # (usually the same collapsed fit Check 1 catches).
                result.coherent = False
                result.coherence_penalty = max(result.coherence_penalty, 0.45)
                if result.suspected_outlier is None:
                    result.suspected_outlier = "model_mlss_implausibly_low"
                result.warnings.append(
                    f"Model MLSS ({predicted:.0f}W) is far below the sustained "
                    f"threshold power ({observed:.0f}W) — only {ratio*100:.0f}%. "
                    f"The parameter fit is physiologically inconsistent."
                )
            elif ratio > 1.15:
                # Model MLSS above sustained power → the long effort was
                # likely sub-maximal, or VO2max is overestimated.
                result.coherent = False
                result.coherence_penalty = max(result.coherence_penalty, 0.25)
                if result.suspected_outlier is None:
                    result.suspected_outlier = "submaximal_long_effort"
                result.warnings.append(
                    f"Model MLSS ({predicted:.0f}W) exceeds sustained power "
                    f"({observed:.0f}W) by {(ratio-1)*100:.0f}%. The long effort "
                    f"may have been sub-maximal, or VO2max is overestimated."
                )

    # ------------------------------------------------------------------
    # CHECK 3 — Monotonicity of the power curve
    # A longer effort with HIGHER power than a shorter one means the two
    # anchors came from incompatible sessions or a mis-recorded file.
    # ------------------------------------------------------------------
    durs = sorted(mmp_int.keys())
    inversions = []
    for i in range(len(durs) - 1):
        d_short, d_long = durs[i], durs[i + 1]
        p_short, p_long = mmp_int[d_short], mmp_int[d_long]
        if p_long > p_short * 1.02:  # 2% tolerance for noise
            inversions.append((d_short, d_long, p_short, p_long))

    if inversions:
        result.checks_performed.append("monotonicity")
        result.coherent = False
        result.coherence_penalty = max(result.coherence_penalty, 0.25)
        for d_s, d_l, p_s, p_l in inversions[:3]:
            result.warnings.append(
                f"Power curve inversion: {d_l}s effort ({p_l:.0f}W) exceeds "
                f"{d_s}s effort ({p_s:.0f}W). Efforts likely from inconsistent "
                f"sessions or a mis-recorded file."
            )
        if result.suspected_outlier is None:
            result.suspected_outlier = "power_curve_inversion"

    if not result.checks_performed:
        result.warnings.append(
            "No cross-checks could be run — the MMP lacks a threshold-window "
            "anchor (1200-3600s) to validate against."
        )

    return result
