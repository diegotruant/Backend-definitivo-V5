"""
Athlete-level MMP aggregation — extract, merge, readiness
=========================================================

Pure functions for Supabase-backed rolling MMP curves. The backend computes;
Supabase persists via ``MmpAggregateStore``.

Each activity contributes duration/power points; the aggregate keeps the best
power per duration with provenance (source activity / file / date).
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

# Key duration families for readiness gating (seconds).
MMP_DURATION_FAMILIES: Dict[str, List[int]] = {
    "sprint": [1, 5, 10, 15],
    "anaerobic": [30, 45, 60, 90],
    "vo2_map": [180, 240, 300, 420],
    "threshold": [1200, 1800, 2400],
    "endurance": [3600, 5400],
}

ALL_KEY_DURATIONS: List[int] = sorted(
    {duration for durations in MMP_DURATION_FAMILIES.values() for duration in durations}
)

MMP_STATUS_COLLECTING = "collecting"
MMP_STATUS_PROVISIONAL = "provisional"
MMP_STATUS_PUBLISHED = "published"

EXPOSABLE_MMP_STATUSES = frozenset({MMP_STATUS_PROVISIONAL, MMP_STATUS_PUBLISHED})


def _normalize_point(
    row: Dict[str, Any],
    *,
    activity_id: str,
    activity_file_id: str,
    activity_date: str,
) -> Dict[str, Any] | None:
    try:
        duration_s = int(row["duration_s"])
        power_w = float(row["power_w"])
    except (KeyError, TypeError, ValueError):
        return None
    if duration_s <= 0 or power_w <= 0:
        return None
    return {
        "duration_s": duration_s,
        "power_w": round(power_w, 1),
        "source_activity_id": str(row.get("source_activity_id") or activity_id),
        "source_file_id": str(row.get("source_file_id") or activity_file_id),
        "activity_date": str(row.get("activity_date") or activity_date)[:10],
    }


def extract_mmp_points(
    bundle: Dict[str, Any],
    *,
    activity_id: str,
    activity_file_id: str,
    activity_date: str,
) -> List[Dict[str, Any]]:
    """
    Extract per-activity MMP points from a full activity bundle.

    Primary source: ``workout_summary.sections.power.mmp_curve``.
    Fallback: ``activity_intelligence.best_efforts_power.efforts``.
    """
    points: List[Dict[str, Any]] = []
    seen: set[int] = set()

    summary = bundle.get("workout_summary") or {}
    power_section = ((summary.get("sections") or {}).get("power") or {})
    for row in power_section.get("mmp_curve") or []:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_point(
            row,
            activity_id=activity_id,
            activity_file_id=activity_file_id,
            activity_date=activity_date,
        )
        if normalized and normalized["duration_s"] not in seen:
            points.append(normalized)
            seen.add(normalized["duration_s"])

    intelligence = bundle.get("activity_intelligence") or {}
    efforts_block = intelligence.get("best_efforts_power") or {}
    for row in efforts_block.get("efforts") or []:
        if not isinstance(row, dict):
            continue
        mapped = {
            "duration_s": row.get("duration_s"),
            "power_w": row.get("value") or row.get("power_w"),
        }
        normalized = _normalize_point(
            mapped,
            activity_id=activity_id,
            activity_file_id=activity_file_id,
            activity_date=activity_date,
        )
        if normalized and normalized["duration_s"] not in seen:
            points.append(normalized)
            seen.add(normalized["duration_s"])

    return sorted(points, key=lambda p: p["duration_s"])


def merge_mmp_curves(
    existing_mmp: List[Dict[str, Any]],
    new_points: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Merge existing aggregate MMP with new activity points.

    For each duration keep the highest ``power_w``. Returns merged curve and
  the list of points that improved (or newly added) the aggregate.
    """
    by_duration: Dict[int, Dict[str, Any]] = {}
    for row in existing_mmp or []:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_point(
            row,
            activity_id=str(row.get("source_activity_id") or ""),
            activity_file_id=str(row.get("source_file_id") or ""),
            activity_date=str(row.get("activity_date") or "")[:10],
        )
        if normalized:
            by_duration[normalized["duration_s"]] = normalized

    improvements: List[Dict[str, Any]] = []
    for row in new_points or []:
        if not isinstance(row, dict):
            continue
        duration_s = int(row["duration_s"])
        power_w = float(row["power_w"])
        previous = by_duration.get(duration_s)
        if previous is None or power_w > float(previous["power_w"]):
            by_duration[duration_s] = dict(row)
            improvements.append(dict(row))

    merged = [by_duration[d] for d in sorted(by_duration)]
    return merged, improvements


def _families_covered(mmp_curve: Sequence[Dict[str, Any]]) -> Dict[str, bool]:
    durations = {
        int(p["duration_s"])
        for p in mmp_curve
        if isinstance(p, dict) and float(p.get("power_w") or 0) > 0
    }
    return {
        family: any(d in durations for d in family_durations)
        for family, family_durations in MMP_DURATION_FAMILIES.items()
    }


def evaluate_mmp_readiness(mmp_curve: List[Dict[str, Any]], n_activities: int) -> Dict[str, Any]:
    """
    Evaluate whether the athlete MMP curve may be exposed to the frontend.

    Rules (initial):
    - collecting: < 5 activities OR fewer than 3 duration families covered
    - provisional: >= 5 activities AND >= 3 families covered
    - published: >= 8 activities AND >= 4 families including vo2_map + threshold
    """
    covered_key_durations = sorted(
        int(p["duration_s"])
        for p in mmp_curve
        if isinstance(p, dict) and float(p.get("power_w") or 0) > 0 and int(p["duration_s"]) in ALL_KEY_DURATIONS
    )
    missing_durations = [d for d in ALL_KEY_DURATIONS if d not in covered_key_durations]
    coverage_score = round(len(covered_key_durations) / max(len(ALL_KEY_DURATIONS), 1), 4)

    families = _families_covered(mmp_curve)
    n_families = sum(1 for covered in families.values() if covered)

    if (
        n_activities >= 8
        and n_families >= 4
        and families.get("vo2_map")
        and families.get("threshold")
    ):
        mmp_status = MMP_STATUS_PUBLISHED
        confidence_tier = "high"
    elif n_activities >= 5 and n_families >= 3:
        mmp_status = MMP_STATUS_PROVISIONAL
        confidence_tier = "medium"
    else:
        mmp_status = MMP_STATUS_COLLECTING
        confidence_tier = "low"

    return {
        "coverage_score": coverage_score,
        "confidence_tier": confidence_tier,
        "mmp_status": mmp_status,
        "missing_durations": missing_durations,
        "covered_key_durations": covered_key_durations,
        "n_key_durations_covered": len(covered_key_durations),
        "n_duration_families_covered": n_families,
        "duration_families_covered": {k: v for k, v in families.items() if v},
        "expose_to_frontend": mmp_status in EXPOSABLE_MMP_STATUSES,
    }


def public_mmp_curve(mmp_curve: List[Dict[str, Any]], readiness: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return curve for API/frontend only when status allows exposure."""
    if readiness.get("expose_to_frontend"):
        return list(mmp_curve)
    return []
