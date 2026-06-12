"""
FastAPI application factory for the Digital Twin backend.

The public entrypoint remains ``api_app:app`` for backward compatibility with
uvicorn, CI workflows and existing documentation.
"""

from __future__ import annotations

import os

try:
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "FastAPI is required for the API layer: pip install fastapi uvicorn"
    ) from e

from engines.core.security import MAX_UPLOAD_BYTES, MAX_UPLOAD_FILES, safe_error_detail

from api.routers import health, load, performance, profile, ride, team, test_routes, twin, workouts

app: FastAPI


def create_app() -> FastAPI:
    application = FastAPI(
        title=os.getenv("DIGITAL_TWIN_API_TITLE", "Digital Twin Fisiologico API"),
        version=os.getenv("DIGITAL_TWIN_API_VERSION", "5.1.0"),
    )

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
    ):
        application.include_router(router)

    return application


app = create_app()
