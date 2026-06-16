"""
Zones Engine — Coggan power zones + Friel HR zones + Seiler polarization
Version: 1.0.0

Computes time-in-zone for an activity using three orthogonal zone systems:

  1. Coggan 7-zone power    — anchored at FTP. Industry standard for
                              power-based prescription.
  2. Friel 5-zone HR        — anchored at LTHR (lactate-threshold HR).
                              Used by athletes without power meters.
  3. Seiler 3-zone           — Z1 (below VT1) / Z2 (VT1–VT2) / Z3 (above VT2).
                              The polarization model. Used to classify the
                              session intensity distribution.

Each system returns time-in-zone (seconds + percent), and the Seiler one
also classifies the session as polarized / pyramidal / threshold / mixed.

References:
  - Coggan & Allen 2010, "Training and Racing with a Power Meter"
  - Friel 2009, "The Cyclist's Training Bible" 4th ed.
  - Seiler 2010, Int J Sports Physiol Perform 5: 276–291
  - St\u00f6ggl & Sperlich 2014, Front Physiol 5:33 (polarization classification)
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from engines.core.analysis import safe_dt


# =============================================================================
# ZONE DEFINITIONS
# =============================================================================

# Coggan 7-zone power zones, expressed as % FTP boundaries.
# (label, min_pct_inclusive, max_pct_exclusive — except Z7 which is open-ended)
COGGAN_POWER_ZONES = [
    ("Z1", "Active Recovery",       0.00, 0.55),
    ("Z2", "Endurance",             0.55, 0.76),
    ("Z3", "Tempo",                 0.76, 0.91),
    ("Z4", "Lactate Threshold",     0.91, 1.06),
    ("Z5", "VO₂max",                1.06, 1.21),
    ("Z6", "Anaerobic Capacity",    1.21, 1.51),
    ("Z7", "Neuromuscular Power",   1.51, float("inf")),
]

# Friel 5-zone HR zones, expressed as % LTHR boundaries.
# Note: Friel uses 5 zones but splits Z5 into Z5a/b/c. We keep 7 buckets
# to preserve granularity at the top end.
FRIEL_HR_ZONES = [
    ("Z1",  "Recovery",         0.00, 0.81),
    ("Z2",  "Endurance",        0.81, 0.89),
    ("Z3",  "Tempo",            0.89, 0.94),
    ("Z4",  "Sub-Threshold",    0.94, 1.00),
    ("Z5a", "Threshold",        1.00, 1.03),
    ("Z5b", "VO₂max",           1.03, 1.07),
    ("Z5c", "Anaerobic",        1.07, float("inf")),
]


# =============================================================================
# PRIMARY TIME-IN-ZONE COMPUTATION
# =============================================================================

def _stream_arrays(stream) -> Dict[str, np.ndarray]:
    """Extract (t, power, hr) as float arrays. Power None\u21920, HR None\u2192nan."""
    t = np.array(stream.elapsed_s, dtype=float)
    p = np.array([
        float(v) if v is not None and v >= 0 else 0.0
        for v in stream.power
    ], dtype=float)
    h = np.array([
        float(v) if v is not None and 30 <= v <= 230 else np.nan
        for v in stream.heart_rate
    ], dtype=float)
    return {"t": t, "power": p, "hr": h}


def _time_in_bins(
    values: np.ndarray,
    boundaries: List[Tuple[str, str, float, float]],
    anchor: float,
    sample_dt_s: float = 1.0,
    valid_mask: Optional[np.ndarray] = None,
) -> List[Dict[str, Any]]:
    """
    Generic time-in-zone bucketer.

    boundaries: list of (zone_code, label, lo_factor, hi_factor)
    anchor: scalar (FTP or LTHR) that scales the boundaries
    valid_mask: optional bool array — only count samples where True
    """
    if values.size == 0:
        return []

    if valid_mask is None:
        valid_mask = ~np.isnan(values)
    else:
        valid_mask = valid_mask & ~np.isnan(values)

    total_valid_s = float(valid_mask.sum() * sample_dt_s)

    out: List[Dict[str, Any]] = []
    for code, label, lo_f, hi_f in boundaries:
        lo = lo_f * anchor
        hi = hi_f * anchor
        in_zone = valid_mask & (values >= lo) & (values < hi)
        time_s = float(in_zone.sum() * sample_dt_s)
        pct = (time_s / total_valid_s * 100.0) if total_valid_s > 0 else 0.0
        out.append({
            "zone": code,
            "label": label,
            "min_pct_anchor": round(lo_f * 100, 1),
            "max_pct_anchor": round(hi_f * 100, 1) if hi_f != float("inf") else None,
            "min_value": round(lo, 1),
            "max_value": round(hi, 1) if hi != float("inf") else None,
            "time_s": int(time_s),
            "time_pct": round(pct, 1),
        })

    return out


# =============================================================================
# COGGAN POWER ZONES
# =============================================================================

def coggan_power_zones(stream, ftp: float) -> Dict[str, Any]:
    """Time-in-zone breakdown using Coggan's 7-zone power model."""
    if ftp <= 0:
        return {"available": False, "reason": "INVALID_FTP"}

    arrs = _stream_arrays(stream)
    p = arrs["power"]
    t = arrs["t"]
    if p.size == 0 or not (p > 0).any():
        return {"available": False, "reason": "NO_POWER_DATA"}

    dt = safe_dt(t)

    # Only count moving samples (power > 0). Stops/coasting at zero power
    # otherwise inflate Z1 artificially.
    valid_mask = p > 0

    zones = _time_in_bins(p, COGGAN_POWER_ZONES, anchor=ftp,
                          sample_dt_s=dt, valid_mask=valid_mask)

    return {
        "available": True,
        "model": "Coggan 7-zone",
        "anchor_ftp_w": round(ftp, 1),
        "total_moving_time_s": int(valid_mask.sum() * dt),
        "zones": zones,
        "reference": "Coggan & Allen 2010",
    }


# =============================================================================
# FRIEL HR ZONES
# =============================================================================

def friel_hr_zones(stream, lthr: float) -> Dict[str, Any]:
    """Time-in-zone breakdown using Friel's HR-based zone model."""
    if lthr <= 0:
        return {"available": False, "reason": "INVALID_LTHR"}

    arrs = _stream_arrays(stream)
    h = arrs["hr"]
    t = arrs["t"]
    if not np.any(~np.isnan(h)):
        return {"available": False, "reason": "NO_HR_DATA"}

    dt = safe_dt(t)
    zones = _time_in_bins(h, FRIEL_HR_ZONES, anchor=lthr, sample_dt_s=dt)

    return {
        "available": True,
        "model": "Friel 5-zone (7 buckets)",
        "anchor_lthr_bpm": round(lthr, 1),
        "total_hr_time_s": int(np.sum(~np.isnan(h)) * dt),
        "zones": zones,
        "reference": "Friel 2009",
    }


# =============================================================================
# SEILER 3-ZONE POLARIZATION
# =============================================================================

# Polarization classification thresholds (St\u00f6ggl & Sperlich 2014):
# - Polarized:  Z1 \u2265 75%, Z3 \u2265 15%, Z2 \u2264 10%
# - Pyramidal:  Z1 > Z2 > Z3, all > 0%, and not polarized
# - Threshold:  Z2 \u2265 35% (dominant zone is the middle band)
# - Mixed:      none of the above
_POLARIZED_Z1_MIN = 75.0
_POLARIZED_Z3_MIN = 15.0
_POLARIZED_Z2_MAX = 10.0
_THRESHOLD_Z2_MIN = 35.0


def _classify_distribution(z1: float, z2: float, z3: float) -> str:
    """Classify training intensity distribution per St\u00f6ggl & Sperlich."""
    if z1 >= _POLARIZED_Z1_MIN and z3 >= _POLARIZED_Z3_MIN and z2 <= _POLARIZED_Z2_MAX:
        return "POLARIZED"
    if z2 >= _THRESHOLD_Z2_MIN:
        return "THRESHOLD"
    if z1 > z2 > z3 and z3 > 0:
        return "PYRAMIDAL"
    return "MIXED"


def seiler_polarization(
    stream,
    vt1_w: Optional[float] = None,
    vt2_w: Optional[float] = None,
    vt1_bpm: Optional[float] = None,
    vt2_bpm: Optional[float] = None,
    prefer: str = "auto",
) -> Dict[str, Any]:
    """
    Compute the Seiler 3-zone distribution and classify the session.

    The 3 zones are anchored on VT1/VT2. Caller can supply either:
      - power-based thresholds (vt1_w, vt2_w) — preferred for cycling with PM
      - HR-based thresholds (vt1_bpm, vt2_bpm) — fallback for HR-only

    prefer = "auto" | "power" | "hr"
      auto: use power if available and stream has power, else HR
    """
    arrs = _stream_arrays(stream)
    t = arrs["t"]
    dt = safe_dt(t)

    use_power = False
    use_hr = False

    if prefer == "power" or (
        prefer == "auto"
        and vt1_w is not None and vt2_w is not None
        and (arrs["power"] > 0).any()
    ):
        use_power = True
    elif prefer == "hr" or (
        prefer == "auto"
        and vt1_bpm is not None and vt2_bpm is not None
        and np.any(~np.isnan(arrs["hr"]))
    ):
        use_hr = True

    if not (use_power or use_hr):
        return {
            "available": False,
            "reason": "MISSING_THRESHOLDS_OR_DATA",
        }

    if use_power:
        if vt1_w is None or vt2_w is None:
            raise ValueError("vt1_w and vt2_w are required for power-based Seiler zones")
        values = arrs["power"]
        valid = values > 0
        thr_lo, thr_hi = float(vt1_w), float(vt2_w)
        anchor_label = "power"
        anchor_units = "W"
    else:
        if vt1_bpm is None or vt2_bpm is None:
            raise ValueError("vt1_bpm and vt2_bpm are required for HR-based Seiler zones")
        values = arrs["hr"]
        valid = ~np.isnan(values)
        thr_lo, thr_hi = float(vt1_bpm), float(vt2_bpm)
        anchor_label = "hr"
        anchor_units = "bpm"

    if thr_hi <= thr_lo:
        return {"available": False, "reason": "VT2_NOT_ABOVE_VT1"}

    z1_mask = valid & (values < thr_lo)
    z2_mask = valid & (values >= thr_lo) & (values < thr_hi)
    z3_mask = valid & (values >= thr_hi)

    total_valid_s = float(valid.sum() * dt)
    if total_valid_s <= 0:
        return {"available": False, "reason": "NO_VALID_SAMPLES"}

    z1_s = float(z1_mask.sum() * dt)
    z2_s = float(z2_mask.sum() * dt)
    z3_s = float(z3_mask.sum() * dt)

    z1_pct = round(z1_s / total_valid_s * 100.0, 1)
    z2_pct = round(z2_s / total_valid_s * 100.0, 1)
    z3_pct = round(z3_s / total_valid_s * 100.0, 1)

    distribution = _classify_distribution(z1_pct, z2_pct, z3_pct)

    interpretations = {
        "POLARIZED":  "Polarized session: high volume of easy work + targeted high-intensity (Seiler model).",
        "PYRAMIDAL":  "Pyramidal session: progressively less time in higher zones — typical base-period structure.",
        "THRESHOLD":  "Threshold-dominant session: bulk of time at sweet-spot/lactate-threshold intensity.",
        "MIXED":      "Mixed distribution that doesn't fit a single classification.",
    }

    return {
        "available": True,
        "model": "Seiler 3-zone",
        "anchor_type": anchor_label,
        "anchor_units": anchor_units,
        "vt1": round(thr_lo, 1),
        "vt2": round(thr_hi, 1),
        "z1_pct": z1_pct, "z1_s": int(z1_s),
        "z2_pct": z2_pct, "z2_s": int(z2_s),
        "z3_pct": z3_pct, "z3_s": int(z3_s),
        "total_valid_s": int(total_valid_s),
        "distribution_class": distribution,
        "interpretation": interpretations[distribution],
        "reference": "Seiler 2010; St\u00f6ggl & Sperlich 2014",
    }


# =============================================================================
# UNIFIED API
# =============================================================================

class ZonesEngine:
    """
    Computes all three zone-system breakdowns at once.

    Each system is independent — if the corresponding anchor is missing,
    that section is reported as not available rather than failing.

    Usage:
        engine = ZonesEngine(ftp=300, lthr=170)
        result = engine.analyze(
            stream,
            vt1_w=185, vt2_w=275,           # for polarization (preferred)
            vt1_bpm=145, vt2_bpm=170,        # fallback for polarization
        )
    """

    def __init__(self, ftp: Optional[float] = None, lthr: Optional[float] = None):
        self.ftp = ftp
        self.lthr = lthr

    def analyze(
        self,
        stream,
        vt1_w: Optional[float] = None,
        vt2_w: Optional[float] = None,
        vt1_bpm: Optional[float] = None,
        vt2_bpm: Optional[float] = None,
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "status": "success",
            "schema_version": "1.0.0",
        }

        if self.ftp is not None and self.ftp > 0:
            out["coggan_power"] = coggan_power_zones(stream, self.ftp)
        else:
            out["coggan_power"] = {"available": False, "reason": "FTP_NOT_PROVIDED"}

        if self.lthr is not None and self.lthr > 0:
            out["friel_hr"] = friel_hr_zones(stream, self.lthr)
        else:
            out["friel_hr"] = {"available": False, "reason": "LTHR_NOT_PROVIDED"}

        out["seiler_polarization"] = seiler_polarization(
            stream,
            vt1_w=vt1_w, vt2_w=vt2_w,
            vt1_bpm=vt1_bpm, vt2_bpm=vt2_bpm,
        )

        return out
