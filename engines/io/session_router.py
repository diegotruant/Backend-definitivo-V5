"""
Session router.
===============

When a FIT arrives, the backend should know *what kind* of session it is and
run the engines that make sense for it — instead of running everything and
hoping. This module is that dispatcher.

It does not re-classify or re-calculate anything itself: it leans on
interval_detector.classify_session() for the decision and then calls the
existing engines. Its value is the routing policy, learned from real data:

  * Threshold detection from DFA-alpha1 needs a *graded* effort. On a ramp/
    incremental test alpha1 falls cleanly with intensity and VT1/VT2 are
    well-defined. On a free ride the power jumps around, alpha1 reacts to
    transients, and the alpha1-vs-power regression is too weak to trust
    (observed R ~ 0.2 on a real 3-hour ride). So HRV *threshold* extraction is
    routed ONLY to ramp/incremental tests.

  * A free ride still has valuable HRV content — but as *durability* and
    time-in-zone, not as a threshold. So rides route to the durability/
    time-in-zone read of DFA-alpha1, plus the power-curve update.

  * CP / sprint tests route to the metabolic anchor path (sprint -> VLamax,
    CP -> aerobic), via the test-effort extractor.

Routing table (category/subtype -> engines):

  TEST + ramp_test            -> HRV threshold (VT1/VT2) + metabolic
  TEST + cp*/sprint*/mixed    -> metabolic anchor (extract_test_proposal)
  STEADY (sweet_spot, z2...)  -> power curve + durability HRV
  FREE / UNCLASSIFIED         -> power curve + durability HRV
  HIIT                        -> power curve + interval stimulus (+ durability)
  ride/hiit + profilo Mader   -> mader_durability (CP residua ODE + potenze sostenibili)

Known limitation: a CP test made of two maximal blocks with recovery between
them (e.g. CP3 + CP6, no sprint) is structurally indistinguishable from a HIIT
session and may classify as HIIT. This is acceptable because profile *creation*
does not rely on single-file routing: the coach uploads the test files and
extract_test_proposal() searches for anchors across all of them regardless of
per-file category. Single-file routing here serves the *monitoring* flow,
where the question is "ride to learn from vs. occasional test", and a CP block
routed as HIIT still updates the power curve correctly.

Everything degrades gracefully: missing power -> skip power engines; missing
RR -> skip HRV; the report says what ran and what was skipped and why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from engines.core.athlete_context import AthleteContext
from engines.performance.interval_detector import classify_session


# Subtypes that are graded enough for clean DFA-alpha1 threshold detection.
_RAMP_LIKE = {"ramp_test", "incrementale", "ramp"}


@dataclass
class RoutingDecision:
    category: str
    subtype: Optional[str]
    confidence: float
    route: str                       # "metabolic_anchor" | "hrv_threshold" | "ride_monitoring" | "hiit"
    source: str = "signal"           # classify_session source: filename | laps | signal | hint
    engines_to_run: List[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category, "subtype": self.subtype,
            "confidence": round(self.confidence, 3), "route": self.route,
            "source": self.source,
            "engines_to_run": self.engines_to_run, "rationale": self.rationale,
        }


def decide_route(
    power: List[float],
    *,
    filename: Optional[str] = None,
    laps: Optional[List[Dict[str, Any]]] = None,
    ftp: Optional[float] = None,
    has_rr: bool = False,
    has_metabolic_profile: bool = False,
) -> RoutingDecision:
    """
    Classify the session and decide which engines to run. Pure decision; no
    engine is executed here (so it is cheap and testable).
    """
    cls = classify_session(power, filename=filename, laps=laps, ftp=ftp)
    cat = cls.category
    sub = getattr(cls, "subtype", None)
    conf = float(getattr(cls, "confidence", 0.0) or 0.0)
    src = str(getattr(cls, "source", "signal") or "signal")

    engines: List[str] = []
    if cat == "TEST":
        if sub in _RAMP_LIKE:
            route = "hrv_threshold"
            engines = ["metabolic_profile"]
            if has_rr:
                engines.append("hrv_threshold_vt1_vt2")
                rationale = ("Graded ramp test: DFA-alpha1 gives clean VT1/VT2; "
                             "running HRV threshold + metabolic profile.")
            else:
                rationale = ("Ramp test but no RR data: HRV thresholds skipped, "
                             "metabolic profile only.")
        else:
            route = "metabolic_anchor"
            engines = ["test_effort_extraction", "metabolic_profile"]
            rationale = (f"Structured test ({sub}): routing to metabolic anchor "
                         f"(sprint->VLamax, CP->aerobic).")
            if has_rr:
                engines.append("hrv_durability")
    elif cat == "HIIT":
        route = "hiit"
        engines = ["power_curve_update", "interval_stimulus"]
        if has_rr:
            engines.append("hrv_durability")
        if has_metabolic_profile:
            engines.append("mader_durability")
        rationale = "Interval session: power curve + interval stimulus (HRV as durability)."
    else:  # STEADY, FREE, UNCLASSIFIED
        route = "ride_monitoring"
        engines = ["power_curve_update"]
        if has_rr:
            engines.append("hrv_durability")
        if has_metabolic_profile:
            engines.append("mader_durability")
        rationale = (f"{cat}{('/'+sub) if sub else ''}: free/steady ride. "
                     f"Power curve update"
                     f"{' + HRV durability/time-in-zone' if has_rr else ' (no RR for HRV)'}. "
                     f"HRV thresholds NOT extracted (needs a graded test)."
                     f"{' Mader CP-residual durability when metabolic profile is available.' if has_metabolic_profile else ''}")

    return RoutingDecision(
        category=cat, subtype=sub, confidence=conf, source=src,
        route=route, engines_to_run=engines, rationale=rationale,
    )


def route_and_run(
    power: List[float],
    rr_samples: Optional[List[Dict[str, Any]]] = None,
    *,
    elapsed_s: Optional[List[float]] = None,
    weight_kg: Optional[float] = None,
    filename: Optional[str] = None,
    laps: Optional[List[Dict[str, Any]]] = None,
    ftp: Optional[float] = None,
    context: Optional[AthleteContext] = None,
    metabolic_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Full auto-pipeline: classify, then run the engines the route calls for.
    Returns the routing decision plus whatever each engine produced. Engines
    that cannot run (missing data) are reported as skipped, not failed.
    """
    ctx = context or AthleteContext(gender="MALE", training_years=10, discipline="ENDURANCE")
    has_rr = bool(rr_samples)
    has_profile = bool(metabolic_snapshot and metabolic_snapshot.get("status") == "success")
    decision = decide_route(
        power,
        filename=filename,
        laps=laps,
        ftp=ftp,
        has_rr=has_rr,
        has_metabolic_profile=has_profile,
    )
    out: Dict[str, Any] = {"routing": decision.to_dict(), "results": {}, "skipped": {}, "assumptions": []}
    try:
        resolved_weight = float(weight_kg) if weight_kg is not None else 0.0
    except (TypeError, ValueError):
        resolved_weight = 0.0
    if resolved_weight <= 0.0:
        resolved_weight = 70.0
        out["assumptions"].append(
            "weight_kg_missing_defaulted_to_70_for_non_official_metrics"
        )

    parr = np.nan_to_num(np.array(power, dtype=float), nan=0.0)

    # --- HRV threshold (only on ramp-like tests) ---
    if "hrv_threshold_vt1_vt2" in decision.engines_to_run:
        try:
            vt = _hrv_thresholds(rr_samples, parr, elapsed_s, ctx)
            out["results"]["hrv_threshold"] = vt
        except Exception as e:
            out["skipped"]["hrv_threshold"] = f"error: {e}"

    # --- HRV durability / time-in-zone (rides, structured tests with RR) ---
    if "hrv_durability" in decision.engines_to_run:
        try:
            out["results"]["hrv_durability"] = _hrv_durability(rr_samples, elapsed_s, ctx)
        except Exception as e:
            out["skipped"]["hrv_durability"] = f"error: {e}"

    # --- Metabolic profile / anchor extraction ---
    if "test_effort_extraction" in decision.engines_to_run:
        try:
            from engines.performance.effort_extractor import extract_test_proposal
            prop = extract_test_proposal([{"file_id": filename or "test", "power": power, "laps": laps}])
            out["results"]["test_proposal"] = prop.to_dict()
        except Exception as e:
            out["skipped"]["test_effort_extraction"] = f"error: {e}"

    if "metabolic_profile" in decision.engines_to_run:
        try:
            from engines.metabolic.metabolic_profiler import MetabolicProfiler
            from engines.performance.mmp_aggregator import update_power_curve
            import datetime
            r = update_power_curve(power, datetime.date.today(), weight_kg=resolved_weight)
            prof = MetabolicProfiler(weight=resolved_weight, context=ctx)
            out["results"]["metabolic_snapshot"] = prof.generate_metabolic_snapshot(r.mmp_for_profiler)
        except Exception as e:
            out["skipped"]["metabolic_profile"] = f"error: {e}"

    # --- Mader mechanistic durability (rides / hiit with metabolic profile) ---
    if "mader_durability" in decision.engines_to_run:
        try:
            from engines.performance.mader_durability import compute_session_durability
            out["results"]["mader_durability"] = compute_session_durability(
                power, metabolic_snapshot, resolved_weight,
            )
        except Exception as e:
            out["skipped"]["mader_durability"] = f"error: {e}"

    # --- Power curve update (rides / hiit) ---
    if "power_curve_update" in decision.engines_to_run:
        try:
            from engines.performance.mmp_aggregator import update_power_curve
            import datetime
            r = update_power_curve(power, datetime.date.today(), weight_kg=resolved_weight)
            out["results"]["power_curve"] = {
                "curve": r.curve, "mmp_for_profiler": r.mmp_for_profiler,
                "ride_usable": r.ride_usable,
            }
        except Exception as e:
            out["skipped"]["power_curve_update"] = f"error: {e}"

    return out


# ---------------------------------------------------------------------------
# Engine helpers
# ---------------------------------------------------------------------------
def _hrv_thresholds(rr_samples, parr, elapsed_s, ctx) -> Dict[str, Any]:
    """VT1/VT2 in watts from DFA-alpha1 vs power (ramp test only)."""
    from engines.recovery.hrv_engine import analyze_rr_stream
    if elapsed_s is None:
        raise ValueError("elapsed_s required for threshold/power alignment")
    elapsed = np.array(elapsed_s, dtype=float)
    windows = analyze_rr_stream(rr_samples, window_seconds=120, step_seconds=10.0, context=ctx)
    pts = []
    for w in windows:
        t = w.get("timestamp")
        a1 = w.get("alpha1_smoothed") or w.get("alpha1")
        if t is None or a1 is None or np.isnan(a1):
            continue
        mask = (elapsed >= t - 60) & (elapsed <= t + 60)
        if mask.sum() < 30:
            continue
        pw = parr[mask]
        pw = pw[pw > 0]
        if len(pw) < 30:
            continue
        pts.append((a1, float(np.mean(pw))))
    if len(pts) < 8:
        return {"status": "insufficient", "n_points": len(pts)}
    arr = np.array(pts)
    a1v, pwv = arr[:, 0], arr[:, 1]
    # regression over the working band
    m = (pwv >= np.percentile(pwv, 20)) & (pwv <= np.percentile(pwv, 90))
    if m.sum() < 6:
        m = np.ones_like(pwv, dtype=bool)
    slope, intercept = np.polyfit(pwv[m], a1v[m], 1)
    r = float(np.corrcoef(pwv[m], a1v[m])[0, 1])
    vt1 = (0.75 - intercept) / slope if slope != 0 else None
    vt2 = (0.50 - intercept) / slope if slope != 0 else None
    reliable = abs(r) >= 0.5  # honest gate: weak fit -> not reliable
    return {
        "status": "ok" if reliable else "low_reliability",
        "vt1_watts": round(vt1, 0) if vt1 else None,
        "vt2_watts": round(vt2, 0) if vt2 else None,
        "regression_r": round(r, 2),
        "n_points": int(m.sum()),
        "note": ("Clean graded relationship." if reliable else
                 "Weak alpha1-power relationship; thresholds indicative only "
                 "(this is why free rides are not used for thresholds)."),
    }


def _hrv_durability(rr_samples, elapsed_s, ctx) -> Dict[str, Any]:
    """Time-in-zone and DFA-alpha1 drift over the session (rides)."""
    from engines.recovery.hrv_engine import analyze_rr_stream
    from collections import Counter
    windows = analyze_rr_stream(rr_samples, window_seconds=120, step_seconds=10.0, context=ctx)
    a1_raw = [(w.get("alpha1_smoothed") or w.get("alpha1")) for w in windows]
    a1: List[float] = [float(x) for x in a1_raw if x is not None and not np.isnan(x)]
    status = Counter(w.get("status") for w in windows if w.get("status"))
    tot = sum(status.values()) or 1
    if not a1:
        return {"status": "insufficient"}
    # alpha1 drift: first third vs last third (durability signal)
    n = len(a1)
    first: float = float(np.mean(a1[: n // 3])) if n >= 3 else float(a1[0])
    last: float = float(np.mean(a1[-n // 3:])) if n >= 3 else float(a1[-1])
    return {
        "status": "ok",
        "alpha1_mean": round(float(np.mean(a1)), 3),
        "alpha1_min": round(float(np.min(a1)), 3),
        "time_in_zone_pct": {k: round(100 * v / tot, 0) for k, v in status.items()},
        "alpha1_drift": round(last - first, 3),
        "n_windows": n,
        "note": ("Durability read: time-in-zone and alpha1 drift across the "
                 "session. Negative drift = HRV moving toward anaerobic as "
                 "fatigue accumulates."),
    }
