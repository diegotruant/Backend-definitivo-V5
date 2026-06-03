"""
Confidence Tiers
================

Single source of truth for the methodological tier of each module output.

Tiers
-----
A — REFERENCE: deterministic from input. Standard formulas (NP, IF, TSS, MMP,
    rolling averages, zone time-in-zone). No model assumptions beyond the
    formula itself. Equivalent to external analysis platforms/open-source analysis platform outputs.

B — MODEL: physiological model with documented assumptions. The result is a
    prediction of a quantity that cannot be directly measured from the stream
    (VO2max from MMP via Mader, DFA-α₁ thresholds, W' balance via Skiba).
    Backed by peer-reviewed literature, but values depend on model fidelity.

C — HEURISTIC: rule-of-thumb thresholds, not validated against gold standards.
    Examples: durability cutoffs at 97/93/88%, ACWR=1.5 risk threshold,
    metabolic flexibility index formulae. Useful for trending and
    classification, but the absolute thresholds are disputed.

D — EXPERIMENTAL: simplified models, single-paper claims, or our own
    heuristics not yet documented. Use only for exploration.

Usage
-----
    from engines.tiers import Tier, ENGINE_TIERS

    result["tier"] = Tier.A.value          # "REFERENCE"
    result["tier_explanation"] = Tier.A.explanation

Or via the module-name lookup:

    result["tier"] = ENGINE_TIERS["power_engine"].value
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class _TierMeta:
    name: str
    short: str
    explanation: str
    
    @property
    def value(self) -> str:
        return self.name


class Tier(Enum):
    REFERENCE = _TierMeta(
        "REFERENCE",
        "A",
        "Deterministic from input. Standard formulas with no model "
        "assumptions beyond the math itself.",
    )
    MODEL = _TierMeta(
        "MODEL",
        "B",
        "Physiological model with documented assumptions. Predicts a "
        "quantity that cannot be measured directly from the stream.",
    )
    HEURISTIC = _TierMeta(
        "HEURISTIC",
        "C",
        "Rule-of-thumb thresholds, useful for trending and classification, "
        "but absolute cutoffs are disputed or unvalidated.",
    )
    EXPERIMENTAL = _TierMeta(
        "EXPERIMENTAL",
        "D",
        "Simplified models or single-paper claims. Use for exploration only.",
    )
    
    @property
    def value(self) -> str:
        return self._value_.name
    
    @property
    def short(self) -> str:
        return self._value_.short
    
    @property
    def explanation(self) -> str:
        return self._value_.explanation


# Mapping: module-name → tier
# Used by orchestrators / dashboards to label outputs.
ENGINE_TIERS: Dict[str, Tier] = {
    "fit_parser":                    Tier.REFERENCE,
    "power_engine":                  Tier.REFERENCE,
    "zones_engine":                  Tier.REFERENCE,
    "coggan_classifier":             Tier.REFERENCE,
    "cardiac_engine":                Tier.REFERENCE,  # metrics; classification is heuristic
    "data_quality_engine":           Tier.REFERENCE,
    "efforts_analyzer":              Tier.REFERENCE,
    "workout_summary":               Tier.REFERENCE,  # aggregator inherits worst-of
    "hrv_engine":                    Tier.MODEL,
    "metabolic_profiler":            Tier.MODEL,
    "cross_validation_engine":       Tier.MODEL,
    "lactate_validation_engine":     Tier.REFERENCE,  # lactate is measured ground truth
    "test_protocols":                Tier.REFERENCE,  # in-person test calculations (direct formulas)
    "w_prime_balance_engine":        Tier.MODEL,
    "race_prediction_engine":        Tier.MODEL,
    "mmp_aggregator":                Tier.REFERENCE,
    "metabolic_profiler_phenotype":  Tier.HEURISTIC,
    "detraining_engine":             Tier.HEURISTIC,
    "durability_engine":             Tier.HEURISTIC,
    "training_variability_engine":   Tier.HEURISTIC,
    "metabolic_flexibility_engine":  Tier.HEURISTIC,
    "metabolic_current":             Tier.HEURISTIC,  # combines MODEL + HEURISTIC
    "explainability_engine":         Tier.HEURISTIC,
    "chart_builder":                 Tier.REFERENCE,  # pass-through formatting
    "metric_contracts":              Tier.REFERENCE,
}


def tier_for(module_name: str) -> Tier:
    """Return the canonical Tier for a module name, defaulting to EXPERIMENTAL."""
    return ENGINE_TIERS.get(module_name, Tier.EXPERIMENTAL)


def annotate(result: dict, module_name: str) -> dict:
    """
    Add `tier` and `tier_explanation` fields to a result dict in-place.
    Convenience for engines that want to self-annotate.
    """
    tier = tier_for(module_name)
    result["tier"] = tier.value
    result["tier_explanation"] = tier.explanation
    return result


# Module classification table (per-activity vs longitudinal)
# Useful for documentation; not enforced programmatically.
SCOPE: Dict[str, str] = {
    "per_activity": [
        "fit_parser", "power_engine", "zones_engine", "coggan_classifier",
        "cardiac_engine", "hrv_engine", "efforts_analyzer", "data_quality_engine",
        "workout_summary", "chart_builder",
    ],
    "longitudinal": [
        "metabolic_profiler", "metabolic_profiler_phenotype", "metabolic_current",
        "detraining_engine", "training_variability_engine", "durability_engine",
        "w_prime_balance_engine", "metabolic_flexibility_engine",
        "explainability_engine",
    ],
}


# =============================================================================
# Display gating (analysis-platform-style "hide instead of mislead")
# =============================================================================
#
# analysis platform's product decision: if the data is too dirty to compute reliable
# values, show "—" (em-dash) instead of the numbers. Better no information
# than misleading information.
#
# Default thresholds for the Digital Twin (tuneable by the consumer):
#   - confidence >= 0.55  → display the value
#   - confidence < 0.55   → display placeholder + reason
#
# The threshold is conservative compared to lab-grade requirements but
# realistic given that confidence_score in MODEL-tier outputs is RMSE-based
# and rarely exceeds 0.85 even on clean data.


# Default thresholds. Override per-deployment if needed.
DEFAULT_DISPLAY_THRESHOLD = 0.55
DEFAULT_PLACEHOLDER = "—"


def should_display(
    confidence: Optional[float],
    threshold: float = DEFAULT_DISPLAY_THRESHOLD,
) -> bool:
    """
    Return True if a value with this confidence should be shown to the user.
    
    A None confidence is treated as "unknown" and gated out by default —
    the consumer must opt in to showing values without confidence.
    """
    if confidence is None:
        return False
    try:
        return float(confidence) >= float(threshold)
    except (TypeError, ValueError):
        return False


def mask_low_confidence(
    payload: Dict[str, Any],
    confidence_field: str = "confidence_score",
    value_fields: Optional[List[str]] = None,
    threshold: float = DEFAULT_DISPLAY_THRESHOLD,
    placeholder: Any = DEFAULT_PLACEHOLDER,
    add_display_meta: bool = True,
) -> Dict[str, Any]:
    """
    Return a copy of `payload` where numeric values are masked with a
    placeholder if the confidence is below the threshold.
    
    Parameters
    ----------
    payload : dict
        The output of an engine (typically a metabolic snapshot).
    confidence_field : str
        Which key in payload holds the confidence score.
    value_fields : list of str, optional
        Which fields to mask. If None, defaults to the standard set of
        metabolic snapshot value fields.
    threshold : float
        Confidence below this triggers masking.
    placeholder : Any
        What to put in place of the value. Default "—".
    add_display_meta : bool
        If True, add a `_display` dict to the output explaining what was
        hidden and why.
    
    Returns
    -------
    dict — a new dict (the input is not mutated)
    
    Notes
    -----
    This is a *consumer-side* helper. The engines themselves do NOT call this
    automatically. The product layer (or UI) decides whether to gate.
    Showing the raw value is still the default for debugging and API consumers
    that want to see everything.
    """
    if value_fields is None:
        value_fields = [
            "estimated_vo2max",
            "estimated_vlamax_mmol_L_s",
            "mlss_power_watts",
            "mlss_power_wkg",
            "fatmax_power_watts",
            "map_aerobic_watts",
            "ftp_estimate_w",
            "critical_power_w",
            "lt1_w",
        ]
    
    masked = dict(payload)
    confidence = payload.get(confidence_field)
    show = should_display(confidence, threshold)
    
    hidden_fields = []
    if not show:
        for f in value_fields:
            if f in masked and masked[f] is not None:
                hidden_fields.append(f)
                masked[f] = placeholder
    
    if add_display_meta:
        masked["_display"] = {
            "shown": show,
            "threshold": threshold,
            "confidence": confidence,
            "hidden_fields": hidden_fields,
            "reason": (
                "Confidence above threshold — values shown." if show else
                f"Confidence {confidence} below threshold {threshold}. "
                "Values masked to avoid misleading display. The numbers are "
                "still available in the unmasked payload — this is a UI gate, "
                "not a data deletion."
            ),
        }
    return masked
