"""Athlete body-mass resolution for official vs indicative metrics."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def resolve_weight_kg(
    value: Any,
    *,
    default: Optional[float] = None,
    min_kg: float = 35.0,
    max_kg: float = 160.0,
) -> Tuple[Optional[float], Dict[str, Any]]:
    """Resolve athlete weight with explicit provenance for model safety.

    Returns (weight_kg_or_none, metadata) where metadata includes:
      - provided: whether a caller-supplied value was parsed
      - source: explicit | default | missing | invalid
      - wkg_official: False when weight is missing/default/invalid
    """
    meta: Dict[str, Any] = {
        "provided": False,
        "source": "missing",
        "wkg_official": False,
        "assumptions": [],
    }
    if value is None or value == "":
        if default is not None and default > 0:
            meta.update(
                {
                    "source": "default",
                    "wkg_official": False,
                    "assumptions": ["weight_kg_defaulted_for_non_official_metrics"],
                }
            )
            return float(default), meta
        meta["assumptions"] = ["weight_kg_missing_wkg_not_computed"]
        return None, meta

    try:
        weight = float(value)
    except (TypeError, ValueError):
        meta.update({"source": "invalid", "assumptions": ["weight_kg_invalid_wkg_not_computed"]})
        return None, meta

    if weight <= 0:
        meta.update({"source": "invalid", "assumptions": ["weight_kg_non_positive_wkg_not_computed"]})
        return None, meta

    meta["provided"] = True
    meta["source"] = "explicit"
    meta["wkg_official"] = min_kg <= weight <= max_kg
    if not meta["wkg_official"]:
        meta["assumptions"] = ["weight_kg_out_of_plausible_range_wkg_use_caution"]
    return weight, meta


def require_weight_kg(value: Any, *, field_name: str = "weight_kg") -> float:
    """Strict resolver for lab-grade / in-person test flows."""
    weight, meta = resolve_weight_kg(value, default=None)
    if weight is None:
        reason = meta.get("source", "missing")
        raise ValueError(f"{field_name} is required ({reason})")
    return weight
