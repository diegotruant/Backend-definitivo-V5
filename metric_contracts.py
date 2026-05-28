"""
Unified metric confidence and API contract helpers.

The backend historically returns plain dictionaries from each engine. This
module adds a small, backwards-compatible contract layer that every engine can
attach without changing existing fields.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tiers import Tier, tier_for


CONTRACT_SCHEMA_VERSION = "metric_contract.v1"


class ConfidenceLevel(Enum):
    """Common confidence levels for all metric families."""

    NONE = "none"
    VERY_LOW = "very_low"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


def normalize_confidence(value: Any) -> Optional[float]:
    """
    Normalize common confidence representations to 0.0..1.0.

    Accepts:
    - numeric 0..1
    - numeric 0..100
    - strings such as HIGH, MEDIUM/MODERATE, LOW, NONE
    """
    if value is None:
        return None

    if isinstance(value, str):
        mapped = {
            "NONE": 0.0,
            "VERY_LOW": 0.2,
            "LOW": 0.4,
            "MEDIUM": 0.7,
            "MODERATE": 0.7,
            "HIGH": 0.9,
            "VERY_HIGH": 0.97,
        }.get(value.strip().upper())
        return mapped

    try:
        score = float(value)
    except (TypeError, ValueError):
        return None

    if score > 1.0:
        score = score / 100.0
    return max(0.0, min(1.0, score))


def confidence_level(score: Optional[float]) -> ConfidenceLevel:
    """Map a normalized confidence score to a common categorical level."""
    if score is None:
        return ConfidenceLevel.NONE
    if score >= 0.95:
        return ConfidenceLevel.VERY_HIGH
    if score >= 0.85:
        return ConfidenceLevel.HIGH
    if score >= 0.70:
        return ConfidenceLevel.MODERATE
    if score >= 0.50:
        return ConfidenceLevel.LOW
    return ConfidenceLevel.VERY_LOW


@dataclass(frozen=True)
class MetricUncertainty:
    """Machine-readable uncertainty/confidence descriptor for one metric."""

    confidence_score: Optional[float] = None
    confidence_level: ConfidenceLevel = ConfidenceLevel.NONE
    method: Optional[str] = None
    tier: Optional[str] = None
    interval_95: Optional[Tuple[float, float]] = None
    interval_80: Optional[Tuple[float, float]] = None
    std: Optional[float] = None
    sample_size: Optional[int] = None
    factors: Sequence[str] = field(default_factory=tuple)
    limitations: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confidence_score": (
                round(self.confidence_score, 4)
                if self.confidence_score is not None else None
            ),
            "confidence_level": self.confidence_level.value,
            "method": self.method,
            "tier": self.tier,
            "interval_95": (
                [round(self.interval_95[0], 4), round(self.interval_95[1], 4)]
                if self.interval_95 is not None else None
            ),
            "interval_80": (
                [round(self.interval_80[0], 4), round(self.interval_80[1], 4)]
                if self.interval_80 is not None else None
            ),
            "std": round(self.std, 4) if self.std is not None else None,
            "sample_size": self.sample_size,
            "factors": list(self.factors),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class MetricEnvelope:
    """Uniform envelope for a single metric value."""

    name: str
    value: Any
    unit: Optional[str] = None
    status: str = "success"
    uncertainty: Optional[MetricUncertainty] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "status": self.status,
            "uncertainty": (
                self.uncertainty.to_dict() if self.uncertainty is not None else None
            ),
            "metadata": dict(self.metadata),
        }


def build_uncertainty(
    *,
    module_name: str,
    method: Optional[str] = None,
    confidence: Any = None,
    interval_95: Optional[Tuple[float, float]] = None,
    interval_80: Optional[Tuple[float, float]] = None,
    std: Optional[float] = None,
    sample_size: Optional[int] = None,
    factors: Optional[Sequence[str]] = None,
    limitations: Optional[Sequence[str]] = None,
) -> MetricUncertainty:
    """Build a common uncertainty descriptor for any engine output."""
    score = normalize_confidence(confidence)
    tier = tier_for(module_name)
    return MetricUncertainty(
        confidence_score=score,
        confidence_level=confidence_level(score),
        method=method,
        tier=tier.value,
        interval_95=interval_95,
        interval_80=interval_80,
        std=std,
        sample_size=sample_size,
        factors=tuple(factors or ()),
        limitations=tuple(limitations or ()),
    )


def build_api_contract(
    *,
    module_name: str,
    status: str = "success",
    method: Optional[str] = None,
    confidence: Any = None,
    schema_version: str = CONTRACT_SCHEMA_VERSION,
    limitations: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Build the common top-level API contract attached to engine payloads.
    """
    tier = tier_for(module_name)
    uncertainty = build_uncertainty(
        module_name=module_name,
        method=method,
        confidence=confidence,
        limitations=limitations,
    )
    return {
        "schema_version": schema_version,
        "status": status,
        "module": module_name,
        "method": method,
        "tier": tier.value,
        "tier_explanation": tier.explanation,
        "confidence": uncertainty.to_dict(),
    }


def annotate_payload(
    payload: Dict[str, Any],
    *,
    module_name: str,
    method: Optional[str] = None,
    confidence: Any = None,
    confidence_field: Optional[str] = None,
    limitations: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Add `api_contract` and `uncertainty` to an existing dict in-place.

    Existing fields are preserved. This is the preferred migration path for
    existing APIs because clients can adopt the common contract gradually.
    """
    status = str(payload.get("status", "success"))
    if confidence is None and confidence_field:
        confidence = payload.get(confidence_field)

    contract = build_api_contract(
        module_name=module_name,
        status=status,
        method=method,
        confidence=confidence,
        limitations=limitations,
    )

    payload["api_contract"] = contract
    payload["uncertainty"] = contract["confidence"]

    tier = tier_for(module_name)
    payload.setdefault("tier", tier.value)
    payload.setdefault("tier_explanation", tier.explanation)
    return payload


def metric_envelope(
    name: str,
    value: Any,
    *,
    unit: Optional[str] = None,
    module_name: str,
    method: Optional[str] = None,
    confidence: Any = None,
    status: str = "success",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a uniform envelope for a single metric value."""
    uncertainty = build_uncertainty(
        module_name=module_name,
        method=method,
        confidence=confidence,
    )
    return MetricEnvelope(
        name=name,
        value=value,
        unit=unit,
        status=status,
        uncertainty=uncertainty,
        metadata=metadata or {},
    ).to_dict()


def summarize_section_contracts(sections: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a compact status map for an orchestrator's named sections.
    """
    summary: Dict[str, Any] = {}
    for name, section in sections.items():
        if isinstance(section, dict):
            contract = section.get("api_contract", {})
            summary[name] = {
                "status": section.get("status")
                or ("success" if section.get("available", True) else "unavailable"),
                "available": section.get("available", section.get("status") == "success"),
                "tier": contract.get("tier", section.get("tier")),
                "confidence_level": (
                    contract.get("confidence", {}).get("confidence_level")
                    if contract else section.get("confidence")
                ),
            }
        else:
            summary[name] = {
                "status": "unknown",
                "available": False,
                "tier": None,
                "confidence_level": None,
            }
    return summary
