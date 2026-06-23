# Backend-definitivo-V5

Python backend for physiological analysis and cycling performance (Digital Twin).

Current version: **5.2.1** — full engine HTTP coverage (105 OpenAPI paths) + dual metabolic/Coggan zones.

## Overview

| Layer | Path | Role |
|-------|------|------|
| **HTTP Entrypoint** | `api_app.py` | Compatible shim for `uvicorn api_app:app` |
| **API package** | `api/` | Routers, services, schemas, upload, serialization |
| **Physiological engines** | `engines/` | Algorithms, tiers, metric contracts |
| **OpenAPI contract** | `openapi/openapi.json` | **105 documented endpoints** |
| **Frontend client** | `frontend/src/api/` | Generated TS types + `api.*` client (all paths) |
| **Tests** | `tests/` | pytest smoke/hardening + `tests/integration/` |

## API surface (5.2.x)

| Tag | Paths | Examples |
|-----|------:|----------|
| ride | 32 | `/ride/summary`, `/ride/analytics/*`, `/ride/durability` |
| profile | 14 | `/profile/snapshot`, `/profile/kalman/trajectory`, `/profile/glycolytic-profile` |
| workouts | 9 | `/workouts/prescribe`, `/workouts/compare` |
| lab | 7 | `/lab/lactate/validate-model`, `/lab/vlapeak/observed` |
| explainability | 6 | `/explainability/vo2max-confidence` |
| twin | 6 | `/twin/state/build`, `/twin/state/validate` |
| load | 5 | `/load/manual`, `/load/acwr` |
| + history, performance, planning, readiness, test, integrations, meta, race, team, health | 20 | see index below |

Full inventory: [`docs/API_ENDPOINT_INDEX.md`](docs/API_ENDPOINT_INDEX.md)

## API architecture (`api/`)

```text
api/
├── app.py                 # FastAPI factory, middleware, exception handlers
├── deps.py                # Dependency injection (Depends → services)
├── engine_schemas.py      # Request DTOs for extended engine endpoints
├── errors.py              # ServiceError → HTTP 4xx
├── schemas.py             # Core Pydantic request DTOs
├── domain_schemas.py      # TwinState, Workout, InPersonTest, …
├── routers/               # Thin HTTP layer — one module per domain
│   ├── health.py, test_routes.py, ride.py, ride_analytics.py
│   ├── profile.py, profile_extended.py, lab.py
│   ├── workouts.py, twin.py, performance.py
│   ├── load.py, load_extended.py, explainability.py
│   ├── race.py, integrations.py, meta.py
│   ├── team.py, history.py, readiness.py, planning.py
│   └── …
└── services/              # Use-case orchestration (no FastAPI)
    ├── ride_service.py, ride_analytics_service.py
    ├── profile_service.py, profile_extended_service.py
    ├── lab_service.py, twin_service.py, …
    └── engine_context.py  # AthleteContext / MetabolicProfiler helpers
```

Flow: **router → service → engines**. Details in `docs/ARCHITECTURE.md`.

## Zones (coach choice)

`/ride/summary` and `/ride/analytics/zones` return **both**:

- **`metabolic_power`** — 5 zones anchored on MLSS/MAP from the metabolic snapshot
- **`coggan_power`** — 7 zones anchored on FTP (industry standard)

Use `sections.zones.systems_available` and `coach_note` in the UI. See `docs/RELEASE_NOTES_v5.2.1.md`.

## Local setup

Prerequisites: Python 3.10+, pip.

```bash
make install
cp .env.example .env   # optional
make run               # http://127.0.0.1:8000
```

Swagger UI: `http://localhost:8000/docs`  
OpenAPI JSON: `http://localhost:8000/openapi.json`

## Development commands

```bash
make run              # uvicorn api_app:app
make test             # smoke pytest (fast local check)
make test-all         # full pytest + integration scripts
make hardening-test   # malformed input robustness
make stress-test      # bounded stress subset
make check            # lint + mypy + test-all + hardening (release gate)
make typecheck-metabolic
make openapi-frontend # export openapi.json + regenerate TS types
make lint | format | typecheck
```

## Tests

| Suite | Command |
|-------|---------|
| Smoke (fast local) | `make test` |
| Full | `make test-all` |
| Engine API coverage | `pytest tests/pytest_engine_api_coverage.py` |
| Metabolic zones | `pytest tests/pytest_metabolic_zones.py` |
| Release gate | `make check` |
| Metabolic typing | `make typecheck-metabolic` |

## Repository structure

```text
.
├── api/                      # HTTP layer (router + service + schemas)
├── api_app.py                # uvicorn entrypoint
├── engines/                  # physiological engines
│   ├── core/                 # tiers, security, athlete_context
│   ├── metabolic/            # profiler, zones, glycolytic validation
│   ├── performance/          # power, MMP, durability, race
│   ├── recovery/             # HRV, cardiac, thermal, explainability
│   ├── io/                   # FIT parser, workout_summary, charts
│   ├── twin_state/           # canonical TwinState v1
│   ├── workouts/             # prescription, compliance, calendar
│   ├── projection/           # season what-if
│   └── integrations/         # external activity normalize/dedupe
├── openapi/openapi.json      # committed OpenAPI 3.1 (105 paths)
├── frontend/                 # Vite/React + api/client.ts
├── tests/
├── docs/                     # architecture, frontend guide, API index
├── scripts/export_openapi.py
└── Makefile
```

## Documentation

| Document | Content |
|----------|---------|
| [`docs/API_ENDPOINT_INDEX.md`](docs/API_ENDPOINT_INDEX.md) | **All 105 endpoints** by tag |
| [`docs/RELEASE_NOTES_v5.2.1.md`](docs/RELEASE_NOTES_v5.2.1.md) | V5.2.0 + V5.2.1 release notes |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layering router/service/engines |
| [`docs/FRONTEND_DEVELOPER_GUIDE.md`](docs/FRONTEND_DEVELOPER_GUIDE.md) | Frontend integration, TwinState, zones |
| [`docs/OPENAPI_FRONTEND.md`](docs/OPENAPI_FRONTEND.md) | OpenAPI, TS codegen, `api.*` client |
| [`docs/FRONTEND_CONNECT_NEXT_VERCEL.md`](docs/FRONTEND_CONNECT_NEXT_VERCEL.md) | Next/Vercel/v0 deployment |
| [`docs/DEPLOY_BACKEND.md`](docs/DEPLOY_BACKEND.md) | Production uvicorn |
| [`docs/API_EXAMPLES.md`](docs/API_EXAMPLES.md) | Minimal JSON payloads |
| [`CHANGELOG.md`](CHANGELOG.md) | Full version history |

## Release policy

Bug fixes and API additions require tests + `make check`. After router/schema changes run `make openapi-frontend` and commit `openapi/openapi.json` (and generated TS if applicable).

## CI

| Workflow | Trigger | Gate |
|----------|---------|------|
| `.github/workflows/ci.yml` | push/PR | `make lint` + `make test-all` |
| `.github/workflows/full-check.yml` | push main, PR, weekly | `make check` |
| `.github/workflows/hardening.yml` | manual | hardening + stress subset |

## Frontend API base URL

| Stack | Variable |
|-------|----------|
| **Vite** (`frontend/`) | `VITE_API_BASE_URL` |
| **Next.js / Vercel / v0** | `NEXT_PUBLIC_API_BASE_URL` |

## What V5.2 includes

- **105 OpenAPI endpoints** — full engine coverage over HTTP
- Metabolic snapshot, Kalman, bayesian profile, glycolytic/vLaPeak validation
- Ride analytics (W′, durability, cardiac, HRV, session routing, …)
- Lab parse/validate, explainability narratives, GPX race simulation
- Dual **metabolic + Coggan** zone systems on activity reports
- Canonical TwinState + season projection + `/twin/state/validate`
- Workout system (validate → prescribe → feasibility → compare)
- Team learning calibration, JWT/OAuth auth, security hardening
- Golden FIT regression suite (`tests/assets/fit/`)

## Branch

- `main` — current backend (5.2.1)
- `old/main` — pre-architectural-refactor snapshot
