"""Coach-facing physiological resilience envelope (naming + contract only)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from engines.core.metric_contracts import annotate_payload


def _confidence_label(score: Optional[float]) -> str:
    if score is None:
        return "low"
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def build_physiological_resilience(
    *,
    mader_durability: Optional[Dict[str, Any]] = None,
    durability_index: Optional[Dict[str, Any]] = None,
    prior: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Map existing durability outputs into a top-level resilience contract.

    Does not change underlying engines — naming and aggregation only.
    """
    mader = mader_durability or {}
    di_block = durability_index or {}
    prior_block = prior or {}

    dcp_pct = mader.get("durability_loss_pct")
    if dcp_pct is not None:
        try:
            dcp_pct = round(float(dcp_pct), 1)
        except (TypeError, ValueError):
            dcp_pct = None

    di_raw = di_block.get("durability_index")
    durability_index_norm = None
    late_power_retention = None
    if di_raw is not None:
        try:
            durability_index_norm = round(float(di_raw) / 100.0, 3)
            late_power_retention = durability_index_norm
        except (TypeError, ValueError):
            pass

    trend = "stable"
    prev_dcp = prior_block.get("dcp_pct")
    if dcp_pct is not None and prev_dcp is not None:
        try:
            delta = float(dcp_pct) - float(prev_dcp)
            if delta <= -1.0:
                trend = "improving"
            elif delta >= 1.0:
                trend = "declining"
        except (TypeError, ValueError):
            pass

    if mader.get("status") != "success" and durability_index_norm is None:
        return annotate_payload(
            {"status": "unavailable", "reason": "no_durability_signals"},
            module_name="physiological_resilience",
            method="aggregate_durability_outputs",
            confidence=0.0,
        )

    confidence = _confidence_label(
        float(mader.get("confidence_score") or 0.65)
        if mader.get("status") == "success"
        else 0.35
    )

    payload = {
        "status": "success",
        "dcp_pct": dcp_pct,
        "durability_index": durability_index_norm,
        "late_power_retention": late_power_retention,
        "trend": trend,
        "confidence": confidence,
        "source": {
            "mader_durability": mader.get("status"),
            "elapsed_durability_index": di_block.get("status"),
        },
        "label": "physiological_resilience",
        "interpretation": (
            "Fatigue resistance / residual capacity during prolonged work. "
            "Model-based (Mader DCP) when available; empirical retention when long rides exist."
        ),
    }
    return annotate_payload(
        payload,
        module_name="physiological_resilience",
        method="aggregate_durability_outputs",
        confidence=0.65 if mader.get("status") == "success" else 0.4,
    )
