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
from collections import deque, defaultdict

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


def _parse_csv_set(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def _parse_key_prefix_map(raw: str) -> dict[str, list[str]]:
    """
    Parse `key:prefix1|prefix2,key2:prefix3` into a dict.
    """
    mapping: dict[str, list[str]] = {}
    for chunk in (part.strip() for part in raw.split(",") if part.strip()):
        if ":" not in chunk:
            continue
        key, prefixes = chunk.split(":", 1)
        key = key.strip()
        pref_list = [p.strip() for p in prefixes.split("|") if p.strip()]
        if key and pref_list:
            mapping[key] = pref_list
    return mapping


class _InMemoryRateLimiter:
    """Simple sliding-window limiter (per IP+path, single-process only)."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(1.0, float(window_seconds))
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        ts = time.monotonic() if now is None else now
        cutoff = ts - self.window_seconds
        with self._lock:
            q = self._buckets[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.max_requests:
                return False
            q.append(ts)
            # Prune empty buckets lazily when old keys cool down.
            if not q:
                self._buckets.pop(key, None)
            return True


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
    rate_limit_enabled = os.getenv("DIGITAL_TWIN_RATE_LIMIT_ENABLED", "true").lower() != "false"
    require_athlete_id = os.getenv("DIGITAL_TWIN_REQUIRE_ATHLETE_ID", "false").lower() == "true"
    api_key_auth_enabled = os.getenv("DIGITAL_TWIN_API_KEY_AUTH_ENABLED", "false").lower() == "true"
    valid_api_keys = _parse_csv_set(os.getenv("DIGITAL_TWIN_API_KEYS", ""))
    api_key_athlete_prefixes = _parse_key_prefix_map(
        os.getenv("DIGITAL_TWIN_API_KEY_ATHLETE_PREFIXES", "")
    )
    limiter = _InMemoryRateLimiter(
        max_requests=int(os.getenv("DIGITAL_TWIN_RATE_LIMIT_MAX_REQUESTS", "120")),
        window_seconds=float(os.getenv("DIGITAL_TWIN_RATE_LIMIT_WINDOW_S", "60")),
    )
    athlete_scoped_prefixes = (
        "/ride",
        "/profile",
        "/workouts",
        "/twin",
        "/projection",
        "/performance",
        "/load",
        "/team",
        "/history",
        "/readiness",
        "/planning",
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
        application.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    @application.middleware("http")
    async def limit_request_body(request: Request, call_next):
        path = request.url.path
        athlete_scoped = path.startswith(athlete_scoped_prefixes)
        if api_key_auth_enabled and athlete_scoped:
            auth_header = (request.headers.get("Authorization") or "").strip()
            token = ""
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()
            if not token or token not in valid_api_keys:
                return JSONResponse(status_code=401, content=safe_error_detail("UNAUTHORIZED"))
            request.state.api_key = token

        if require_athlete_id and path.startswith(athlete_scoped_prefixes):
            athlete_id = (request.headers.get("X-Athlete-Id") or "").strip()
            if not athlete_id:
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": {
                            "error": "MISSING_ATHLETE_ID",
                            "message": "Missing required X-Athlete-Id header for athlete-scoped endpoint.",
                        }
                    },
                )
            request.state.athlete_id = athlete_id
            if api_key_auth_enabled:
                allowed_prefixes = api_key_athlete_prefixes.get(getattr(request.state, "api_key", ""), [])
                if allowed_prefixes and not any(athlete_id.startswith(prefix) for prefix in allowed_prefixes):
                    return JSONResponse(status_code=403, content=safe_error_detail("FORBIDDEN"))
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
