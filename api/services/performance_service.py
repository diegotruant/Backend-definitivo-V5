from __future__ import annotations

from typing import Any, Dict, List, Optional

from api.schemas import PowerSourceNormalizationRequest
from engines.io.power_source_normalizer import analyze_power_source_offsets
from engines.performance.neuromuscular_profile import analyze_neuromuscular_profile
from engines.performance.ability_profile import build_ability_profile
from engines.performance.breakthrough_detector import detect_breakthroughs


class PerformanceService:
    def neuromuscular_profile(
        self,
        stream: Any,
        *,
        weight_kg: float,
        sprint_threshold_w: Optional[float],
    ) -> Dict[str, Any]:
        return analyze_neuromuscular_profile(
            stream,
            weight_kg=weight_kg,
            sprint_threshold_w=sprint_threshold_w,
        )

    def normalize_power_sources(self, req: PowerSourceNormalizationRequest) -> Dict[str, Any]:
        activities: List[Dict[str, Any]] = [item.to_engine_dict() for item in req.activities]
        return analyze_power_source_offsets(
            activities,
            baseline_source_id=req.baseline_source_id,
            warning_threshold_pct=req.warning_threshold_pct,
            severe_threshold_pct=req.severe_threshold_pct,
        )

    def ability_profile(self, req) -> Dict[str, Any]:
        return build_ability_profile(
            req.athlete_profile,
            weight_kg=req.weight_kg,
            durability=req.durability,
            compliance_history=req.compliance_history,
        )

    def breakthroughs(self, req) -> Dict[str, Any]:
        return detect_breakthroughs(
            req.baseline_curve,
            req.activity_curve,
            min_gain_pct=req.min_gain_pct,
        )
