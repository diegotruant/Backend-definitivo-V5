from __future__ import annotations

from typing import Any, Dict

from api.engine_schemas import ChartConfigRequest
from api.errors import ServiceError


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
        required_keys = {
            "mmp": ("mmp",),
            "power_duration": ("mmp",),
            "zones": ("zones_data",),
            "hrv": ("time_seconds", "dfa_alpha1"),
            "training_load": ("dates", "ctl_values", "atl_values", "tsb_values"),
            "detraining": ("parameters", "baseline_values", "current_values", "units"),
        }
        missing = [key for key in required_keys.get(req.chart_type, ()) if key not in payload]
        if missing:
            raise ServiceError(
                message=f"chart payload missing required keys: {', '.join(missing)}",
                status_code=422,
                code="MISSING_CHART_PAYLOAD",
                details={"chart_type": req.chart_type, "missing": missing},
            )

        if req.chart_type in {"mmp", "power_duration"}:
            payload["mmp"] = {int(k): float(v) for k, v in payload["mmp"].items()}

        if req.chart_type == "training_load" and "dates" in payload:
            from datetime import date

            payload["dates"] = [
                date.fromisoformat(str(item).split("T")[0]) if not isinstance(item, date) else item
                for item in payload["dates"]
            ]

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
