"""
Lactate Validation Engine — invasive ground-truth calibration
==============================================================

PURPOSE
-------
This module does one thing: takes REAL data from a lactate test
(in-person Mader test with capillary sampling at the end of each step) and
uses it to VALIDATE the non-invasive metabolic model (`MetabolicProfiler`,
which estimates the profile from MMP alone).

This is the ONBOARDING moment for a new athlete. Example: Lorenzo arrives.
The coach performs the lactate test ONCE. From that data the true MLSS is
derived (measured). It is compared with the MLSS that the Mader Python model
predicts from Lorenzo's MMP. If the two values converge, the model is validated
FOR LORENZO: from that point on Lorenzo can be monitored indefinitely without
further blood sampling.

DIFFERENCE from `cross_validation_engine.py`
--------------------------------------------
  - cross_validation_engine  → validates Mader Python WITHOUT lactate, using
                               observed power in the MMP as reference.
                               Used LATER, during continuous monitoring.
  - lactate_validation_engine → validates Mader Python AGAINST real lactate.
                               Used ONCE, at onboarding.

These are two different moments in the athlete lifecycle. They do not overlap.

WHY D-MAX AND NOT A FIXED 4 mmol/L THRESHOLD
--------------------------------------------
Validation only makes sense if the "true" reference comes from mathematics
INDEPENDENT of the model being validated. Mader Python uses Michaelis-Menten
kinetics. If we derived the "true" MLSS with the same model, we would be
comparing the model to itself: null validation.

D-max derives the threshold from the GEOMETRY of the lactate/power curve
(the point farthest from the line joining the first and last point),
without assuming any fixed threshold and without using Michaelis-Menten.
It is therefore a methodologically independent reference — the only honest one.

We still compute the fixed 4 mmol/L threshold (classic Mader OBLA)
because it costs nothing and provides comparability with historical data.

PROTOCOL REQUIREMENT
--------------------
D-max needs at least MIN_LACTATE_STEPS points to be reliable:
with 3 or fewer points the "curve" is too sparse and D-max becomes noise.
The module REJECTS inputs with too few steps and explains why. In practice
this enforces the correct protocol (incremental steps until lactate is
clearly above threshold).

Tier: REFERENCE (lactate measurement is ground truth; the validation
judgment is MODEL).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

# annotate_payload: same function used by other backend modules to
# tag output with module/method/confidence/limitations. The signature is
# inferred from calls in metabolic_profiler.py and metabolic_flexibility_engine.py.
# If metric_contracts is not importable (e.g. in isolated tests), we use a
# fallback that returns the payload unchanged so the module remains usable.
try:
    from engines.core.metric_contracts import annotate_payload
except Exception:  # pragma: no cover
    def annotate_payload(payload, **kwargs):  # type: ignore
        return payload


# =============================================================================
# Method parameters
# =============================================================================

# Minimum number of lactate steps for a reliable D-max.
MIN_LACTATE_STEPS = 5

# Classic fixed OBLA threshold (Mader 1976): lactate = 4 mmol/L.
OBLA_THRESHOLD_MMOL = 4.0
# Classic aerobic threshold (approximate LT1): lactate = 2 mmol/L.
AEROBIC_THRESHOLD_MMOL = 2.0

# Validation tolerance: how far the MLSS predicted by Mader Python may deviate
# from the true MLSS (D-max) before the model is considered NOT validated
# for that athlete. Expressed as a percentage of true MLSS.
# 8% reflects typical biological variability in the MLSS literature.
VALIDATION_TOLERANCE_PCT = 8.0


# =============================================================================
# Data structures
# =============================================================================

@dataclass
class LactateStep:
    """A single step of the lactate test."""
    power_w: float          # mean power held during the step (W)
    lactate_mmol: float     # lactate at end of step (mmol/L)
    hr_mean: Optional[float] = None      # mean HR during the step (bpm)
    cadence_mean: Optional[float] = None # mean cadence (rpm)
    duration_s: Optional[float] = None   # step duration (s)


@dataclass
class LactateThresholds:
    """Thresholds derived from real lactate data (ground truth)."""
    mlss_dmax_w: Optional[float] = None       # MLSS via D-max (primary reference)
    obla_4mmol_w: Optional[float] = None       # classic 4 mmol/L threshold
    aerobic_2mmol_w: Optional[float] = None    # 2 mmol/L threshold (approximate LT1)
    dmax_lactate_at_threshold: Optional[float] = None  # lactate at D-max point

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mlss_dmax_watts": self.mlss_dmax_w,
            "obla_4mmol_watts": self.obla_4mmol_w,
            "aerobic_2mmol_watts": self.aerobic_2mmol_w,
            "lactate_at_dmax_mmol": self.dmax_lactate_at_threshold,
        }


# =============================================================================
# Threshold computation from lactate data
# =============================================================================

def _sorted_steps(steps: List[LactateStep]) -> Tuple[np.ndarray, np.ndarray]:
    """Return (powers, lactates) sorted by ascending power."""
    pairs = sorted(
        ((s.power_w, s.lactate_mmol) for s in steps if s.power_w > 0 and s.lactate_mmol > 0),
        key=lambda x: x[0],
    )
    powers = np.array([p for p, _ in pairs], dtype=float)
    lacts = np.array([l for _, l in pairs], dtype=float)
    return powers, lacts


def _interpolate_power_at_lactate(
    powers: np.ndarray, lacts: np.ndarray, target_lactate: float
) -> Optional[float]:
    """
    Find the power at which lactate reaches `target_lactate`,
    by linear interpolation between the two enclosing steps.
    Returns None if the threshold is not crossed by the data.
    """
    for i in range(len(powers) - 1):
        l0, l1 = lacts[i], lacts[i + 1]
        if (l0 <= target_lactate <= l1) or (l1 <= target_lactate <= l0):
            if abs(l1 - l0) < 1e-9:
                return float(powers[i])
            frac = (target_lactate - l0) / (l1 - l0)
            return float(powers[i] + frac * (powers[i + 1] - powers[i]))
    return None


def _dmax_threshold(
    powers: np.ndarray, lacts: np.ndarray
) -> Tuple[Optional[float], Optional[float]]:
    """
    Modified D-max.

    Builds the line joining the first and last point of the lactate/power
    curve, then finds the curve point with maximum perpendicular distance
    from that line. The power at that point is the threshold.

    Returns (threshold_power, lactate_at_threshold). None if not computable.

    Note: this is "modified" D-max because it works on measured points
    (not a fitted polynomial). For well-formed lactate curves with 5+ points
    it is stable and standard in modern literature.
    """
    if len(powers) < 3:
        return None, None

    x0, y0 = powers[0], lacts[0]
    x1, y1 = powers[-1], lacts[-1]

    dx, dy = x1 - x0, y1 - y0
    line_len = np.hypot(dx, dy)
    if line_len < 1e-9:
        return None, None

    # Perpendicular distance of each point from the line (first→last).
    # We use the 2D cross-product formula / segment length.
    best_idx = None
    best_dist = -1.0
    for i in range(1, len(powers) - 1):  # endpoints excluded: zero distance
        px, py = powers[i], lacts[i]
        dist = abs(dy * (px - x0) - dx * (py - y0)) / line_len
        if dist > best_dist:
            best_dist = dist
            best_idx = i

    if best_idx is None:
        return None, None
    return float(powers[best_idx]), float(lacts[best_idx])


def compute_lactate_thresholds(steps: List[LactateStep]) -> LactateThresholds:
    """
    Compute thresholds from real lactate data.

    - MLSS via D-max → primary reference (independent of Mader)
    - OBLA 4 mmol/L → historical comparability
    - Aerobic 2 mmol/L threshold → approximate LT1
    """
    powers, lacts = _sorted_steps(steps)
    thr = LactateThresholds()

    if len(powers) < 3:
        return thr  # not enough points; caller handles the error

    dmax_w, dmax_lact = _dmax_threshold(powers, lacts)
    thr.mlss_dmax_w = round(dmax_w, 1) if dmax_w is not None else None
    thr.dmax_lactate_at_threshold = round(dmax_lact, 2) if dmax_lact is not None else None

    obla = _interpolate_power_at_lactate(powers, lacts, OBLA_THRESHOLD_MMOL)
    thr.obla_4mmol_w = round(obla, 1) if obla is not None else None

    aer = _interpolate_power_at_lactate(powers, lacts, AEROBIC_THRESHOLD_MMOL)
    thr.aerobic_2mmol_w = round(aer, 1) if aer is not None else None

    return thr


# =============================================================================
# Validation of the non-invasive model against real lactate
# =============================================================================

def validate_model_against_lactate(
    steps: List[LactateStep],
    profiler,
    mmp: Dict[Any, float],
    expected_eta: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Validate Mader Python (MetabolicProfiler) against real lactate.

    Parameters
    ----------
    steps : list[LactateStep]
        Lactate test steps (power + lactate at end of step).
    profiler : MetabolicProfiler
        Instance already built with the athlete's weight and context.
    mmp : dict
        The athlete's MMP {duration_s: watts}. This is what Mader Python uses
        to estimate the profile, to be compared against lactate.
    expected_eta : float, optional
        Mechanical efficiency to pass to the profiler (otherwise it resolves it).

    Returns
    -------
    dict
        JSON payload with: lactate thresholds, MLSS predicted by the model,
        error, and validation verdict.
    """
    # --- Protocol guard: D-max requires enough points ---------
    valid_steps = [s for s in steps if s.power_w > 0 and s.lactate_mmol > 0]
    if len(valid_steps) < MIN_LACTATE_STEPS:
        return annotate_payload(
            {
                "status": "error",
                "reason": "insufficient_lactate_steps",
                "message": (
                    f"D-max requires at least {MIN_LACTATE_STEPS} valid lactate steps; "
                    f"only {len(valid_steps)} were provided. Repeat the test with "
                    f"more power increments until lactate is clearly above threshold "
                    f"(>6-8 mmol/L)."
                ),
                "steps_provided": len(valid_steps),
                "steps_required": MIN_LACTATE_STEPS,
            },
            module_name="lactate_validation_engine",
            method="validate_model_against_lactate",
            confidence=0.0,
        )

    # --- 1. "True" thresholds from lactate (ground truth) --------------------
    thresholds = compute_lactate_thresholds(valid_steps)
    mlss_true = thresholds.mlss_dmax_w

    if mlss_true is None:
        return annotate_payload(
            {
                "status": "error",
                "reason": "dmax_not_computable",
                "message": (
                    "Unable to compute D-max: the lactate/power curve does not "
                    "have a usable shape (check that lactate increases with power)."
                ),
                "lactate_thresholds": thresholds.to_dict(),
            },
            module_name="lactate_validation_engine",
            method="validate_model_against_lactate",
            confidence=0.0,
        )

    # --- 2. MLSS predicted by Mader Python from MMP --------------------
    snapshot = profiler.generate_metabolic_snapshot(mmp, expected_eta=expected_eta)

    if snapshot.get("status") != "success":
        return annotate_payload(
            {
                "status": "error",
                "reason": "model_snapshot_failed",
                "message": (
                    "The non-invasive model did not produce a valid snapshot "
                    "for the provided MMP: " + str(snapshot.get("message", "unknown error"))
                ),
                "lactate_thresholds": thresholds.to_dict(),
                "model_snapshot": snapshot,
            },
            module_name="lactate_validation_engine",
            method="validate_model_against_lactate",
            confidence=0.0,
        )

    mlss_model = snapshot.get("mlss_power_watts")
    if mlss_model is None:
        return annotate_payload(
            {
                "status": "error",
                "reason": "model_mlss_unavailable",
                "message": (
                    "The model could not estimate MLSS from the MMP "
                    "(probably missing a 20-60 min threshold-duration anchor "
                    "in the MMP). See 'expressiveness' in the snapshot."
                ),
                "lactate_thresholds": thresholds.to_dict(),
                "model_snapshot": snapshot,
            },
            module_name="lactate_validation_engine",
            method="validate_model_against_lactate",
            confidence=0.0,
        )

    # --- 3. Comparison and verdict ----------------------------------------
    error_w = float(mlss_model) - float(mlss_true)
    error_pct = 100.0 * error_w / float(mlss_true)
    abs_error_pct = abs(error_pct)

    if abs_error_pct <= VALIDATION_TOLERANCE_PCT:
        validated = True
        severity = "none"
        verdict = (
            f"Model VALIDATED for this athlete. MLSS predicted from MMP "
            f"({mlss_model:.0f}W) matches lactate-measured MLSS "
            f"({mlss_true:.0f}W) within {VALIDATION_TOLERANCE_PCT:.0f}% "
            f"(error {error_pct:+.1f}%). Monitoring can now continue "
            f"non-invasively without repeating the lactate test."
        )
        recommended_action = (
            "Proceed with non-invasive monitoring. Re-evaluate with a new "
            "lactate test only after major physiological changes "
            "(long training block, extended break, injury)."
        )
    elif abs_error_pct <= 2 * VALIDATION_TOLERANCE_PCT:
        validated = False
        severity = "moderate"
        verdict = (
            f"Model NOT yet validated. Predicted MLSS ({mlss_model:.0f}W) "
            f"deviates from measured MLSS ({mlss_true:.0f}W) by "
            f"{error_pct:+.1f}%, beyond the {VALIDATION_TOLERANCE_PCT:.0f}% "
            f"tolerance. The error is moderate."
        )
        recommended_action = (
            "Check MMP quality (threshold durations present? recent maximal "
            "efforts?) and calibration of the power meter used in the test. "
            "Consider repeating the lactate test."
        )
    else:
        validated = False
        severity = "severe"
        verdict = (
            f"Model NOT validated. Predicted MLSS ({mlss_model:.0f}W) deviates "
            f"strongly from measured MLSS ({mlss_true:.0f}W): "
            f"{error_pct:+.1f}%. Do not use the non-invasive model for this "
            f"athlete until the discrepancy is resolved."
        )
        recommended_action = (
            "Excessive error. Possible causes: unrepresentative MMP "
            "(sub-maximal efforts), miscalibrated test power meter, or "
            "atypical phenotype outside default Mader calibration. "
            "Review input data before relying on the model."
        )

    # Verdict confidence: high with many steps and clear convergence,
    # reduced when near the tolerance limit.
    margin = 1.0 - min(1.0, abs_error_pct / (2 * VALIDATION_TOLERANCE_PCT))
    step_factor = min(1.0, len(valid_steps) / 7.0)  # 7+ steps = full weight
    confidence = round(float(np.clip(0.4 + 0.5 * margin * step_factor, 0.2, 0.95)), 3)

    return annotate_payload(
        {
            "status": "success",
            "validated": validated,
            "severity": severity,
            "verdict": verdict,
            "recommended_action": recommended_action,
            "n_lactate_steps": len(valid_steps),
            # Ground truth from lactate
            "lactate_thresholds": thresholds.to_dict(),
            "mlss_true_watts": mlss_true,
            # Non-invasive model prediction
            "mlss_model_watts": round(float(mlss_model), 1),
            # Comparison
            "error_watts": round(error_w, 1),
            "error_pct": round(error_pct, 1),
            "tolerance_pct": VALIDATION_TOLERANCE_PCT,
            # Full model snapshot for audit
            "model_snapshot": snapshot,
        },
        module_name="lactate_validation_engine",
        method="validate_model_against_lactate",
        confidence=confidence,
        limitations=[
            "Reference MLSS estimated via D-max from measured lactate points.",
            "Validation is specific to the tested athlete, not generalizable.",
            f"Requires at least {MIN_LACTATE_STEPS} lactate steps for D-max.",
        ],
    )


# =============================================================================
# Helper to build steps from the app JSON payload
# =============================================================================

def steps_from_payload(raw_steps: List[Dict[str, Any]]) -> List[LactateStep]:
    """
    Convert the step list JSON from the app into LactateStep objects.

    Expected format for each step:
        {"power_w": 250, "lactate_mmol": 3.2, "hr_mean": 165,
         "cadence_mean": 92, "duration_s": 300}
    """
    out: List[LactateStep] = []
    for s in raw_steps:
        try:
            out.append(LactateStep(
                power_w=float(s["power_w"]),
                lactate_mmol=float(s["lactate_mmol"]),
                hr_mean=float(s["hr_mean"]) if s.get("hr_mean") is not None else None,
                cadence_mean=float(s["cadence_mean"]) if s.get("cadence_mean") is not None else None,
                duration_s=float(s["duration_s"]) if s.get("duration_s") is not None else None,
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return out


if __name__ == "__main__":  # pragma: no cover
    # Demo with synthetic data: an athlete with true MLSS ~250W from lactate.
    demo_steps = [
        LactateStep(power_w=150, lactate_mmol=1.2),
        LactateStep(power_w=200, lactate_mmol=1.8),
        LactateStep(power_w=230, lactate_mmol=2.6),
        LactateStep(power_w=260, lactate_mmol=4.1),
        LactateStep(power_w=290, lactate_mmol=6.8),
        LactateStep(power_w=320, lactate_mmol=10.2),
    ]
    thr = compute_lactate_thresholds(demo_steps)
    print("Thresholds from lactate:")
    print("  MLSS (D-max):    ", thr.mlss_dmax_w, "W")
    print("  OBLA (4 mmol/L): ", thr.obla_4mmol_w, "W")
    print("  Aerobic (2):     ", thr.aerobic_2mmol_w, "W")
