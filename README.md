# Backend-definitivo-V5

Python backend for physiological analysis and cycling performance (Digital Twin).

Current version: **5.1.1** — frontend integration stabilization (tests + docs). Architectural baseline: **v5.1.0**.

## Overview

| Layer | Path | Role |
|-------|------|--------|
| **HTTP Entrypoint** | `api_app.py` | Compatible shim for `uvicorn api_app:app` |
| **API package** | `api/` | Router, service, schemas, upload, serialization |
| **Physiological engines** | `engines/` | Algorithms, tier, metric contracts |
| **OpenAPI Contract** | `openapi/openapi.json` | 42 documented endpoints |
| **Frontend client** | `frontend/src/api/` | Generated TS types + `api.*` client |
| **Tests** | `tests/` | pytest smoke/hardening + `tests/integration/` |

## API Architecture (`api/`)

```text
api/
├── app.py                 # FastAPI factory, middleware, exception handlers
├── deps.py                # Dependency injection (Depends → services)
├── errors.py              # ServiceError → HTTP 4xx
├── schemas.py             # Pydantic request DTOs (API boundary)
├── domain_schemas.py      # Typed payloads: TwinState, Workout, InPersonTest, …
├── serialization.py       # JSON safety (NaN/Inf → null)
├── upload.py              # FIT multipart parsing
├── parsing.py             # Date, snapshot, curve coercion, AthleteContext
├── activity_streams.py    # FIT or power_json → ActivityStream
├── helpers.py             # Legacy re-export (prefer modules above)
├── openapi.py             # OpenAPI metadata (servers, codegen hints)
├── responses.py           # Response models for Swagger
├── route_docs.py          # OpenAPI response templates
├── routers/               # Thin HTTP layer — one file per domain
│   ├── health.py
│   ├── test_routes.py
│   ├── ride.py
│   ├── profile.py
│   ├── workouts.py
│   ├── twin.py
│   ├── performance.py
│   ├── load.py
│   └── team.py
└── services/              # Use-case orchestration (no FastAPI)
    ├── test_service.py
    ├── ride_service.py
    ├── profile_service.py
    ├── workout_service.py
    ├── twin_service.py
    ├── team_service.py
    ├── performance_service.py
    └── load_service.py
```

Flow: **router → service → engines**. Details in `docs/ARCHITECTURE.md`.

## Local setup

Prerequisites: Python 3.10+, pip.

```bash
make install
cp .env.example .env   # opzionale
make run               # http://127.0.0.1:8000
```

Swagger UI: `http://localhost:8000/docs`

## Development commands

```bash
make run              # uvicorn api_app:app
make test             # smoke pytest (fast local check)
make test-all         # full pytest + integration scripts
make hardening-test   # malformed input robustness
make stress-test      # bounded stress subset
make check            # lint + mypy + test-all + hardening (release gate)
make typecheck-metabolic # mypy on engines/metabolic
make openapi-frontend # export openapi.json + regenerate TS types
make lint | format | typecheck
```

## Tests

| Suite | Comando |
|-------|---------|
| Smoke (fast local) | `make test` |
| Full | `make test-all` |
| Integration scripts | `tests/integration/test_*.py` via `pytest_script_suite.py` |
| Release gate | `make check` |
| Metabolic typing | `make typecheck-metabolic` |

## Repository structure

```text
.
├── api/                      # HTTP layer (router + service + schemas)
├── api_app.py                # uvicorn entrypoint
├── engines/                  # physiological engines
│   ├── core/                 # tier, security, athlete_context
│   ├── metabolic/            # profiler, team learning, zones
│   ├── performance/          # power, MMP, durability, protocols
│   ├── recovery/             # HRV, cardiac, thermal
│   ├── io/                   # FIT parser, workout_summary, charts
│   ├── twin_state/           # canonical TwinState v1
│   ├── workouts/             # prescription, compliance, calendar
│   ├── projection/           # season what-if
│   └── load/                 # manual non-cycling load
├── openapi/                  # committed openapi.json
├── frontend/                   # client Vite/React + api/client.ts
├── tests/
│   ├── pytest_*.py           # smoke, hardening, security
│   └── integration/          # executable regression scripts
├── docs/                     # ARCHITECTURE, FRONTEND_DEVELOPER_GUIDE, OPENAPI_FRONTEND
├── scripts/export_openapi.py
├── tools/stress/             # multitenant + deep bottleneck harness
└── Makefile
```

## Documentation

| Document | Content |
|-----------|-----------|
| `docs/ARCHITECTURE.md` | Layering router/service/engines |
| `docs/FRONTEND_DEVELOPER_GUIDE.md` | Frontend integration, TwinState, endpoint map |
| `docs/FRONTEND_CONNECT_NEXT_VERCEL.md` | **Next/Vercel/v0** — env, CORS, FormData, offline |
| `docs/DEPLOY_BACKEND.md` | Production uvicorn deployment |
| `docs/API_EXAMPLES.md` | Minimal copy-paste JSON payloads |
| `docs/TROUBLESHOOTING.md` | CORS, upload, CI, TwinState |
| `docs/RELEASE_NOTES_v5.1.0.md` | Architectural baseline (tag v5.1.0) |
| `docs/RELEASE_NOTES_v5.1.1.md` | Test + frontend docs stabilization |

## V5.1.x Policy

No major new features. Only bug fixes (with tests), tests on critical contracts, product/deployment docs. Release gate: `make check`.

## CI

| Workflow | Trigger | Gate |
|----------|---------|------|
| `.github/workflows/ci.yml` | push/PR | `make lint` + `make test-all` |
| `.github/workflows/full-check.yml` | push main, PR, weekly | `make check` (release gate) |
| `.github/workflows/hardening.yml` | manual | hardening + stress subset |

## Frontend API base URL

The backend is agnostic. The client supports both conventions:

| Stack | Variabile |
|-------|-----------|
| **Vite** (MVP in `frontend/`) | `VITE_API_BASE_URL` |
| **Next.js / Vercel / v0** | `NEXT_PUBLIC_API_BASE_URL` |

## What V5.1 includes

- Canonical TwinState (`twin_state.v1`) + seasonal projection
- Workout system (validate → prescribe → feasibility → compare)
- Team learning calibration
- mader_durability, neuromuscular profile, manual load
- Security hardening (upload limits, JSON depth, CORS, rate limiting)
- Optional tenant gating via `X-Athlete-Id` (feature flag)
- OpenAPI 3.1 with 42 endpoints + generated TypeScript client

## Branch

- `main` — current backend
- `old/main` — pre-architectural-refactor snapshot
