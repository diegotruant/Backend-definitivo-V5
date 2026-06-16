"""Model safety metadata helpers for physiological engine outputs."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def bounded_confidence(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def finalize_model_metadata(
    *,
    assumptions: Optional[Iterable[str]] = None,
    missing_inputs: Optional[Iterable[str]] = None,
    quality_flags: Optional[Iterable[str]] = None,
    confidence: float = 0.7,
) -> Dict[str, Any]:
    assumption_list = sorted({str(a) for a in (assumptions or []) if a})
    missing_list = sorted({str(m) for m in (missing_inputs or []) if m})
    flag_list = sorted({str(f) for f in (quality_flags or []) if f})

    confidence_value = bounded_confidence(confidence)
    if missing_list:
        confidence_value = min(confidence_value, 0.55)
    if flag_list:
        confidence_value = min(confidence_value, 0.65)

    return {
        "assumptions": assumption_list,
        "missing_inputs": missing_list,
        "quality_flags": flag_list,
        "confidence_score": round(confidence_value, 3),
    }
