from __future__ import annotations

from fastapi import APIRouter

from api.responses import HealthResponse
from api.route_docs import ERRORS, HEALTH_OK

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Health check",
    description="Liveness probe and API version.",
    operation_id="healthCheck",
    response_model=HealthResponse,
    responses={200: HEALTH_OK, **ERRORS},
)
def health() -> HealthResponse:
    from api.app import app

    return HealthResponse(status="ok", service="digital-twin-api", version=app.version)
