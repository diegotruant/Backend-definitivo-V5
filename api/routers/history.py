from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_history_service
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.schemas import HistorySummaryRequest
from api.services.history_service import HistoryService

router = APIRouter(prefix="/history", tags=["history"], )


@router.post("/summary", summary="Athlete history summary", operation_id="historySummary", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def history_summary(req: HistorySummaryRequest, service: HistoryService = Depends(get_history_service)):
    return json_response(service.summary(req))


@router.post("/power-curve", summary="Power curve by period", operation_id="historyPowerCurve", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def history_power_curve(req: HistorySummaryRequest, service: HistoryService = Depends(get_history_service)):
    return json_response(service.power_curve(req))


@router.post("/records", summary="Personal records from history", operation_id="historyRecords", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def history_records(req: HistorySummaryRequest, service: HistoryService = Depends(get_history_service)):
    return json_response(service.records(req))


@router.post("/load", summary="Historical load trends", operation_id="historyLoad", response_model=EnginePayload, responses={200: JSON_OBJECT, 400: ERRORS[400]})
def history_load(req: HistorySummaryRequest, service: HistoryService = Depends(get_history_service)):
    return json_response(service.load(req))
