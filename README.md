# Backend-definitivo-V5

Python backend for physiological analysis and cycling performance (Digital Twin).

Current version: **5.2.3** — coach layer (20 endpoints), contract-first testing, fueling CHO+FAT grams (132 OpenAPI paths).

## Overview

| Layer | Path | Role |
|-------|------|------|
| **HTTP Entrypoint** | `api_app.py` | Compatible shim for `uvicorn api_app:app` |
| **API package** | `api/` | Routers, services, schemas, upload, serialization |
| **Physiological engines** | `engines/` | Algorithms, tiers, metric contracts |
| **OpenAPI contract** | `openapi/openapi.json` | **132 documented endpoints** |
| **Frontend client** | `frontend/src/api/` | Generated TS types + `api.*` client (all paths) |
| **Tests** | `tests/` | pytest smoke/hardening + `tests/integration/` |

## API surface (5.2.x)

| Tag | Paths | Examples |
|-----|------:|----------|
| ride | 32 | `/ride/summary`, `/ride/analytics/*`, `/ride/durability` |
| **coach** | **20** | `/coach/daily-brief`, `/coach/session-decision`, `/coach/nutrition/performance-targets` |
| profile | 19 | `/profile/snapshot`, `/profile/metabolic/curves`, `/profile/vlamax-from-power-series` |
| workouts | 9 | `/workouts/prescribe`, `/workouts/compare` |
| lab | 7 | `/lab/lactate/validate-model`, `/lab/vlapeak/observed` |
| explainability | 8 | `/explainability/vo2max-confidence`, `/explainability/fatmax-narrative` |
| twin | 6 | `/twin/state/build`, `/twin/state/validate` |
| load | 5 | `/load/manual`, `/load/acwr` |
| + history, performance, planning, readiness, test, integrations, meta, race, team, health | 23 | see index below |

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

Use `sections.zones.systems_available` and `coach_note` in the UI. See `docs/RELEASE_NOTES_v5.2.1.md` and `docs/RELEASE_NOTES_v5.2.2.md`.

## Local setup

Prerequisites: Python **3.10+** (CI uses 3.11), pip.

```bash
make install
cp .env.example .env   # optional — tune CORS, auth, limits
make run               # http://127.0.0.1:8000
```

Swagger UI: `http://localhost:8000/docs`  
OpenAPI JSON: `http://localhost:8000/openapi.json`

### Docker (production-style)

```bash
docker build -t digital-twin-api .
docker run --rm -p 8000:8000 --env-file .env digital-twin-api
# or pass overrides:
docker run --rm -p 8000:8000 \
  -e UVICORN_WORKERS=2 \
  -e DIGITAL_TWIN_CORS_ORIGINS=https://app.example.com \
  digital-twin-api
curl -s http://localhost:8000/health
```

The image installs **production dependencies only** (`pip install .`), runs as non-root, and exposes `/health` for container probes. See [`docs/DEPLOY_BACKEND.md`](docs/DEPLOY_BACKEND.md) for TLS, workers, and auth.


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
| Contract-first (engines + API) | `pytest tests/pytest_engines_contract_all.py tests/pytest_contract_full_codebase.py -q` |
| Engine API coverage | `pytest tests/pytest_engine_api_coverage.py` |
| Metabolic zones | `pytest tests/pytest_metabolic_zones.py` |
| Release gate | `make check` |
| Metabolic typing | `make typecheck-metabolic` |

See `docs/CONTRACT_FIRST_TESTING.md` for the product-contract methodology (~1843 tests in full suite).

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
├── openapi/openapi.json      # committed OpenAPI 3.1 (132 paths)
├── frontend/                 # Vite/React + api/client.ts
├── tests/
├── docs/                     # architecture, frontend guide, API index
├── scripts/export_openapi.py
├── Dockerfile              # production image (pip install ., non-root)
├── .env.example              # full runtime + security env template
└── Makefile
```

## Documentation

| Document | Content |
|----------|---------|
| [`docs/API_ENDPOINT_INDEX.md`](docs/API_ENDPOINT_INDEX.md) | **All 132 endpoints** by tag |
| [`docs/RELEASE_NOTES_v5.2.3.md`](docs/RELEASE_NOTES_v5.2.3.md) | V5.2.3 — coach layer, contract testing, fueling fat_g |
| [`docs/CONTRACT_FIRST_TESTING.md`](docs/CONTRACT_FIRST_TESTING.md) | Product-contract test methodology |
| [`docs/COACH_DECISION_ENGINE.md`](docs/COACH_DECISION_ENGINE.md) | 20 coach decision-support endpoints |
| [`docs/STRENGTH_AND_FUELING_CONTRACT.md`](docs/STRENGTH_AND_FUELING_CONTRACT.md) | Strength + fueling schemas (CHO/FAT g) |
| [`docs/RELEASE_NOTES_v5.2.2.md`](docs/RELEASE_NOTES_v5.2.2.md) | V5.2.2 — power-series VLamax proxy |
| [`docs/VLAMAX_POWER_PROXY_PROTOCOL.md`](docs/VLAMAX_POWER_PROXY_PROTOCOL.md) | Fixed T_PCr semantics, late-peak handling, coach UI wording |
| [`docs/RELEASE_NOTES_v5.2.1.md`](docs/RELEASE_NOTES_v5.2.1.md) | V5.2.0 + V5.2.1 release notes |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layering router/service/engines |
| [`docs/FRONTEND_DEVELOPER_GUIDE.md`](docs/FRONTEND_DEVELOPER_GUIDE.md) | Frontend integration, TwinState, zones |
| [`docs/OPENAPI_FRONTEND.md`](docs/OPENAPI_FRONTEND.md) | OpenAPI, TS codegen, `api.*` client |
| [`docs/FRONTEND_CONNECT_NEXT_VERCEL.md`](docs/FRONTEND_CONNECT_NEXT_VERCEL.md) | Next/Vercel/v0 deployment |
| [`docs/DEPLOY_BACKEND.md`](docs/DEPLOY_BACKEND.md) | Production uvicorn, Docker, workers, per-process rate limits |
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

- **132 OpenAPI endpoints** — full engine + coach coverage over HTTP
- **20 coach endpoints** — decision safety, daily brief, fueling, periodization, …
- Contract-first test suites (`docs/CONTRACT_FIRST_TESTING.md`)
- Metabolic snapshot, Kalman, bayesian profile, glycolytic/vLaPeak validation
- Performance fueling targets with **session_carbohydrate_g** + **session_fat_g** (INSCYD-style grams)
- Ride analytics (W′, durability, cardiac, HRV, session routing, …)
- Lab parse/validate, explainability narratives, GPX race simulation
- Dual **metabolic + Coggan** zone systems on activity reports
- Canonical TwinState + season projection + `/twin/state/validate`
- Workout system (validate → prescribe → feasibility → compare)
- Team learning calibration, JWT/OAuth auth, security hardening
- Golden FIT regression suite (`tests/assets/fit/`)

## Branch

- `main` — current backend (5.2.3)
- `old/main` — pre-architectural-refactor snapshot
