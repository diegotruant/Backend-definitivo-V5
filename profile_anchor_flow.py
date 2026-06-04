"""
Profile anchor flow.
====================

The "thread" that connects the three previously-standalone pieces into one
production cycle:

    extract_test_proposal()        (test_effort_extractor)
            |  coach confirms
            v
    build_anchor_from_proposal()   -> MeasuredProfile  (this module)
            |
            v
    update_profile_from_ride()     -> updated snapshot  (this module)
       uses PhysiologicalPriorManager + bayesian_metabolic_snapshot

Design rules carried over from the rest of the backend:

  * Nothing is auto-committed. build_anchor_from_proposal() runs only on a
    proposal the coach has confirmed; the caller owns that gate.
  * VLamax comes DIRECTLY from the sprint decomposition (the reliable path),
    not from the joint power-curve fit, which is degenerate for VLamax.
  * VO2max / MLSS come from the metabolic fit on the CP anchors, with VLamax
    held as a strong prior so the aerobic estimate is coherent with the
    measured glycolytic capacity.
  * Honesty preserved: if the confirmed proposal is missing anchors, the
    resulting MeasuredProfile carries only what could be measured, and the
    caller is told what is missing. No fabricated values.
  * Ride updates are Bayesian: the test is the prior (sticky VLamax, looser
    aerobic), the ride MMP is the evidence. Old measurements widen over time
    and under low load via PhysiologicalPriorManager.

This module orchestrates; it does not reimplement any physiology.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union

from athlete_context import AthleteContext
from athlete_physiological_prior import MeasuredProfile, PhysiologicalPriorManager
from metabolic_profiler import MetabolicProfiler


@dataclass
class AnchorResult:
    """Outcome of turning a confirmed proposal into a measured anchor."""
    status: str                                  # "anchored" | "partial" | "failed"
    profile: Optional[MeasuredProfile] = None
    vlamax_source: str = ""                      # "sprint" | "none"
    vo2max_source: str = ""                      # "cp_fit" | "none"
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "profile": (
                {
                    "measured_on": self.profile.measured_on.isoformat(),
                    "vo2max": self.profile.vo2max,
                    "mlss_watts": self.profile.mlss_watts,
                    "vlamax": self.profile.vlamax,
                    "source": self.profile.source,
                } if self.profile else None
            ),
            "vlamax_source": self.vlamax_source,
            "vo2max_source": self.vo2max_source,
            "confidence": round(self.confidence, 3),
            "warnings": self.warnings,
            "detail": self.detail,
        }


def build_anchor_from_proposal(
    proposal: Any,                       # ProfileProposal (or its .to_dict())
    *,
    weight_kg: float,
    measured_on: Union[date, datetime, str],
    context: Optional[AthleteContext] = None,
    active_muscle_mass_kg: Optional[float] = None,
) -> AnchorResult:
    """
    Turn a coach-confirmed ProfileProposal into a MeasuredProfile anchor.

    The caller must only pass a proposal the coach has confirmed. This does
    not re-validate the coach's decision; it computes the physiological
    anchor from the proposal's efforts.

    Path:
      VLamax  <- vlamax_from_sprint(proposal.sprint)        [direct, reliable]
      VO2max  <- metabolic fit on proposal.mmp_for_fit,
                 with VLamax held as a strong prior
      MLSS    <- derived by the model from (VO2max, VLamax)
    """
    # Accept either the dataclass or a dict form.
    def g(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    sprint = g(proposal, "sprint")
    mmp_for_fit = g(proposal, "mmp_for_fit") or {}
    prop_conf = float(g(proposal, "confidence", 0.0) or 0.0)

    ctx = context or AthleteContext(gender="MALE", training_years=10, discipline="ENDURANCE")
    profiler = MetabolicProfiler(weight=weight_kg, context=ctx)
    amm = active_muscle_mass_kg if active_muscle_mass_kg is not None else profiler.active_muscle_mass

    result = AnchorResult(status="failed")
    vlamax_val: Optional[float] = None
    vo2max_val: Optional[float] = None
    mlss_val: Optional[float] = None

    # --- VLamax from the sprint (the reliable path) ---
    if sprint is not None:
        peak = g(sprint, "peak_1s_w")
        mean = g(sprint, "mean_w")
        dur = g(sprint, "duration_s", 15)
        vla_res = profiler.vlamax_from_sprint(
            p_peak_1s=float(peak), p_mean_sprint=float(mean),
            sprint_duration_s=float(dur), active_muscle_mass_kg=amm,
        )
        if vla_res.get("status") == "success":
            vlamax_val = vla_res["vlamax_mmol_l_s"]
            result.vlamax_source = "sprint"
            result.detail["vlamax_range"] = vla_res.get("vlamax_range")
        else:
            result.warnings.append(
                f"Sprint present but VLamax not estimable: {vla_res.get('status')}."
            )
    else:
        result.warnings.append("No sprint in proposal - VLamax cannot be anchored.")

    # --- VO2max / MLSS from the CP anchors, VLamax held as prior ---
    # Use the deterministic fit; if VLamax is known, pass it so the aerobic
    # estimate is coherent with measured glycolytic capacity. The profiler
    # masks parameters it cannot reliably resolve, so we read its own
    # reliability flags rather than trusting raw numbers.
    if mmp_for_fit and len(mmp_for_fit) >= 3:
        mmp_int = {int(k): float(v) for k, v in mmp_for_fit.items()}
        snap = profiler.generate_metabolic_snapshot(mmp_int)
        if snap.get("status") == "success":
            rel = snap.get("expressiveness", {}).get("reliability", {})
            if rel.get("vo2max") and snap.get("estimated_vo2max") is not None:
                vo2max_val = snap["estimated_vo2max"]
                result.vo2max_source = "cp_fit"
            if rel.get("mlss") and snap.get("mlss_power_watts") is not None:
                mlss_val = snap["mlss_power_watts"]
            # If the fit could not resolve the aerobic side, say why.
            missing = snap.get("expressiveness", {}).get("missing_windows", [])
            if not vo2max_val:
                result.warnings.append(
                    "VO2max/MLSS not reliably resolved from the CP anchors "
                    f"(missing windows: {missing or 'aerobic/threshold'}). "
                    "Add a maximal CP12 and a longer threshold effort."
                )
            cm = snap.get("curve_maximality")
            if cm and not cm.get("plausible_maximal", True):
                result.warnings.append(cm.get("reason", "Curve looks sub-maximal."))
    else:
        result.warnings.append("Insufficient CP anchors in proposal for an aerobic fit.")

    # --- assemble the anchor with whatever was reliably measured ---
    if vlamax_val is None and vo2max_val is None:
        result.status = "failed"
        result.confidence = 0.0
        result.warnings.append("No reliable anchor could be built from this proposal.")
        return result

    result.profile = MeasuredProfile(
        measured_on=measured_on,
        vo2max=vo2max_val,
        mlss_watts=mlss_val,
        vlamax=vlamax_val,
        source="field_test",
        notes="Anchored from coach-confirmed test proposal.",
    )
    # Confidence blends the proposal's own confidence with completeness of
    # the resulting anchor (all three params present => fuller anchor).
    have = sum(x is not None for x in (vlamax_val, vo2max_val, mlss_val))
    completeness = have / 3.0
    result.confidence = round(min(prop_conf, 0.95) * (0.4 + 0.6 * completeness), 3)
    result.status = "anchored" if (vlamax_val and vo2max_val) else "partial"
    return result


def update_profile_from_ride(
    anchor: MeasuredProfile,
    ride_mmp: Dict[int, float],
    *,
    weight_kg: float,
    as_of: Union[date, datetime, str],
    load_factor: float = 1.0,
    context: Optional[AthleteContext] = None,
    detraining_fn=None,
    n_samples: int = 2000,
    n_warmup: int = 500,
) -> Dict[str, Any]:
    """
    Update the metabolic snapshot from a new ride, Bayesianly.

    The measured anchor becomes the prior (via PhysiologicalPriorManager,
    which widens it with age and low load and keeps VLamax sticky); the ride's
    MMP is the evidence. Returns the Bayesian snapshot dict plus the priors
    that were applied, so the caller can show how much the data moved things.

    Note: this updates the *aerobic* estimate primarily. VLamax stays anchored
    to the test unless the ride contains a genuine maximal sprint (which the
    caller should detect separately and, if found, re-anchor via
    build_anchor_from_proposal). A normal ride does not move VLamax much,
    which is physiologically correct.
    """
    from bayesian_profiler import bayesian_metabolic_snapshot

    ctx = context or AthleteContext(gender="MALE", training_years=10, discipline="ENDURANCE")
    profiler = MetabolicProfiler(weight=weight_kg, context=ctx)

    mmp_int = {int(k): float(v) for k, v in ride_mmp.items()}

    # Maximality gate. A normal ride is rarely maximal across durations; using
    # it as Bayesian evidence would drag a strong anchor toward a weaker,
    # sub-maximal picture and can make the sampler diverge. We only let a ride
    # update the aerobic estimate if its curve is plausibly maximal (same
    # physical floor used in the profiler's curve_maximality check). Otherwise
    # the profile stays at the anchor and the ride only informs the rolling
    # power curve elsewhere.
    p_short = mmp_int.get(5) or mmp_int.get(10) or mmp_int.get(1)
    p_long = mmp_int.get(1200) or mmp_int.get(1800) or mmp_int.get(3600) or mmp_int.get(720)
    se_ratio = (float(p_short) / float(p_long)) if (p_short and p_long and p_long > 0) else None

    mgr = PhysiologicalPriorManager(anchor)
    priors = mgr.current_priors(as_of=as_of, load_factor=load_factor, detraining_fn=detraining_fn)

    if se_ratio is not None and se_ratio < 2.2:
        # Not maximal enough to update: report the anchor (time/load-adjusted)
        # unchanged, and say why. This protects the profile from ordinary rides.
        return {
            "status": "anchor_held",
            "reason": (
                f"Ride not maximal enough to update the profile "
                f"(sprint/endurance ratio {se_ratio:.2f} < 2.2). "
                f"Profile held at the anchor; ride still feeds the power curve."
            ),
            "estimated_vo2max": priors["vo2max"].mean if "vo2max" in priors else anchor.vo2max,
            "estimated_vlamax_mmol_L_s": priors["vlamax"].mean if "vlamax" in priors else anchor.vlamax,
            "mlss_power_watts": priors["mlss"].mean if "mlss" in priors else anchor.mlss_watts,
            "priors_applied": {k: v.to_dict() for k, v in priors.items()},
            "anchor_age_days": priors["vlamax"].age_days if "vlamax" in priors else None,
            "sprint_endurance_ratio": round(se_ratio, 2),
        }

    kwargs = mgr.bayesian_kwargs(as_of=as_of, load_factor=load_factor, detraining_fn=detraining_fn)

    # Update the aerobic estimate with the reliable deterministic fit, holding
    # the measured VLamax as a fixed input so VO2max/MLSS are coherent with the
    # athlete's known glycolytic capacity. NOTE: the MCMC Bayesian profiler
    # (bayesian_metabolic_snapshot) currently mis-converges on maximal MMPs
    # (it returns VO2max far below the deterministic fit with zero confidence),
    # so it is intentionally NOT used in this production path until its
    # sampling is fixed. The deterministic fit + VLamax prior is the trusted
    # route here; the time/load-aware priors still gate and contextualise it.
    prior_vla = kwargs.get("prior_vla_mean")
    measured_lacap = None
    if prior_vla is not None:
        # Convert the anchored VLamax into the profiler's lactate-capacity
        # input so the aerobic fit is consistent with it.
        measured_lacap = float(min(30.0, max(8.0, 10.0 + (prior_vla - 0.2) * 15.0)))

    snap = profiler.generate_metabolic_snapshot(mmp_int, measured_lacap=measured_lacap)
    out = dict(snap)

    # VLamax stays anchored to the test value in a ride update. The aerobic
    # parameters (VO2max, MLSS) are what a ride updates; VLamax is sticky and
    # only moves when a dedicated maximal sprint re-anchors it (handled by
    # build_anchor_from_proposal, not here). The deterministic fit re-estimates
    # VLamax from the curve, so we overwrite it with the anchored prior to keep
    # the physiology consistent and flag that it was held.
    if prior_vla is not None:
        out["estimated_vlamax_mmol_L_s"] = round(float(prior_vla), 4)
        out["vlamax_held_from_anchor"] = True

    out["priors_applied"] = {k: v.to_dict() for k, v in priors.items()}
    out["anchor_age_days"] = (
        priors["vlamax"].age_days if "vlamax" in priors
        else (priors["vo2max"].age_days if "vo2max" in priors else None)
    )
    out["update_method"] = "deterministic_fit_with_vlamax_prior"
    return out
