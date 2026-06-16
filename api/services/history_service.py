from __future__ import annotations

from typing import Any, Dict

from engines.history.athlete_history import build_history_summary, compute_personal_records
from engines.history.load_trends import compute_load_trends
from engines.history.power_curve_history import build_power_curve_history


class HistoryService:
    def summary(self, req) -> Dict[str, Any]:
        return build_history_summary(req.activities, as_of=req.as_of, weight_kg=req.weight_kg)

    def power_curve(self, req) -> Dict[str, Any]:
        return build_power_curve_history(req.activities, as_of=req.as_of, weight_kg=req.weight_kg)

    def records(self, req) -> Dict[str, Any]:
        return compute_personal_records(req.activities, weight_kg=req.weight_kg)

    def load(self, req) -> Dict[str, Any]:
        return compute_load_trends(req.activities, as_of=req.as_of)
