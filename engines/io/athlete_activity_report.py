"""Athlete-level activity report with stable metabolic profile section."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _activity_session_metrics(activity: Dict[str, Any]) -> Dict[str, Any]:
    bundle = activity.get("bundle") or activity
    summary = bundle.get("workout_summary") or {}
    sections = summary.get("sections") or {}
    intelligence = bundle.get("activity_intelligence") or {}

    power = sections.get("power") or {}
    cardiac = sections.get("cardiac") or {}
    hrv = sections.get("hrv") or {}
    mader = sections.get("mader_durability") or {}
    pedaling = bundle.get("pedaling_balance") or {}

    return {
        "activity_id": activity.get("activity_id") or bundle.get("activity_id"),
        "activity_date": activity.get("activity_date") or summary.get("activity_date"),
        "power_metrics": power.get("summary") or power,
        "hr_metrics": cardiac.get("summary") or cardiac,
        "dfa_alpha1": hrv.get("dfa_alpha1") or hrv.get("summary"),
        "decoupling": intelligence.get("cardiac_decoupling"),
        "durability": mader if mader.get("status") == "success" else bundle.get("durability_index"),
        "pedaling_mechanics": pedaling,
    }


def _athlete_profile_section(active_profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "profile_version": active_profile.get("profile_version"),
        "calculated_at": active_profile.get("calculated_at"),
        "valid_from_date": active_profile.get("valid_from_date"),
        "profile_status": active_profile.get("profile_status"),
        "confidence_score": active_profile.get("confidence_score"),
        "confidence_tier": active_profile.get("confidence_tier"),
        "n_activities_included": active_profile.get("n_activities_included"),
        "source_coverage_score": active_profile.get("source_coverage_score"),
        "vo2max_ml_kg_min": active_profile.get("vo2max_ml_kg_min"),
        "vlamax_mmol_l_s": active_profile.get("vlamax_mmol_l_s"),
        "map_power_w": active_profile.get("map_power_w"),
        "mlss_power_w": active_profile.get("mlss_power_w"),
        "apr_w": active_profile.get("apr_w"),
        "fatmax_power_w": active_profile.get("fatmax_power_w"),
        "phenotype_type": active_profile.get("phenotype_type"),
        "phenotype_description": active_profile.get("phenotype_description"),
        "warnings": active_profile.get("warnings") or [],
        "note": "Stable athlete profile — derived from published aggregate MMP only.",
    }


def build_athlete_activity_report(
    *,
    athlete_id: str,
    activities: List[Dict[str, Any]],
    active_profile: Optional[Dict[str, Any]] = None,
    mmp_aggregate: Optional[Dict[str, Any]] = None,
    mmp_contributions: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Build report with one athlete-level metabolic profile section and per-activity
    session metrics (no per-activity VO2max/VLamax/MLSS as definitive profile).
    """
    contributions = mmp_contributions or {}
    activity_rows: List[Dict[str, Any]] = []

    for activity in activities:
        activity_id = str(activity.get("activity_id") or "")
        contrib = contributions.get(activity_id) or {}
        improved = contrib.get("improved_durations") or contrib.get("improvements") or []
        activity_rows.append(
            {
                **_activity_session_metrics(activity),
                "contributed_to_mmp": bool(contrib.get("contributed", contrib)),
                "mmp_improved_durations": improved,
            }
        )

    profile_section: Dict[str, Any]
    if active_profile:
        profile_section = {
            "status": "available",
            "title": "Profilo metabolico atleta attivo",
            **_athlete_profile_section(active_profile),
        }
    else:
        mmp_status = (mmp_aggregate or {}).get("mmp_status", "collecting")
        profile_section = {
            "status": "not_available",
            "title": "Profilo metabolico atleta attivo",
            "reason": "MMP not published yet" if mmp_status != "published" else "No active profile",
            "mmp_status": mmp_status,
            "message": "Dati insufficienti per generare un profilo metabolico attendibile.",
        }

    return {
        "status": "success",
        "athlete_id": athlete_id,
        "athlete_metabolic_profile": profile_section,
        "mmp_aggregate_status": (mmp_aggregate or {}).get("mmp_status"),
        "activities": activity_rows,
        "notes": [
            "Per-activity metabolic snapshots are deprecated for athlete profile use.",
            "Use GET /athletes/{athlete_id}/metabolic-profile/current for the active profile.",
        ],
    }
