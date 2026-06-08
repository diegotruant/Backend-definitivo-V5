"""
MMP Aggregator — rolling power-duration curve from many rides
=============================================================

This is the missing link between single-ride parsing and the metabolic
profile. It answers the coach's real workflow:

    Day 0:  athlete does a TEST  →  initial metabolic profile
    Then :  every training ride / race that arrives is mined for power
            windows that could improve the athlete's power-duration curve,
            and the profile is re-modelled on the updated curve.

What it does
------------
1. From an incoming ride, extract the full mean-maximal-power curve
   (best power sustained for each standard duration, 5s … 3600s).
2. Compare each duration against the athlete's stored historical curve.
   Where the new ride beats the stored value, the curve improves.
3. Apply a time window (default 90 days, like analysis platform): efforts older than
   the window decay out, so the curve reflects CURRENT fitness, not a
   personal best from six months ago.
4. Gate every candidate window through data-quality and physiological
   sanity BEFORE it is allowed into the curve, so a spurious power spike
   from a mis-calibrated meter in one race cannot corrupt the profile.

Design: PURE FUNCTION
---------------------
This engine holds no state and touches no database. It takes the new
ride's power stream plus the athlete's stored curve (as plain dicts /
lists, e.g. loaded from Supabase) and returns the updated curve plus an
audit of what changed. The ecosystem persists the result; this module
only computes it.

    updated = update_power_curve(
        new_power_stream = [...],          # this ride's 1Hz power
        ride_date        = date(2026, 6, 1),
        stored_curve     = {...},          # from Supabase, or {} if first ride
        ride_id          = "race_giro_2026",
    )
    # write updated.curve back to Supabase

Tier: REFERENCE (curve construction) — feeds the MODEL tier (profiler).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from datetime import date, datetime, timedelta
import numpy as np


# Standard durations (seconds) tracked in the power-duration curve.
# Dense at the short end (neuromuscular/glycolytic) and across the aerobic
# and threshold windows, so the curve carries everything the profiler and
# the cross-validation need.
STANDARD_DURATIONS = [
    1, 5, 10, 15, 20, 30, 45,
    60, 90, 120, 180, 240, 300, 420, 600, 900,
    1200, 1800, 2400, 3600, 5400,
]

# Default rolling window (days). analysis platform uses 90 for power-duration metrics.
DEFAULT_WINDOW_DAYS = 90


@dataclass
class CurveEntry:
    """One point on the rolling power-duration curve, with provenance."""
    duration_s: int
    power_w: float
    ride_id: str
    ride_date: str          # ISO date the effort was achieved
    reliability: float = 1.0  # 0..1, inherited from session classification

    def to_dict(self) -> Dict[str, Any]:
        return {
            "duration_s": self.duration_s,
            "power_w": round(self.power_w, 1),
            "ride_id": self.ride_id,
            "ride_date": self.ride_date,
            "reliability": round(self.reliability, 2),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CurveEntry":
        return cls(
            duration_s=int(d["duration_s"]),
            power_w=float(d["power_w"]),
            ride_id=str(d.get("ride_id", "unknown")),
            ride_date=str(d.get("ride_date", "")),
            reliability=float(d.get("reliability", 1.0)),
        )


@dataclass
class CurveUpdateResult:
    """
    Outcome of folding one ride into the rolling curve.

    curve : dict[int, dict]
        The updated power-duration curve, keyed by duration_s. Each value
        is a serialized CurveEntry. This is what gets persisted.
    mmp_for_profiler : dict[int, float]
        Convenience view {duration_s: power_w} — exactly the input the
        MetabolicProfiler expects.
    improvements : list
        Durations where this ride beat the stored curve (the "windows that
        improve the curve").
    expired : list
        Durations whose stored best fell outside the time window and were
        dropped or replaced.
    rejected : list
        Candidate windows refused by the quality/sanity gate, with reasons.
    profile_should_refresh : bool
        True if the curve changed in a way that warrants re-running the
        metabolic profile (an improvement, or an expiry that lowered a
        profile-critical window).
    """
    curve: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    mmp_for_profiler: Dict[int, float] = field(default_factory=dict)
    improvements: List[Dict[str, Any]] = field(default_factory=list)
    expired: List[Dict[str, Any]] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    profile_should_refresh: bool = False
    ride_usable: bool = True
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": "REFERENCE",
            "curve": {str(k): v for k, v in self.curve.items()},
            "mmp_for_profiler": {str(k): round(v, 1) for k, v in self.mmp_for_profiler.items()},
            "improvements": self.improvements,
            "expired": self.expired,
            "rejected": self.rejected,
            "profile_should_refresh": self.profile_should_refresh,
            "ride_usable": self.ride_usable,
            "notes": self.notes,
        }


# Durations that, if they change, justify re-running the metabolic profile.
# These are the windows the Mader fit and cross-validation actually use.
_PROFILE_CRITICAL = {15, 20, 30, 45, 60, 180, 240, 300, 420, 1200, 1800, 3600}


# Absolute physiological power ceilings (W/kg) by duration. No human
# sustains power above these for the given duration; a candidate window
# exceeding the ceiling is a sensor artifact (spike/dropout), not a real
# effort. Values sit comfortably above world-class records so they never
# reject a legitimate effort — they only catch impossible spikes.
# References: track sprint peak ~25 W/kg (1s), elite 5s ~22, 1min ~11,
# 5min ~7.5, FTP ~6.5 for the very best; ceilings set well above these.
_POWER_CEILING_WKG = [
    (1, 30.0), (5, 26.0), (10, 22.0), (15, 19.0), (20, 17.0),
    (30, 14.0), (45, 12.5), (60, 11.5), (90, 10.0), (120, 9.5),
    (180, 8.5), (240, 8.0), (300, 7.8), (420, 7.3), (600, 7.0),
    (900, 6.8), (1200, 6.6), (1800, 6.3), (2400, 6.1), (3600, 6.0),
    (5400, 5.7),
]


def _ceiling_for(duration_s: int, weight_kg: float) -> float:
    """Absolute plausible power (W) for a duration given athlete weight."""
    wkg = _POWER_CEILING_WKG[-1][1]
    for d, c in _POWER_CEILING_WKG:
        if duration_s <= d:
            wkg = c
            break
    return wkg * max(40.0, weight_kg)


def _parse_date(d) -> date:
    if isinstance(d, date):
        return d
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str):
        try:
            return date.fromisoformat(d[:10])
        except ValueError:
            return date.today()
    return date.today()


def extract_ride_curve(
    power_stream: List[float],
    durations: Optional[List[int]] = None,
    despike: bool = True,
) -> Dict[int, float]:
    """
    Extract the mean-maximal-power curve from a single ride.

    Returns {duration_s: best_power_w} for every standard duration that
    fits inside the ride. Uses the validated power_engine.mean_maximal_power
    (cumulative-sum sliding window) under the hood.

    despike : bool
        If True, apply the data-quality engine's own power-spike filter
        (median filter for isolated readings above a physiological bound)
        before extracting the curve, so a single corrupt sample cannot
        enter as a duration best. Reuses the quality engine's logic rather
        than duplicating it.
    """
    from power_engine import mean_maximal_power

    if durations is None:
        durations = STANDARD_DURATIONS

    arr = np.asarray(power_stream, dtype=float)
    arr = np.nan_to_num(arr, nan=0.0)
    if arr.size < 1 or float(np.max(arr)) <= 0.0:
        return {}

    if despike:
        # Reuse the quality engine's spike remover if available, so the
        # de-spiking rule lives in exactly one place.
        try:
            from data_quality_engine import _remove_power_spikes
            arr = np.asarray(_remove_power_spikes(arr), dtype=float)
        except Exception:
            # Fallback: simple isolated-spike clamp. A reading is a spike
            # if it is far above both neighbours (a 1-2 sample jump that
            # drops straight back). Replace it with the local median.
            if arr.size >= 3:
                for i in range(1, arr.size - 1):
                    nb = 0.5 * (arr[i - 1] + arr[i + 1])
                    if arr[i] > 1.8 * nb and arr[i] - nb > 300.0:
                        arr[i] = np.median(arr[max(0, i - 2):i + 3])

    # Only request durations that fit in the ride.
    fit_durations = [d for d in durations if d <= arr.size]
    if not fit_durations:
        return {}

    mmp = mean_maximal_power(arr, durations_s=fit_durations)
    out: Dict[int, float] = {}
    for pt in mmp:
        d = int(pt["duration_s"])
        p = float(pt["power_w"])
        if p > 0:
            out[d] = p
    return out


def update_power_curve(
    new_power_stream: List[float],
    ride_date,
    stored_curve: Optional[Dict[Any, Any]] = None,
    ride_id: str = "unknown",
    *,
    weight_kg: float = 70.0,
    hr_stream: Optional[List[float]] = None,
    cadence_stream: Optional[List[float]] = None,
    reliability: float = 1.0,
    window_days: int = DEFAULT_WINDOW_DAYS,
    today=None,
    enforce_quality_gate: bool = True,
    enforce_monotonicity: bool = True,
) -> CurveUpdateResult:
    """
    Fold one ride into the athlete's rolling power-duration curve.

    Parameters
    ----------
    new_power_stream : list of float
        The incoming ride's 1Hz power data.
    ride_date : date | str
        When the ride happened (the date its efforts are credited to).
    stored_curve : dict, optional
        The athlete's current curve, as persisted. Keys are duration_s
        (int or str), values are serialized CurveEntry dicts. Empty/None
        for an athlete's first ride.
    ride_id : str
        Identifier for provenance.
    hr_stream, cadence_stream : list, optional
        Used by the quality gate to decide whether the ride is trustworthy.
    reliability : float
        Confidence in this ride's power (e.g. 1.0 for a clean test, lower
        for a ride flagged by session classification). Stored with any
        window this ride contributes.
    window_days : int
        Rolling window. Efforts older than this decay out of the curve.
    today : date, optional
        Reference "now" for the window (defaults to ride_date or today).
    enforce_quality_gate : bool
        If True, a ride the data-quality engine marks unusable contributes
        NO windows (protects the curve from dirty data).
    enforce_monotonicity : bool
        If True, candidate windows that would create a power-curve inversion
        (a longer duration with higher power than a shorter one) are
        rejected as physically impossible.

    Returns
    -------
    CurveUpdateResult
    """
    result = CurveUpdateResult()
    rdate = _parse_date(ride_date)
    ref_today = _parse_date(today) if today is not None else rdate

    # ---- Load the stored curve into CurveEntry objects -----------------
    curve: Dict[int, CurveEntry] = {}
    if stored_curve:
        for k, v in stored_curve.items():
            try:
                d = int(k)
            except (TypeError, ValueError):
                continue
            if isinstance(v, dict):
                curve[d] = CurveEntry.from_dict(v)
            else:
                # bare number → wrap it (unknown provenance)
                curve[d] = CurveEntry(d, float(v), "historical", "", 1.0)

    # ---- Expire efforts older than the rolling window ------------------
    cutoff = ref_today - timedelta(days=window_days)
    for d in list(curve.keys()):
        e = curve[d]
        if e.ride_date:
            try:
                edate = date.fromisoformat(e.ride_date[:10])
            except ValueError:
                edate = None
            if edate is not None and edate < cutoff:
                result.expired.append(e.to_dict())
                if d in _PROFILE_CRITICAL:
                    result.profile_should_refresh = True
                del curve[d]

    # ---- Quality gate on the incoming ride -----------------------------
    if enforce_quality_gate:
        try:
            from data_quality_engine import assess_data_quality
            q = assess_data_quality(
                power_stream=list(new_power_stream),
                hr_stream=list(hr_stream) if hr_stream is not None else None,
                cadence_stream=list(cadence_stream) if cadence_stream is not None else None,
            )
            usable = getattr(q, "usable_for_analysis", True)
            if not usable:
                result.ride_usable = False
                issues = getattr(q, "issues_detected", [])
                result.notes.append(
                    f"Ride {ride_id} failed quality gate; no windows contributed. "
                    f"Issues: {'; '.join(issues[:3]) if issues else 'unusable'}"
                )
                # Still return the (possibly expired) stored curve.
                result.curve = {d: e.to_dict() for d, e in curve.items()}
                result.mmp_for_profiler = {d: e.power_w for d, e in curve.items()}
                return result
        except Exception:
            # If the gate can't run, proceed but note it.
            result.notes.append("Quality gate unavailable; ride accepted without it.")

    # ---- Extract this ride's mean-maximal curve ------------------------
    ride_curve = extract_ride_curve(new_power_stream)
    if not ride_curve:
        result.notes.append(f"Ride {ride_id} has no usable power; curve unchanged.")
        result.curve = {d: e.to_dict() for d, e in curve.items()}
        result.mmp_for_profiler = {d: e.power_w for d, e in curve.items()}
        return result

    # ---- Merge: keep the best power per duration -----------------------
    # Process shortest→longest so the monotonicity check can use the
    # already-accepted shorter durations as an upper reference.
    for d in sorted(ride_curve.keys()):
        cand = ride_curve[d]
        stored = curve.get(d)

        # Improvement test: does this ride beat the stored value?
        if stored is not None and cand <= stored.power_w:
            continue  # stored best stands

        # Monotonicity sanity: a longer effort cannot exceed a shorter
        # one's power. If the candidate would invert the curve against an
        # accepted shorter duration, it is physically impossible → reject.
        if enforce_monotonicity:
            shorter = [curve[sd].power_w for sd in curve if sd < d]
            if shorter:
                min_shorter = min(shorter)
                if cand > min_shorter * 1.02:  # 2% noise tolerance
                    result.rejected.append({
                        "duration_s": d,
                        "candidate_w": round(cand, 1),
                        "reason": (
                            f"would exceed a shorter-duration best "
                            f"({min_shorter:.0f}W) — physically impossible, "
                            f"likely a power spike artifact"
                        ),
                    })
                    continue

        # Accept the candidate.
        prev_w = stored.power_w if stored else None
        curve[d] = CurveEntry(
            duration_s=d,
            power_w=cand,
            ride_id=ride_id,
            ride_date=rdate.isoformat(),
            reliability=reliability,
        )
        result.improvements.append({
            "duration_s": d,
            "new_w": round(cand, 1),
            "previous_w": round(prev_w, 1) if prev_w is not None else None,
            "gain_w": round(cand - prev_w, 1) if prev_w is not None else None,
        })
        if d in _PROFILE_CRITICAL:
            result.profile_should_refresh = True

    # ---- Finalize ------------------------------------------------------
    result.curve = {d: e.to_dict() for d, e in sorted(curve.items())}
    result.mmp_for_profiler = {d: e.power_w for d, e in sorted(curve.items())}

    if result.improvements:
        result.notes.append(
            f"Ride {ride_id} improved {len(result.improvements)} duration(s)."
        )
    else:
        result.notes.append(f"Ride {ride_id} did not improve the curve.")

    return result


def curve_to_mmp(stored_curve: Dict[Any, Any]) -> Dict[int, float]:
    """
    Convert a persisted curve to the {duration_s: power_w} dict the
    MetabolicProfiler consumes. Convenience for the ecosystem.
    """
    out: Dict[int, float] = {}
    for k, v in (stored_curve or {}).items():
        try:
            d = int(k)
        except (TypeError, ValueError):
            continue
        if isinstance(v, dict):
            p = float(v.get("power_w", 0))
        else:
            p = float(v)
        if p > 0:
            out[d] = p
    return out
