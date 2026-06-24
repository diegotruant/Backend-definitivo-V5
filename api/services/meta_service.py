from __future__ import annotations

from typing import Any, Dict

from api.engine_schemas import ChartConfigRequest


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

    def chart_config(self, req: ChartConfigRequest) -> Dict[str, Any]:
        from engines.io import chart_builder

        payload = dict(req.payload)
        if req.chart_type in {"mmp", "power_duration"}:
            if "mmp" in payload:
                payload["mmp"] = {int(k): float(v) for k, v in payload["mmp"].items()}
            else:
                return {
                    "status": "partial",
                    "reason": "MISSING_MMP",
                    "available": ["mmp", "zones", "hrv", "training_load", "detraining", "power_duration"],
                }

        builders = {
            "mmp": chart_builder.chart_power_duration_curve,
            "zones": chart_builder.chart_zones_distribution,
            "hrv": chart_builder.chart_hrv_timeline,
            "training_load": chart_builder.chart_training_load,
            "detraining": chart_builder.chart_detraining_decay,
            "power_duration": chart_builder.chart_power_duration_curve,
        }
        fn = builders.get(req.chart_type)
        if fn is None:
            return {"status": "error", "reason": "UNKNOWN_CHART_TYPE", "available": list(builders)}
        return {"status": "success", "config": fn(**payload)}
