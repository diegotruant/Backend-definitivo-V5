from __future__ import annotations

from typing import Any, Dict, List, Optional

from api.schemas import PowerSourceNormalizationRequest
from engines.io.power_source_normalizer import analyze_power_source_offsets
from engines.performance.neuromuscular_profile import analyze_neuromuscular_profile


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
        return analyze_power_source_offsets(
            req.activities,
            baseline_source_id=req.baseline_source_id,
            warning_threshold_pct=req.warning_threshold_pct,
            severe_threshold_pct=req.severe_threshold_pct,
        )
