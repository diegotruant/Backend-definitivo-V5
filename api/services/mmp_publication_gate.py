"""Internal publication policy for a longitudinal MMP curve.

This module is intentionally NOT wired to FastAPI response models, TwinState
or Supabase yet. It evaluates the canonical ``rolling_power_curve`` and
returns an internal, JSON-safe assessment that can later back ``mmp_state.v1``
after frontend coordination.

The gate is conservative and explicitly HEURISTIC: it does not claim external
scientific validation. It prevents activity count alone from making a curve
publishable and instead checks physiological coverage, curve integrity,
provenance, freshness and anchor reliability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Dict, List, Mapping, Optional, Tuple

from engines.performance.mmp_quality import analyze_mmp_quality

MMP_GATE_TIER = "HEURISTIC"
DEFAULT_WINDOW_DAYS = 90

# Each band is (minimum duration, maximum duration, anchors required for
# publication-grade coverage). The ranges are frozen in the MMP frontend
# contract; the minimum counts remain internal backend policy.
BAND_REQUIREMENTS: Dict[str, Tuple[int, int, int]] = {
    "sprint": (5, 15, 1),
    "glycolytic": (20, 60, 1),
    "vo2": (180, 720, 2),
    "threshold": (1200, 3600, 2),
}

_MIN_PUBLISHED_SOURCE_ACTIVITIES = 3
_MIN_PROVISIONAL_SOURCE_ACTIVITIES = 2
_MIN_PUBLISHED_MEDIAN_RELIABILITY = 0.80
_MIN_PUBLISHED_ANCHOR_RELIABILITY = 0.60
_MIN_PROVISIONAL_MEDIAN_RELIABILITY = 0.65
_MIN_PROVISIONAL_ANCHOR_RELIABILITY = 0.50


@dataclass(frozen=True)
class MMPGateAssessment:
    """Internal decision returned by :func:`evaluate_mmp_gate`."""

    lifecycle_status: str
    profile_eligible: bool
    profile_stale: bool
    frontend_visibility: str
    quality: Dict[str, Any]
    coverage: Dict[str, str]
    anchor_count: int
    source_activity_count: int
    critical_durations_present: List[int]
    stale_durations: List[int] = field(default_factory=list)
    missing_date_durations: List[int] = field(default_factory=list)
    decision_reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    tier: str = MMP_GATE_TIER

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lifecycle_status": self.lifecycle_status,
            "profile_eligible": self.profile_eligible,
            "profile_stale": self.profile_stale,
            "frontend_visibility": self.frontend_visibility,
            "quality": self.quality,
            "coverage": self.coverage,
            "anchor_count": self.anchor_count,
            "source_activity_count": self.source_activity_count,
            "critical_durations_present": self.critical_durations_present,
            "stale_durations": self.stale_durations,
            "missing_date_durations": self.missing_date_durations,
            "decision_reasons": self.decision_reasons,
            "warnings": self.warnings,
            "tier": self.tier,
        }


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _coerce_curve(curve: Optional[Mapping[Any, Any]]) -> Dict[int, Dict[str, Any]]:
    """Normalize the frozen rolling_power_curve shape without mutating input."""

    normalized: Dict[int, Dict[str, Any]] = {}
    if not curve:
        return normalized

    for raw_key, raw_value in curve.items():
        try:
            key_duration = int(raw_key)
        except (TypeError, ValueError):
            continue

        if isinstance(raw_value, Mapping):
            raw_duration = raw_value.get("duration_s", key_duration)
            raw_power = raw_value.get("power_w")
            if raw_power is None:
                continue
            try:
                duration_s = int(raw_duration)
                power_w = float(raw_power)
            except (TypeError, ValueError):
                continue
            ride_id = str(raw_value.get("ride_id") or "unknown")
            ride_date = str(raw_value.get("ride_date") or "")
            raw_reliability = raw_value.get("reliability", 1.0)
            try:
                reliability = float(raw_reliability)
            except (TypeError, ValueError):
                reliability = 0.0
        else:
            try:
                duration_s = key_duration
                power_w = float(raw_value)
            except (TypeError, ValueError):
                continue
            ride_id = "historical"
            ride_date = ""
            reliability = 1.0

        if duration_s <= 0 or power_w <= 0:
            continue
        reliability = max(0.0, min(1.0, reliability))

        candidate = {
            "duration_s": duration_s,
            "power_w": power_w,
            "ride_id": ride_id,
            "ride_date": ride_date,
            "reliability": reliability,
        }
        existing = normalized.get(duration_s)
        if existing is None or power_w > float(existing["power_w"]):
            normalized[duration_s] = candidate

    return dict(sorted(normalized.items()))


def _coverage_for(curve: Mapping[int, Mapping[str, Any]]) -> Dict[str, str]:
    coverage: Dict[str, str] = {}
    for band, (start_s, end_s, required_count) in BAND_REQUIREMENTS.items():
        count = sum(1 for duration_s in curve if start_s <= duration_s <= end_s)
        if count == 0:
            coverage[band] = "missing"
        elif count < required_count:
            coverage[band] = "partial"
        else:
            coverage[band] = "present"
    return coverage


def _visibility_for(status: str) -> str:
    return {
        "collecting": "progress_only",
        "provisional": "coach_preview",
        "published": "show",
        "degraded": "coach_preview",
        "invalid": "hidden",
    }[status]


def evaluate_mmp_gate(
    rolling_power_curve: Optional[Mapping[Any, Any]],
    *,
    as_of: Optional[Any] = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    previous_lifecycle_status: Optional[str] = None,
) -> MMPGateAssessment:
    """Evaluate whether a rolling MMP curve is safe for profile publication.

    The result is internal-only. No API or TwinState field is changed by this
    function. ``previous_lifecycle_status`` is used only to distinguish a
    newly incomplete curve (``collecting``) from a formerly published curve
    that has lost required evidence (``degraded``).
    """

    curve = _coerce_curve(rolling_power_curve)
    mmp = {
        duration_s: float(entry["power_w"])
        for duration_s, entry in curve.items()
    }
    samples = [
        {
            "duration_s": duration_s,
            "power_w": entry["power_w"],
            "filename": entry["ride_id"],
            "date": entry["ride_date"],
        }
        for duration_s, entry in curve.items()
        if entry["ride_id"] not in {"", "unknown", "historical"}
    ]
    quality_report = analyze_mmp_quality(mmp, samples or None)
    quality = quality_report.to_dict()
    blocking_issues = [
        issue.to_dict()
        for issue in quality_report.issues
        if issue.severity == "error"
    ]
    quality["blocking_issues"] = blocking_issues

    coverage = _coverage_for(curve)
    critical_durations = sorted(
        duration_s
        for duration_s in curve
        if any(
            start_s <= duration_s <= end_s
            for start_s, end_s, _ in BAND_REQUIREMENTS.values()
        )
    )

    source_ids = {
        str(entry["ride_id"])
        for entry in curve.values()
        if str(entry["ride_id"]) not in {"", "unknown", "historical"}
    }
    source_activity_count = len(source_ids)

    reference_date = _parse_date(as_of) or date.today()
    cutoff = reference_date - timedelta(days=max(1, int(window_days)))
    stale_durations: List[int] = []
    missing_date_durations: List[int] = []
    reliabilities: List[float] = []

    for duration_s in critical_durations:
        entry = curve[duration_s]
        reliabilities.append(float(entry["reliability"]))
        achieved_on = _parse_date(entry["ride_date"])
        if achieved_on is None:
            missing_date_durations.append(duration_s)
        elif achieved_on < cutoff:
            stale_durations.append(duration_s)

    median_reliability = median(reliabilities) if reliabilities else 0.0
    minimum_reliability = min(reliabilities) if reliabilities else 0.0

    all_bands_present = all(value == "present" for value in coverage.values())
    non_missing_band_count = sum(
        value != "missing" for value in coverage.values()
    )
    core_bands_available = (
        coverage["vo2"] != "missing"
        and coverage["threshold"] != "missing"
    )
    quality_good = quality_report.classification == "good"
    quality_usable = quality_report.classification in {"good", "fair"}

    reasons: List[str] = []
    warnings: List[str] = []

    for band, state in coverage.items():
        if state == "missing":
            reasons.append(f"{band} duration band is missing.")
        elif state == "partial":
            reasons.append(f"{band} duration band has only partial coverage.")

    if source_activity_count < _MIN_PUBLISHED_SOURCE_ACTIVITIES:
        reasons.append(
            "Fewer than three independent source activities contribute winning anchors."
        )
    if stale_durations:
        reasons.append(
            "One or more required anchors are older than the rolling freshness window."
        )
    if missing_date_durations:
        reasons.append("One or more required anchors have no valid provenance date.")
    if median_reliability < _MIN_PUBLISHED_MEDIAN_RELIABILITY:
        reasons.append("Median anchor reliability is below the publication threshold.")
    if minimum_reliability < _MIN_PUBLISHED_ANCHOR_RELIABILITY:
        reasons.append("At least one anchor reliability is below the publication minimum.")
    if not quality_good:
        reasons.append(
            f"MMP quality classification is {quality_report.classification}, not good."
        )
    if blocking_issues:
        reasons.append("Blocking MMP integrity issue detected.")

    if not curve:
        warnings.append("No accepted MMP anchors are available yet.")
    if source_activity_count == 0 and curve:
        warnings.append("Winning anchors have no independent activity provenance.")

    published = (
        bool(curve)
        and not blocking_issues
        and all_bands_present
        and quality_good
        and source_activity_count >= _MIN_PUBLISHED_SOURCE_ACTIVITIES
        and not stale_durations
        and not missing_date_durations
        and median_reliability >= _MIN_PUBLISHED_MEDIAN_RELIABILITY
        and minimum_reliability >= _MIN_PUBLISHED_ANCHOR_RELIABILITY
    )

    provisional = (
        bool(curve)
        and not blocking_issues
        and not published
        and core_bands_available
        and non_missing_band_count >= 3
        and quality_usable
        and source_activity_count >= _MIN_PROVISIONAL_SOURCE_ACTIVITIES
        and not any(
            duration_s in stale_durations
            or duration_s in missing_date_durations
            for duration_s in critical_durations
            if 180 <= duration_s <= 3600
        )
        and median_reliability >= _MIN_PROVISIONAL_MEDIAN_RELIABILITY
        and minimum_reliability >= _MIN_PROVISIONAL_ANCHOR_RELIABILITY
    )

    if blocking_issues:
        status = "invalid"
    elif published:
        status = "published"
    elif previous_lifecycle_status == "published":
        status = "degraded"
    elif provisional:
        status = "provisional"
    else:
        status = "collecting"

    return MMPGateAssessment(
        lifecycle_status=status,
        profile_eligible=status == "published",
        profile_stale=status == "degraded",
        frontend_visibility=_visibility_for(status),
        quality=quality,
        coverage=coverage,
        anchor_count=len(curve),
        source_activity_count=source_activity_count,
        critical_durations_present=critical_durations,
        stale_durations=stale_durations,
        missing_date_durations=missing_date_durations,
        decision_reasons=reasons,
        warnings=warnings,
    )
