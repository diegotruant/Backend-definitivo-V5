"""Conservative science-facing contracts, warnings, and naming helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

import numpy as np

from engines.core.tiers import tier_for

TauModel = Literal["skiba_default", "bartram_elite", "pugh_level_based", "individualized"]

_CADENCE_COASTING_MIN_RPM = 40.0

_TAU_SECONDS: dict[TauModel, float] = {
    "skiba_default": 546.0,
    "bartram_elite": 417.0,
    "pugh_level_based": 587.0,
}

_VLAMAX_LIMITATION = (
    "VLamax estimate may be cadence/protocol dependent. Sprint cadence below "
    "130 rpm can underestimate true maximal lactate accumulation potential."
)

_CADENCE_MODELING_WARNING = (
    "Metabolic snapshot is cadence-anchored; comparisons across very different "
    "cadences may be biased."
)


_VLAMAX_DISCLAIMER = (
    "VLamax is an estimated maximal lactate accumulation rate from the Mader model "
    "(vLamax_muscle), not a direct blood or muscle biopsy measurement."
)


def vlamax_contract_fields() -> Dict[str, Any]:
    """Coach-facing VLamax semantics — model estimate, not direct glycolytic rate."""
    tier = tier_for("metabolic_profiler")
    return {
        "vlamax_disclaimer": _VLAMAX_DISCLAIMER,
        "vlamax_label": "estimated_lactate_accumulation_rate",
        "vlamax_not_direct_glycolytic_rate": True,
        "vlamax_unit": "mmol/L/s",
        "vlamax_interpretation": (
            "Estimated maximal lactate accumulation rate from the Mader model fit "
            "(vLamax_muscle); not a direct blood measurement. Compare to capillary "
            "vLaPeak (Wackerhage et al. 2025) only as an external validation benchmark."
        ),
        "vlamax_tier": tier.value,
        "vlamax_tier_explanation": tier.explanation,
    }


_FATMAX_MODEL_LIMITATION = (
    "FATmax power, MFO (g/min) and substrate curves from field/MMP snapshots are model "
    "estimates unless measurement_tier is LAB_MEASURED from stepped VO2/VCO2 data."
)

_FATMAX_LAB_LIMITATION = (
    "Lab FATmax and MFO are computed from non-protein indirect-calorimetry stoichiometry; "
    "protein oxidation is assumed negligible and protocol quality affects validity."
)


def fatmax_contract_fields(*, measurement_tier: str) -> Dict[str, Any]:
    """Coach-facing FATmax semantics — lab measurement vs model estimate."""
    is_lab = measurement_tier == "LAB_MEASURED"
    return {
        "fatmax_measurement_tier": measurement_tier,
        "mfo_is_measured": is_lab,
        "mfo_is_model_proxy": not is_lab and measurement_tier == "MODEL_ESTIMATE",
        "fatmax_interpretation": (
            "FATmax power and MFO from stepped VO2/VCO2 indirect calorimetry."
            if is_lab
            else (
                "FATmax power and MFO are model estimates from the metabolic snapshot "
                "(Mader/MMP context). They are not indirect-calorimetry measurements."
            )
        ),
        "crossover_semantics_note": (
            "carbohydrate_crossover.method distinguishes g/min lab crossover from model proxy crossover."
        ),
    }


def fatmax_limitations(*, measurement_tier: str) -> List[str]:
    if measurement_tier == "LAB_MEASURED":
        return [_FATMAX_LAB_LIMITATION]
    if measurement_tier == "MODEL_ESTIMATE":
        return [_FATMAX_MODEL_LIMITATION]
    return ["Insufficient data to produce a FATmax report."]


def vlamax_limitations(*, effective_cadence_rpm: Optional[float] = None) -> List[str]:
    limits = [_VLAMAX_DISCLAIMER, _VLAMAX_LIMITATION]
    if effective_cadence_rpm is not None and effective_cadence_rpm < 130:
        limits.append(
            f"Sprint/profile cadence ({effective_cadence_rpm:.0f} rpm) is below typical "
            "maximal-test protocols; true lactate accumulation potential may be higher."
        )
    return limits


def derive_effective_cadence_rpm(
    stream: Any,
    *,
    min_rpm: float = _CADENCE_COASTING_MIN_RPM,
) -> Optional[float]:
    """Median cadence above ``min_rpm`` to exclude coasting and stale zeros."""
    raw = getattr(stream, "cadence", None)
    if raw is None:
        return None
    n = int(getattr(stream, "n_samples", 0) or len(raw))
    values: List[float] = []
    for i in range(n):
        c = raw[i]
        if c is None:
            continue
        try:
            fv = float(c)
        except (TypeError, ValueError):
            continue
        if np.isfinite(fv) and fv > min_rpm:
            values.append(fv)
    if not values:
        return None
    return float(np.median(values))


def enrich_metabolic_snapshot_cadence(
    snapshot: Dict[str, Any],
    *,
    effective_cadence_rpm: Optional[float],
    cadence_anchor_status: str = "measured",
) -> Dict[str, Any]:
    """Attach cadence anchor metadata and VLamax limitations when missing."""
    if snapshot.get("status") != "success" or effective_cadence_rpm is None:
        return snapshot
    existing = (snapshot.get("cadence_anchor") or {}).get("effective_cadence_rpm")
    if existing is not None and float(existing) > 0:
        return snapshot
    snapshot["cadence_anchor"] = cadence_anchor_metadata(
        effective_cadence_rpm=effective_cadence_rpm,
        cadence_anchor_status=cadence_anchor_status,
    )
    extra_limits = vlamax_limitations(effective_cadence_rpm=effective_cadence_rpm)
    limits = list(snapshot.get("limitations") or [])
    unc = snapshot.get("uncertainty") or {}
    if not limits and unc.get("limitations"):
        limits = list(unc.get("limitations") or [])
    merged = list(dict.fromkeys(limits + extra_limits))
    snapshot["limitations"] = merged
    if unc:
        unc["limitations"] = merged
        snapshot["uncertainty"] = unc
    return snapshot


def cadence_anchor_metadata(
    *,
    effective_cadence_rpm: Optional[float],
    cadence_anchor_status: str = "unknown",
) -> Dict[str, Any]:
    """Step-1 cadence metadata for metabolic snapshots (no metabolic correction)."""
    measured = effective_cadence_rpm is not None and effective_cadence_rpm > 0
    payload: Dict[str, Any] = {
        "effective_cadence_rpm": round(float(effective_cadence_rpm), 1) if measured else None,
        "cadence_anchor_status": "measured" if measured else cadence_anchor_status,
    }
    if measured:
        payload["cadence_modeling_warning"] = _CADENCE_MODELING_WARNING
        payload["cadence_anchor_confidence"] = "medium"
    return payload


def cp_anchor_warnings(mmp: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Warn when CP fit lacks a ≥20 min anchor in the MMP curve."""
    has_long_anchor = any(int(m.get("duration_s", 0) or 0) >= 1200 for m in mmp)
    if has_long_anchor:
        return []
    return [
        {
            "code": "CP_NO_20MIN_ANCHOR",
            "warning": "CP may be overestimated because no ≥1200s anchor is available.",
            "severity": "medium",
            "recommendation": "Add a 20 min / long steady anchor for better CP validation.",
        }
    ]


def resolve_w_prime_tau(
    tau_model: TauModel = "skiba_default",
    *,
    athlete_profile: Optional[Dict[str, Any]] = None,
    athlete_level: Optional[str] = None,
) -> tuple[float, TauModel]:
    """Resolve W′ reconstitution τ (seconds) from model enum and athlete context."""
    level = (athlete_level or "").strip().lower()
    profile = athlete_profile or {}

    if tau_model == "individualized":
        custom = profile.get("w_prime_tau_s")
        if custom is not None:
            try:
                return float(custom), "individualized"
            except (TypeError, ValueError):
                pass
        tau_model = "skiba_default"

    if tau_model == "skiba_default" and level in {"elite", "pro"}:
        return _TAU_SECONDS["bartram_elite"], "bartram_elite"

    if tau_model == "pugh_level_based":
        if level in {"recreational", "novice", "beginner"}:
            return 620.0, "pugh_level_based"
        if level in {"trained", "competitive"}:
            return 520.0, "pugh_level_based"
        return _TAU_SECONDS["pugh_level_based"], "pugh_level_based"

    return _TAU_SECONDS.get(tau_model, _TAU_SECONDS["skiba_default"]), tau_model
