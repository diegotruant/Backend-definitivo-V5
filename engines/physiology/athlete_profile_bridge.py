"""Bridge versioned athlete stores into TwinState / engine-compatible payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional

PROFILE_SOURCE = "athlete_metabolic_profile_versions"
THRESHOLD_SOURCE = "athlete_threshold_versions"


def versioned_profile_to_metabolic_snapshot(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Convert active athlete metabolic profile row into profiler-compatible snapshot."""
    if not profile:
        return {"status": "unavailable", "reason": "NO_ACTIVE_PROFILE"}

    vo2 = profile.get("vo2max_ml_kg_min")
    vlamax = profile.get("vlamax_mmol_l_s")
    mlss = profile.get("mlss_power_w")
    map_w = profile.get("map_power_w")
    fatmax = profile.get("fatmax_power_w")

    return {
        "status": "success",
        "source": PROFILE_SOURCE,
        "profile_version": profile.get("profile_version"),
        "profile_status": profile.get("profile_status"),
        "confidence_score": profile.get("confidence_score"),
        "confidence_tier": profile.get("confidence_tier"),
        "vo2max_ml_kg_min": vo2,
        "estimated_vo2max": vo2,
        "vlamax": vlamax,
        "vlamax_mmol_l_s": vlamax,
        "mlss_power_watts": mlss,
        "mlss_w": mlss,
        "map_aerobic_w": map_w,
        "map_w": map_w,
        "fatmax_w": fatmax,
        "fatmax_power_watts": fatmax,
        "apr_w": profile.get("apr_w"),
        "phenotype_type": profile.get("phenotype_type"),
        "phenotype_description": profile.get("phenotype_description"),
        "is_athlete_level_profile": True,
        "do_not_use_as_activity_estimate": False,
        "derivation": {
            "source": "published_aggregate_mmp",
            "calculated_at": profile.get("calculated_at"),
            "valid_from_date": profile.get("valid_from_date"),
        },
        "warnings": list(profile.get("warnings") or []),
    }


def versioned_thresholds_to_athlete_profile_patch(thresholds: Dict[str, Any]) -> Dict[str, Any]:
    """Patch twin athlete_profile fields from active threshold version."""
    if not thresholds:
        return {}
    patch: Dict[str, Any] = {
        "threshold_version": thresholds.get("threshold_version"),
        "threshold_source": thresholds.get("source_type") or THRESHOLD_SOURCE,
    }
    if thresholds.get("ftp_w") is not None:
        patch["ftp_w"] = thresholds["ftp_w"]
    if thresholds.get("lthr_bpm") is not None:
        patch["lthr_bpm"] = thresholds["lthr_bpm"]
    if thresholds.get("cp_w") is not None:
        patch["cp_w"] = thresholds["cp_w"]
    if thresholds.get("w_prime_j") is not None:
        patch["w_prime_j"] = thresholds["w_prime_j"]
    return patch


def resolve_active_athlete_model(
    *,
    metabolic_profile: Optional[Dict[str, Any]] = None,
    thresholds: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Package active athlete model fragments for twin / dashboard consumers."""
    snapshot = (
        versioned_profile_to_metabolic_snapshot(metabolic_profile)
        if metabolic_profile
        else {"status": "unavailable", "reason": "NO_ACTIVE_PROFILE"}
    )
    return {
        "status": "success" if snapshot.get("status") == "success" else "partial",
        "metabolic_snapshot": snapshot,
        "metabolic_metrics": _metrics_from_snapshot(snapshot),
        "athlete_profile_patch": versioned_thresholds_to_athlete_profile_patch(thresholds or {}),
        "zone_anchors": build_zone_anchors_from_model(metabolic_profile, thresholds),
    }


def _metrics_from_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    if snapshot.get("status") != "success":
        return {}
    return {
        "cp_w": snapshot.get("mlss_power_watts") or snapshot.get("mlss_w"),
        "vo2max_ml_kg_min": snapshot.get("vo2max_ml_kg_min") or snapshot.get("estimated_vo2max"),
        "vlamax_mmol_l_s": snapshot.get("vlamax_mmol_l_s") or snapshot.get("vlamax"),
        "fatmax_w": snapshot.get("fatmax_w") or snapshot.get("fatmax_power_watts"),
        "map_w": snapshot.get("map_w") or snapshot.get("map_aerobic_w"),
        "ftp_w": snapshot.get("ftp_w"),
    }


def build_zone_anchors_from_model(
    metabolic_profile: Optional[Dict[str, Any]],
    thresholds: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Stable zone anchors for athlete-level prescription (not per-activity)."""
    profile = metabolic_profile or {}
    thresh = thresholds or {}
    mlss = profile.get("mlss_power_w")
    map_w = profile.get("map_power_w")
    ftp = thresh.get("ftp_w")
    lthr = thresh.get("lthr_bpm")
    cp_w = thresh.get("cp_w") or mlss

    anchors: Dict[str, Any] = {
        "status": "unavailable",
        "source": "athlete_active_model",
    }
    if mlss:
        anchors.update(
            {
                "status": "success",
                "mlss_w": float(mlss),
                "map_w": float(map_w) if map_w else None,
                "vt1_w": round(float(mlss) * 0.75, 1),
                "vt2_w": round(float(mlss), 1),
            }
        )
    if ftp:
        anchors["ftp_w"] = float(ftp)
    if lthr:
        anchors["lthr_bpm"] = float(lthr)
    if cp_w:
        anchors["cp_w"] = float(cp_w)
    if thresh.get("w_prime_j") is not None:
        anchors["w_prime_j"] = float(thresh["w_prime_j"])
    if profile.get("profile_version") is not None:
        anchors["metabolic_profile_version"] = profile.get("profile_version")
    if thresh.get("threshold_version") is not None:
        anchors["threshold_version"] = thresh.get("threshold_version")
    return anchors
