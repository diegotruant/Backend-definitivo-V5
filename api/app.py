"""
FastAPI application factory for the Digital Twin backend.

The public entrypoint remains ``api_app:app`` for backward compatibility with
uvicorn, CI workflows and existing documentation.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any
from collections import deque

try:
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.openapi.utils import get_openapi
    from fastapi.responses import JSONResponse
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "FastAPI is required for the API layer: pip install fastapi uvicorn"
    ) from e

from api.auth import authenticate_request, load_auth_config
from api.errors import ServiceError
from api.openapi import enrich_openapi_schema
from api.routers import (
    coach_support,
    explainability,
    health,
    history,
    integrations,
    lab,
    load,
    load_extended,
    meta,
    performance,
    planning,
    profile,
    profile_extended,
    race,
    readiness,
    ride,
    ride_analytics,
    team,
    test_routes,
    twin,
    workouts,
)
from engines.core.security import MAX_UPLOAD_BYTES, MAX_UPLOAD_FILES, safe_error_detail

OPENAPI_TAGS = [
    {"name": "health", "description": "Liveness and version."},
    {"name": "test", "description": "Field test onboarding (propose → confirm)."},
    {"name": "ride", "description": "FIT ingestion, activity analysis, durability, extended analytics."},
    {"name": "profile", "description": "Metabolic snapshot, Kalman, glycolytic profile, MMP quality."},
    {"name": "lab", "description": "Lab PDF/text parsing, lactate validation, vLaPeak."},
    {"name": "workouts", "description": "Prescription, feasibility, compliance."},
    {"name": "twin", "description": "Canonical TwinState and season projection."},
    {"name": "performance", "description": "Neuromuscular profile and power-source QA."},
    {"name": "load", "description": "Manual load, ACWR, monotony/strain, adaptive trends."},
    {"name": "explainability", "description": "Confidence scores and coach narratives."},
    {"name": "race", "description": "GPX course analysis and race simulation."},
    {"name": "integrations", "description": "External activity normalization and deduplication."},
    {"name": "meta", "description": "Engine tiers and chart configuration."},
    {"name": "team", "description": "Team learning calibration."},
    {"name": "history", "description": "Athlete history, power-curve records and load trends."},
    {"name": "readiness", "description": "Daily readiness and load-risk estimates."},
    {"name": "planning", "description": "Season plans and adaptive weekly planning."},
]

app: FastAPI


class _InMemoryRateLimiter:
    """Sliding-window request limiter keyed by client identifier (IP + method + path).

    Counter state lives in this process only. With ``uvicorn --workers N`` (N>1) or
    multiple API replicas behind a load balancer, each process keeps separate buckets,
    so the effective ceiling is roughly ``max_requests × workers`` (× replicas) unless
    traffic is pinned to one worker.

    For a single global limit across workers, disable in-app limiting
    (``DIGITAL_TWIN_RATE_LIMIT_ENABLED=false``) and enforce at the reverse proxy /
    API gateway, or use a shared store (e.g. Redis) instead of this class.
    """

    _PRUNE_EVERY = 256

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(1.0, float(window_seconds))
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def _prune_stale_buckets(self, cutoff: float) -> None:
        """Drop keys whose newest timestamp fell outside the sliding window."""
        stale_keys = [
            key
            for key, timestamps in self._buckets.items()
            if not timestamps or timestamps[-1] < cutoff
        ]
        for key in stale_keys:
            self._buckets.pop(key, None)

    def allow(self, key: str, now: float | None = None) -> bool:
        ts = time.monotonic() if now is None else now
        cutoff = ts - self.window_seconds
        with self._lock:
            self._calls += 1
            if self._calls % self._PRUNE_EVERY == 0:
                self._prune_stale_buckets(cutoff)

            timestamps = self._buckets.get(key)
            if timestamps is not None:
                while timestamps and timestamps[0] < cutoff:
                    timestamps.popleft()
                if not timestamps:
                    self._buckets.pop(key, None)
                    timestamps = None

            if timestamps is None:
                timestamps = deque()
                self._buckets[key] = timestamps

            if len(timestamps) >= self.max_requests:
                return False
            timestamps.append(ts)
            return True


def _register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(ServiceError)
    async def handle_service_error(_request: Request, exc: ServiceError) -> JSONResponse:
        detail: Any = exc.details if exc.details is not None else exc.message
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})


def _resolve_cors_settings(cors_origins: list[str]) -> tuple[list[str], bool]:
    """Validate CORS origins against credential rules enforced by browsers."""
    if "*" in cors_origins:
        raise ValueError(
            "DIGITAL_TWIN_CORS_ORIGINS cannot include '*' while allow_credentials=True. "
            "Browsers reject wildcard origins with credentials; list explicit origins instead."
        )
    return cors_origins, True


def create_app() -> FastAPI:
    application = FastAPI(
        title=os.getenv("DIGITAL_TWIN_API_TITLE", "Digital Twin Fisiologico API"),
        version=os.getenv("DIGITAL_TWIN_API_VERSION", "5.2.3"),
        description=(
            "Stateless physiology analytics API. HTTP routers are thin; "
            "application services orchestrate engines under `engines/`."
        ),
        openapi_tags=OPENAPI_TAGS,
    )

    _register_exception_handlers(application)
    auth_config = load_auth_config()
    rate_limit_enabled = os.getenv("DIGITAL_TWIN_RATE_LIMIT_ENABLED", "true").lower() != "false"
    limiter = _InMemoryRateLimiter(
        max_requests=int(os.getenv("DIGITAL_TWIN_RATE_LIMIT_MAX_REQUESTS", "120")),
        window_seconds=float(os.getenv("DIGITAL_TWIN_RATE_LIMIT_WINDOW_S", "60")),
    )

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
        resolved_origins, allow_credentials = _resolve_cors_settings(cors_origins)
        application.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_origins,
            allow_credentials=allow_credentials,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    @application.middleware("http")
    async def limit_request_body(request: Request, call_next):
        path = request.url.path
        auth_result = authenticate_request(
            path=path,
            authorization=request.headers.get("Authorization"),
            athlete_header=request.headers.get("X-Athlete-Id"),
            config=auth_config,
        )
        if not auth_result.ok:
            return JSONResponse(status_code=auth_result.status_code, content=auth_result.body)
        if auth_result.principal is not None:
            request.state.principal = auth_result.principal
        if auth_result.api_key is not None:
            request.state.api_key = auth_result.api_key
        if auth_result.athlete_id is not None:
            request.state.athlete_id = auth_result.athlete_id
        if rate_limit_enabled:
            if path not in {"/health"} and not path.startswith(("/docs", "/redoc", "/openapi")):
                client_ip = request.client.host if request.client else "unknown"
                key = f"{client_ip}:{request.method}:{path}"
                if not limiter.allow(key):
                    return JSONResponse(status_code=429, content=safe_error_detail("RATE_LIMITED"))
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
        ride_analytics.router,
        profile.router,
        profile_extended.router,
        lab.router,
        workouts.router,
        twin.router,
        performance.router,
        load.router,
        load_extended.router,
        explainability.router,
        race.router,
        integrations.router,
        meta.router,
        team.router,
        history.router,
        readiness.router,
        planning.router,
        coach_support.router,
    ):
        application.include_router(router)

    return application


app = create_app()
