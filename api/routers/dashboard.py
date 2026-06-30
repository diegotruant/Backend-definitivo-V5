"""Dashboard aggregation endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_dashboard_service
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class AthleteSnapshotRequest(BaseModel):
    twin_state: Optional[Dict[str, Any]] = None
    load_state: Optional[Dict[str, Any]] = None
    hrv_status: Optional[Dict[str, Any]] = None
    sleep_status: Optional[Dict[str, Any]] = None
    subjective: Optional[Dict[str, Any]] = None
    daily_tss: Optional[List[float]] = None
    last_ride_summary: Optional[Dict[str, Any]] = None
    include_chart_hints: bool = True


@router.post(
    "/athlete-snapshot",
    summary="Athlete dashboard snapshot",
    description="Aggregates readiness, load risk, ACWR, twin highlights and chart hints for coach home.",
    operation_id="dashboardAthleteSnapshot",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT, 400: ERRORS[400]},
)
def athlete_snapshot(
    req: AthleteSnapshotRequest,
    service: DashboardService = Depends(get_dashboard_service),
):
    return json_response(service.athlete_snapshot(**req.model_dump()))
