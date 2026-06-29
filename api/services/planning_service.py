from __future__ import annotations

from typing import Any, Dict

from engines.planning.plan_adapter import adapt_week
from engines.planning.season_planner import check_load_risk, create_season_plan


class PlanningService:
    def create_season_plan(self, req) -> Dict[str, Any]:
        return create_season_plan(
            start_date=req.start_date,
            target_date=req.target_date,
            weekly_hours=req.weekly_hours,
            goal=req.goal,
            athlete_profile=req.athlete_profile,
        )

    def adapt_week(self, req) -> Dict[str, Any]:
        return adapt_week(req.week_plan, readiness=req.readiness, compliance=req.compliance)

    def check_load_risk(self, req) -> Dict[str, Any]:
        return check_load_risk(req.plan, chronic_load=req.chronic_load)
