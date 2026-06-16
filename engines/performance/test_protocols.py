"""
Test Protocols Engine — in-person test computation (it4cycling-style)
=======================================================================

PURPOSE
-------
This module receives data from an in-person test performed by the coach (via
the tablet app connected to the trainer) and computes the results, returning
JSON ready for the frontend / history / PDF export.

One test = one function. Functions do NOT recompute things the backend already
knows how to do: they hook into existing modules.

  - Mader (lactate)   → delegates to lactate_validation_engine (D-max + validation
                        of the non-invasive model). This is the onboarding test.
  - Critical Power     → delegates to power_engine.fit_critical_power (Monod fit).
  - Incremental       → threshold from HR/power response + max power.
  - P/C curve         → optimal cadence from sprint peaks.
  - Wingate            → peak/mean/minimum + fatigue index.

The input/output JSON contract is documented in CONTRATTO_JSON_test.md.

Tier: REFERENCE for tests that apply direct formulas (P/C curve, wingate,
incremental max-power); the Mader test inherits the lactate tier (REFERENCE
on data, MODEL on validation); CP inherits from power_engine (REFERENCE).
"""

from typing import Any, Dict, Optional
import numpy as np

from engines.core.metric_contracts import annotate_payload

# Existing CP/W' fit in the backend — do NOT rewrite it, call it.
from engines.performance.power_engine import fit_critical_power

# Lactate validation (dedicated module) — used by the Mader test.
from engines.metabolic.lactate_validation_engine import (
    validate_model_against_lactate,
    steps_from_payload,
)


# =============================================================================
# Shared helpers
# =============================================================================

def _err(reason: str, message: str, method: str, **extra) -> Dict[str, Any]:
    """Build a uniform, annotated error response."""
    payload = {"status": "error", "reason": reason, "message": message}
    payload.update(extra)
    return annotate_payload(
        payload,
        module_name="test_protocols",
        method=method,
        confidence=0.0,
    )


def _athlete_weight(envelope: Dict[str, Any]) -> Optional[float]:
    """Extract the athlete's weight from the common envelope."""
    try:
        w = float(envelope.get("athlete", {}).get("weight_kg"))
        return w if w > 0 else None
    except (TypeError, ValueError):
        return None


# =============================================================================
# 1. MADER (lactate test) — onboarding
# =============================================================================

def run_mader_test(
    envelope: Dict[str, Any],
    profiler,
) -> Dict[str, Any]:
    """
    Run the Mader lactate test.

    Fully delegates to lactate_validation_engine: computes true MLSS with
    D-max from lactate points, compares it with the MLSS the non-invasive
    model predicts from MMP, and issues the validation verdict.

    Parameters
    ----------
    envelope : dict
        The full envelope (see contract). test_data must contain
        'steps' (with lactate) and 'mmp'.
    profiler : MetabolicProfiler
        Instance already built with the athlete's weight/context.
    """
    td = envelope.get("test_data", {})
    raw_steps = td.get("steps")
    mmp = td.get("mmp")

    if not raw_steps:
        return _err("missing_steps", "Missing lactate test steps.",
                    "run_mader_test")
    if not mmp:
        return _err("missing_mmp",
                    "Missing athlete MMP: required to validate the non-invasive "
                    "model against lactate.",
                    "run_mader_test")

    steps = steps_from_payload(raw_steps)
    eta = td.get("expected_eta")  # optional

    # All real logic lives here (D-max + validation).
    return validate_model_against_lactate(
        steps=steps,
        profiler=profiler,
        mmp=mmp,
        expected_eta=eta,
    )


# =============================================================================
# 2. INCREMENTAL
# =============================================================================

def run_incremental_test(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Incremental power test (without lactate).

    Extracts: maximum power reached, maximum observed HR, number of steps
    completed. Precise threshold, if needed, comes from the model on MMP
    (not from here): this test provides raw data and max power.
    """
    td = envelope.get("test_data", {})
    steps = td.get("steps")
    if not steps:
        return _err("missing_steps", "Missing incremental test steps.",
                    "run_incremental_test")

    powers = [float(s["power_w"]) for s in steps if s.get("power_w")]
    hrs = [float(s["hr_mean"]) for s in steps if s.get("hr_mean")]

    if not powers:
        return _err("no_power_data", "No valid power data.",
                    "run_incremental_test")

    max_power = max(powers)
    hr_max_obs = max(hrs) if hrs else None

    payload = {
        "status": "success",
        "max_power_w": round(max_power, 1),
        "hr_max_observed": round(hr_max_obs, 0) if hr_max_obs else None,
        "steps_completed": len(steps),
        "notes": (
            "Max power and max HR from the test. For metabolic threshold use the "
            "model on the MMP built from this test."
        ),
    }
    return annotate_payload(
        payload,
        module_name="test_protocols",
        method="run_incremental_test",
        confidence=0.85,  # direct measurement, high reliability
    )


# =============================================================================
# 3. POWER / CADENCE CURVE
# =============================================================================

def run_power_cadence_test(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Power/cadence curve from 4-5 maximal sprints at different RPMs.

    Finds the cadence at which the athlete produces peak power,
    by fitting a parabola to the points (classic model: power as a
    function of cadence has a bell-shaped curve).
    """
    td = envelope.get("test_data", {})
    points = td.get("points")
    if not points or len(points) < 3:
        return _err("insufficient_points",
                    "At least 3 sprints at different cadences are required for the curve.",
                    "run_power_cadence_test",
                    points_provided=len(points) if points else 0)

    rpms = np.array([float(p["rpm_peak"]) for p in points if p.get("rpm_peak")], dtype=float)
    watts = np.array([float(p["w_peak"]) for p in points if p.get("w_peak")], dtype=float)

    if len(rpms) < 3 or len(rpms) != len(watts):
        return _err("invalid_points", "Incomplete cadence/power points.",
                    "run_power_cadence_test")

    # Parabolic fit watts = a*rpm^2 + b*rpm + c; vertex gives optimal cadence.
    optimal_cadence = None
    peak_power_fit = None
    try:
        coeffs = np.polyfit(rpms, watts, 2)
        a, b, c = coeffs
        if a < 0:  # parabola with maximum (bell curve), as expected
            vertex_rpm = -b / (2 * a)
            # accept vertex only if it falls within/near the tested range
            if rpms.min() - 10 <= vertex_rpm <= rpms.max() + 10:
                optimal_cadence = float(vertex_rpm)
                peak_power_fit = float(a * vertex_rpm**2 + b * vertex_rpm + c)
    except Exception:
        pass

    # Fallback: if fit does not yield a valid maximum, use the best measured point.
    if optimal_cadence is None:
        idx = int(np.argmax(watts))
        optimal_cadence = float(rpms[idx])
        peak_power_fit = float(watts[idx])

    curve = [{"rpm": round(float(r)), "watts": round(float(w))}
             for r, w in sorted(zip(rpms, watts))]

    payload = {
        "status": "success",
        "optimal_cadence_rpm": round(optimal_cadence),
        "peak_power_w": round(peak_power_fit),
        "curve": curve,
    }
    return annotate_payload(
        payload,
        module_name="test_protocols",
        method="run_power_cadence_test",
        confidence=0.80,
    )


# =============================================================================
# 4. CRITICAL POWER
# =============================================================================

def run_critical_power_test(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Critical Power test from multiple maximal efforts (2-15 min).

    Delegates to the existing fit in power_engine.fit_critical_power, which expects
    a list [{"duration_s": ..., "power_w": ...}].
    """
    td = envelope.get("test_data", {})
    efforts = td.get("efforts")
    if not efforts:
        return _err("missing_efforts", "Missing efforts for CP fit.",
                    "run_critical_power_test")

    # fit_critical_power filters the 120-900s window itself and requires min 3 points.
    result = fit_critical_power(efforts)

    if result is None:
        return _err(
            "cp_fit_failed",
            "CP fit failed: at least 3 maximal efforts in the "
            "2-15 min window (120-900s) are required, and CP/W' must be positive.",
            "run_critical_power_test",
            efforts_provided=len(efforts),
        )

    result["status"] = "success"
    return annotate_payload(
        result,
        module_name="test_protocols",
        method="run_critical_power_test",
        confidence=result.get("r_squared", 0.8),  # R² as confidence proxy
    )


# =============================================================================
# 5. WINGATE
# =============================================================================

def run_wingate_test(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wingate test: timed maximal sprint (classic 30s).

    Computes peak, mean, minimum, and fatigue index:
        fatigue_index = (peak - minimum) / peak * 100
    """
    td = envelope.get("test_data", {})
    stream = td.get("power_stream")
    if not stream:
        return _err("missing_power_stream",
                    "Missing second-by-second power stream.",
                    "run_wingate_test")

    p = np.array([float(x) for x in stream if x is not None], dtype=float)
    p = p[p >= 0]
    if p.size < 5:
        return _err("stream_too_short",
                    "Power stream too short for a Wingate test.",
                    "run_wingate_test")

    weight = _athlete_weight(envelope)
    # explicit weight in test_data takes priority, if present
    if td.get("body_weight_kg"):
        try:
            weight = float(td["body_weight_kg"])
        except (TypeError, ValueError):
            pass

    peak = float(np.max(p))
    mean = float(np.mean(p))
    minimum = float(np.min(p))
    fatigue_index = (peak - minimum) / peak * 100.0 if peak > 0 else None

    assumptions = []
    if weight is None or weight <= 0:
        assumptions.append("body_weight_missing_peak_power_wkg_not_computed")
    payload = {
        "status": "success",
        "peak_power_w": round(peak, 1),
        "peak_power_wkg": round(peak / weight, 2) if weight and weight > 0 else None,
        "mean_power_w": round(mean, 1),
        "min_power_w": round(minimum, 1),
        "fatigue_index_pct": round(fatigue_index, 1) if fatigue_index is not None else None,
        "duration_s": int(td.get("duration_s", p.size)),
        "assumptions": assumptions,
    }
    return annotate_payload(
        payload,
        module_name="test_protocols",
        method="run_wingate_test",
        confidence=0.90,  # direct measurements
    )


# =============================================================================
# Dispatcher: routes the envelope to the correct test
# =============================================================================

def run_test(envelope: Dict[str, Any], profiler=None) -> Dict[str, Any]:
    """
    Single entry point. Reads envelope['test_type'] and calls the appropriate
    function. The profiler is only needed for the Mader test (others ignore it).
    """
    test_type = envelope.get("test_type")

    if test_type == "mader":
        if profiler is None:
            return _err("profiler_required",
                        "The Mader test requires a MetabolicProfiler instance.",
                        "run_test")
        return run_mader_test(envelope, profiler)
    if test_type == "incrementale":
        return run_incremental_test(envelope)
    if test_type == "curva_pc":
        return run_power_cadence_test(envelope)
    if test_type == "critical_power":
        return run_critical_power_test(envelope)
    if test_type == "wingate":
        return run_wingate_test(envelope)

    return _err("unknown_test_type",
                f"Unknown test type: {test_type!r}.",
                "run_test")
