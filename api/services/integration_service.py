from __future__ import annotations

from typing import Any, Dict

from api.engine_schemas import (
    IntegrationDeduplicateRequest,
    IntegrationHealthDailyEnergyRequest,
    IntegrationNormalizeRequest,
)
from engines.integrations.activity_normalizer import deduplicate_activities, normalize_external_activity
from engines.nutrition.daily_energy_engine import build_daily_energy_analysis


class IntegrationService:
    def normalize_activity(self, req: IntegrationNormalizeRequest) -> Dict[str, Any]:
        return normalize_external_activity(req.activity)

    def deduplicate(self, req: IntegrationDeduplicateRequest) -> Dict[str, Any]:
        return deduplicate_activities(req.activities)

    def daily_energy(self, req: IntegrationHealthDailyEnergyRequest) -> Dict[str, Any]:
        return build_daily_energy_analysis(
            health_daily=req.health_daily,
            athlete=req.athlete,
            load_state=req.load_state,
            training_calories_kcal=req.training_calories_kcal,
        )
