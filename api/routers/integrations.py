"""External activity integration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_integration_service
from api.engine_schemas import (
    IntegrationDeduplicateRequest,
    IntegrationHealthDailyEnergyRequest,
    IntegrationNormalizeRequest,
)
from api.helpers import json_response
from api.responses import EnginePayload
from api.route_docs import ERRORS, JSON_OBJECT
from api.services.integration_service import IntegrationService

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.post("/activity/normalize", operation_id="integrationsNormalizeActivity", response_model=EnginePayload, responses={200: JSON_OBJECT})
def normalize_activity(req: IntegrationNormalizeRequest, service: IntegrationService = Depends(get_integration_service)):
    return json_response(service.normalize_activity(req))


@router.post("/activities/deduplicate", operation_id="integrationsDeduplicateActivities", response_model=EnginePayload, responses={200: JSON_OBJECT})
def deduplicate(req: IntegrationDeduplicateRequest, service: IntegrationService = Depends(get_integration_service)):
    return json_response(service.deduplicate(req))


@router.post(
    "/health/daily-energy",
    operation_id="integrationsHealthDailyEnergy",
    response_model=EnginePayload,
    responses={200: JSON_OBJECT},
)
def health_daily_energy(
    req: IntegrationHealthDailyEnergyRequest,
    service: IntegrationService = Depends(get_integration_service),
):
    return json_response(service.daily_energy(req))
