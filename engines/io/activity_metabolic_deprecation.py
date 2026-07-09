"""Mark per-activity metabolic estimates as deprecated for athlete-profile use."""

from __future__ import annotations

from typing import Any, Dict

DEPRECATED_STATUS = "deprecated_activity_level_estimate"
DEPRECATED_CONFIDENCE = "LOW"

_METABOLIC_VALUE_KEYS = frozenset(
    {
        "vo2max",
        "vo2max_ml_kg_min",
        "vlamax",
        "vlamax_mmol_l_s",
        "mlss",
        "mlss_power_w",
        "mlss_power_watts",
        "fatmax",
        "fatmax_power_w",
        "map",
        "map_power_w",
        "phenotype_type",
        "phenotype_description",
        "rider_phenotype",
    }
)


def _deprecation_meta() -> Dict[str, Any]:
    return {
        "metabolic_snapshot_status": DEPRECATED_STATUS,
        "metabolic_snapshot_confidence": DEPRECATED_CONFIDENCE,
        "do_not_use_as_athlete_profile": True,
    }


def mark_metabolic_section_deprecated(section: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Attach deprecation metadata to a metabolic section without removing values."""
    if not isinstance(section, dict):
        return section
    tagged = dict(section)
    tagged.update(_deprecation_meta())
    return tagged


def apply_activity_metabolic_deprecation(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure per-activity metabolic outputs are not promoted as stable athlete profile.

    Internal session estimates remain available for diagnostics but are tagged
    ``deprecated_activity_level_estimate``.
    """
    if not isinstance(bundle, dict):
        return bundle

    meta = _deprecation_meta()
    bundle = dict(bundle)
    bundle["metabolic_profile"] = meta

    summary = bundle.get("workout_summary")
    if isinstance(summary, dict):
        summary = dict(summary)
        sections = dict(summary.get("sections") or {})
        for key in ("metabolic_snapshot", "fatmax"):
            if key in sections:
                sections[key] = mark_metabolic_section_deprecated(sections[key])
        zones = sections.get("zones")
        if isinstance(zones, dict) and zones.get("metabolic_power"):
            zones = dict(zones)
            zones["metabolic_power"] = mark_metabolic_section_deprecated(zones["metabolic_power"])
            sections["zones"] = zones
        classification = sections.get("classification")
        if isinstance(classification, dict) and classification.get("status") == "success":
            classification = dict(classification)
            classification.update(meta)
            classification["athlete_identity_status"] = "deprecated_session_phenotype"
            sections["classification"] = classification
        summary["sections"] = sections
        headline = dict(summary.get("headline") or {})
        for key in list(headline.keys()):
            if key in _METABOLIC_VALUE_KEYS or key.startswith(("vo2", "vlamax", "mlss", "fatmax", "map_", "rider_phenotype")):
                headline[f"{key}_deprecated"] = True
        if headline.get("rider_phenotype"):
            headline["rider_phenotype_status"] = "deprecated_session_phenotype"
        headline.update(meta)
        summary["headline"] = headline
        bundle["workout_summary"] = summary

    physiology = bundle.get("physiology_outputs")
    if isinstance(physiology, dict):
        physiology = dict(physiology)
        for key in ("metabolic_snapshot", "fatmax"):
            if key in physiology:
                physiology[key] = mark_metabolic_section_deprecated(physiology[key])
        physiology.update(meta)
        bundle["physiology_outputs"] = physiology

    for key in list(bundle.keys()):
        if key in _METABOLIC_VALUE_KEYS:
            wrapped = bundle.pop(key)
            bundle[key] = {"value": wrapped, **meta}

    bundle.update(meta)
    return bundle
