from __future__ import annotations

from typing import Any, Dict

from api.engine_schemas import (
    ExplainabilityAcwrNarrativeRequest,
    ExplainabilityDurabilityConfidenceRequest,
    ExplainabilityMetricNarrativeRequest,
    ExplainabilityVo2ConfidenceRequest,
    ExplainabilityWorkoutSummaryRequest,
)
from engines.recovery.explainability_engine import (
    ConfidenceLevel,
    ConfidenceScore,
    calculate_durability_confidence,
    calculate_vo2max_confidence,
    generate_acwr_narrative,
    generate_durability_narrative,
    generate_metric_narrative,
    generate_workout_summary_narrative,
)


def _confidence_from_dict(
    raw: Dict[str, Any],
    *,
    metric_name: str,
    value: float,
) -> ConfidenceScore:
    level = raw.get("confidence_level", "MODERATE")
    if isinstance(level, str):
        level = ConfidenceLevel[level] if level in ConfidenceLevel.__members__ else ConfidenceLevel.MODERATE
    return ConfidenceScore(
        metric_name=metric_name,
        value=value,
        confidence_level=level,
        confidence_pct=float(raw.get("confidence_pct", 50)),
        factors=list(raw.get("factors") or []),
        limitations=list(raw.get("limitations") or []),
    )


class ExplainabilityService:
    def vo2max_confidence(self, req: ExplainabilityVo2ConfidenceRequest) -> Dict[str, Any]:
        mmp = {int(k): float(v) for k, v in req.mmp_curve.items()}
        score = calculate_vo2max_confidence(mmp, req.efforts_count, req.data_quality_score)
        return {
            "confidence_level": score.confidence_level.name,
            "confidence_pct": score.confidence_pct,
            "factors": score.factors,
            "limitations": score.limitations,
        }

    def durability_confidence(self, req: ExplainabilityDurabilityConfidenceRequest) -> Dict[str, Any]:
        score = calculate_durability_confidence(req.duration_hours, req.power_data_completeness)
        return {
            "confidence_level": score.confidence_level.name,
            "confidence_pct": score.confidence_pct,
            "factors": score.factors,
            "limitations": score.limitations,
        }

    def metric_narrative(self, req: ExplainabilityMetricNarrativeRequest) -> Dict[str, Any]:
        text = generate_metric_narrative(
            req.metric_name,
            req.value,
            _confidence_from_dict(
                req.confidence,
                metric_name=req.metric_name,
                value=req.value,
            ),
            req.context,
        )
        return {"narrative": text}

    def durability_narrative(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        confidence_raw = payload.get("confidence") or {}
        confidence = _confidence_from_dict(
            confidence_raw,
            metric_name="durability",
            value=float(payload.get("durability_index", 0)),
        )
        return {
            "narrative": generate_durability_narrative(
                float(payload.get("durability_index", 0)),
                str(payload.get("classification") or "GOOD"),
                confidence,
                payload.get("prescription") or {},
            )
        }

    def acwr_narrative(self, req: ExplainabilityAcwrNarrativeRequest) -> Dict[str, Any]:
        return {
            "narrative": generate_acwr_narrative(
                req.acwr_value,
                req.risk_level,
                req.ctl,
                req.atl,
                req.tsb,
            )
        }

    def workout_summary_narrative(self, req: ExplainabilityWorkoutSummaryRequest) -> Dict[str, Any]:
        return {"narrative": generate_workout_summary_narrative(req.summary)}
