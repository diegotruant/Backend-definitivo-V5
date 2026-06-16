"""
FastAPI application factory for the Digital Twin backend.

The public entrypoint remains ``api_app:app`` for backward compatibility with
uvicorn, CI workflows and existing documentation.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.openapi.utils import get_openapi
    from fastapi.responses import JSONResponse
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "FastAPI is required for the API layer: pip install fastapi uvicorn"
    ) from e

from api.errors import ServiceError
from api.openapi import enrich_openapi_schema
from api.routers import health, history, load, performance, planning, profile, readiness, ride, team, test_routes, twin, workouts
from engines.core.security import MAX_UPLOAD_BYTES, MAX_UPLOAD_FILES, safe_error_detail

OPENAPI_TAGS = [
    {"name": "health", "description": "Liveness and version."},
    {"name": "test", "description": "Field test onboarding (propose → confirm)."},
    {"name": "ride", "description": "FIT ingestion, activity analysis, durability."},
    {"name": "profile", "description": "Metabolic snapshot read model."},
    {"name": "workouts", "description": "Prescription, feasibility, compliance."},
    {"name": "twin", "description": "Canonical TwinState and season projection."},
    {"name": "performance", "description": "Neuromuscular profile and power-source QA."},
    {"name": "load", "description": "Non-cycling manual load injection."},
    {"name": "team", "description": "Team learning calibration."},
    {"name": "history", "description": "Athlete history, power-curve records and load trends."},
    {"name": "readiness", "description": "Daily readiness and load-risk estimates."},
    {"name": "planning", "description": "Season plans and adaptive weekly planning."},
]

app: FastAPI


def _register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(ServiceError)
    async def handle_service_error(_request: Request, exc: ServiceError) -> JSONResponse:
        detail: Any = exc.details if exc.details is not None else exc.message
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})


def create_app() -> FastAPI:
    application = FastAPI(
        title=os.getenv("DIGITAL_TWIN_API_TITLE", "Digital Twin Fisiologico API"),
        version=os.getenv("DIGITAL_TWIN_API_VERSION", "5.1.1"),
        description=(
            "Stateless physiology analytics API. HTTP routers are thin; "
            "application services orchestrate engines under `engines/`."
        ),
        openapi_tags=OPENAPI_TAGS,
    )

    _register_exception_handlers(application)

    def custom_openapi() -> dict[str, Any]:
        if application.openapi_schema:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title,
            version=application.version,
            description=application.description,
            routes=application.routes,
            tags=application.openapi_tags,
        )
        application.openapi_schema = enrich_openapi_schema(schema)
        return application.openapi_schema

    application.openapi = custom_openapi  # type: ignore[method-assign]

    cors_origins = [
        o.strip()
        for o in os.getenv("DIGITAL_TWIN_CORS_ORIGINS", "").split(",")
        if o.strip()
    ]
    if cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    @application.middleware("http")
    async def limit_request_body(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_UPLOAD_BYTES * (MAX_UPLOAD_FILES + 1):
                    return JSONResponse(
                        status_code=413,
                        content=safe_error_detail("FILE_TOO_LARGE"),
                    )
            except ValueError:
                pass
        return await call_next(request)

    for router in (
        health.router,
        test_routes.router,
        ride.router,
        profile.router,
        workouts.router,
        twin.router,
        performance.router,
        load.router,
        team.router,
        history.router,
        readiness.router,
        planning.router,
    ):
        application.include_router(router)

    return application


app = create_app()
