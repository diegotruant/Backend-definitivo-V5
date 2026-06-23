from __future__ import annotations

from typing import Any, Dict, List

from api.engine_schemas import AcwrRequest, MonotonyStrainRequest
from engines.adaptive_load.recommendation import generate_recommendation
from engines.adaptive_load.trend import calculate_load_trend
from engines.performance.training_variability_engine import calculate_acwr, calculate_monotony_strain


class LoadExtendedService:
    def acwr(self, req: AcwrRequest) -> Dict[str, Any]:
        return calculate_acwr(req.acute_load, req.chronic_load)

    def monotony_strain(self, req: MonotonyStrainRequest) -> Dict[str, Any]:
        return calculate_monotony_strain(req.daily_tss)

    def adaptive_trend(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        return calculate_load_trend(history)

    def adaptive_recommendation(self, report: Dict[str, Any]) -> Dict[str, Any]:
        return generate_recommendation(report)
