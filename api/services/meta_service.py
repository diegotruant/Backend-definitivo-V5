from __future__ import annotations

from typing import Any, Dict

from api.engine_schemas import ChartConfigRequest
from api.errors import ServiceError
from engines.io.chart_registry import ChartBuildError, build_chart_config, list_chart_types


class MetaService:
    def engine_tiers(self) -> Dict[str, Any]:
        from engines.core.tiers import ENGINE_TIERS, Tier

        return {
            "tiers": {
                tier.value: {
                    "name": tier.name,
                    "short": tier.short,
                    "explanation": tier.explanation,
                }
                for tier in Tier
            },
            "engines": {name: tier.value for name, tier in ENGINE_TIERS.items()},
        }

    def chart_types(self) -> Dict[str, Any]:
        return list_chart_types()

    def chart_config(self, req: ChartConfigRequest) -> Dict[str, Any]:
        try:
            return build_chart_config(req.chart_type, dict(req.payload))
        except ChartBuildError as exc:
            raise ServiceError(
                message=exc.message,
                status_code=exc.status_code,
                code=exc.code,
                details=exc.details,
            ) from exc
