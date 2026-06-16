from __future__ import annotations

from typing import Any, Dict

from engines.readness.readiness_engine import compute_load_risk, compute_readiness_today, update_load_state


class ReadinessService:
    def today(self, req) -> Dict[str, Any]:
        return compute_readiness_today(
            load_state=req.load_state,
            hrv_status=req.hrv_status,
            sleep_status=req.sleep_status,
            subjective=req.subjective,
            recent_warnings=req.recent_warnings,
        )

    def update_load_state(self, req) -> Dict[str, Any]:
        return update_load_state(req.previous_state, req.session_load)

    def load_risk(self, req) -> Dict[str, Any]:
        return compute_load_risk(req.load_state, planned_load=req.planned_load)
