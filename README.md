# Backend-definitivo-V5

Backend Python per analisi fisiologica e performance cycling (Digital Twin).

Versione attuale: **5.1.1** — stabilizzazione integrazione frontend (test + docs). Baseline architetturale: **v5.1.0**.

## Panoramica

| Layer | Path | Ruolo |
|-------|------|--------|
| **Entrypoint HTTP** | `api_app.py` | Shim compatibile per `uvicorn api_app:app` |
| **API package** | `api/` | Router, service, schemi, upload, serializzazione |
| **Motori fisiologici** | `engines/` | Algoritmi, tier, contratti metrica |
| **Contratto OpenAPI** | `openapi/openapi.json` | 24 endpoint documentati |
| **Frontend client** | `frontend/src/api/` | Tipi TS generati + client `api.*` |
| **Test** | `tests/` | pytest smoke/hardening + `tests/integration/` |

## Architettura API (`api/`)

```text
api/
├── app.py                 # FastAPI factory, middleware, exception handlers
├── deps.py                # Dependency injection (Depends → services)
├── errors.py              # ServiceError → HTTP 4xx
├── schemas.py             # Request DTO Pydantic (API boundary)
├── domain_schemas.py      # Payload tipizzati: TwinState, Workout, InPersonTest, …
├── serialization.py       # JSON safety (NaN/Inf → null)
├── upload.py              # FIT multipart parsing
├── parsing.py             # Date, snapshot, curve coercion, AthleteContext
├── activity_streams.py    # FIT o power_json → ActivityStream
├── helpers.py             # Re-export legacy (prefer moduli sopra)
├── openapi.py             # Metadata OpenAPI (servers, codegen hints)
├── responses.py           # Response models per Swagger
├── route_docs.py          # OpenAPI response templates
├── routers/               # HTTP thin — un file per dominio
│   ├── health.py
│   ├── test_routes.py
│   ├── ride.py
│   ├── profile.py
│   ├── workouts.py
│   ├── twin.py
│   ├── performance.py
│   ├── load.py
│   └── team.py
└── services/              # Orchestrazione use-case (no FastAPI)
    ├── test_service.py
    ├── ride_service.py
    ├── profile_service.py
    ├── workout_service.py
    ├── twin_service.py
    ├── team_service.py
    ├── performance_service.py
    └── load_service.py
```

Flusso: **router → service → engines**. Dettagli in `docs/ARCHITECTURE.md`.

## Setup locale

Prerequisiti: Python 3.10+, pip.

```bash
make install
cp .env.example .env   # opzionale
make run               # http://127.0.0.1:8000
```

Swagger UI: `http://localhost:8000/docs`

## Comandi sviluppo

```bash
make run              # uvicorn api_app:app
make test             # smoke pytest (veloce, CI default)
make test-all         # pytest completo + integration scripts
make hardening-test   # robustezza input malformati
make stress-test      # subset stress bounded
make check            # lint + mypy + test-all + hardening (release gate)
make openapi-frontend # export openapi.json + rigenera tipi TS
make lint | format | typecheck
```

## Test

| Suite | Comando |
|-------|---------|
| Smoke (CI rapida) | `make test` |
| Completa | `make test-all` |
| Integration scripts | `tests/integration/test_*.py` via `pytest_script_suite.py` |
| Release gate | `make check` |

## Struttura repository

```text
.
├── api/                      # HTTP layer (router + service + schemas)
├── api_app.py                # entrypoint uvicorn
├── engines/                  # motori fisiologici
│   ├── core/                 # tier, security, athlete_context
│   ├── metabolic/            # profiler, team learning, zones
│   ├── performance/          # power, MMP, durability, protocols
│   ├── recovery/             # HRV, cardiac, thermal
│   ├── io/                   # FIT parser, workout_summary, charts
│   ├── twin_state/           # TwinState v1 canonico
│   ├── workouts/             # prescription, compliance, calendar
│   ├── projection/           # season what-if
│   └── load/                 # manual non-cycling load
├── openapi/                  # openapi.json committato
├── frontend/                   # client Vite/React + api/client.ts
├── tests/
│   ├── pytest_*.py           # smoke, hardening, security
│   └── integration/          # regression script eseguibili
├── docs/                     # ARCHITECTURE, FRONTEND_DEVELOPER_GUIDE, OPENAPI_FRONTEND
├── scripts/export_openapi.py
├── tools/stress/             # multitenant + deep bottleneck harness
└── Makefile
```

## Documentazione

| Documento | Contenuto |
|-----------|-----------|
| `docs/ARCHITECTURE.md` | Layering router/service/engines |
| `docs/FRONTEND_DEVELOPER_GUIDE.md` | Integrazione frontend, TwinState, endpoint map |
| `docs/FRONTEND_CONNECT_NEXT_VERCEL.md` | **Next/Vercel/v0** — env, CORS, FormData, offline |
| `docs/DEPLOY_BACKEND.md` | Deploy produzione uvicorn |
| `docs/API_EXAMPLES.md` | Payload JSON minimi copy-paste |
| `docs/TROUBLESHOOTING.md` | CORS, upload, CI, TwinState |
| `docs/RELEASE_NOTES_v5.1.0.md` | Baseline architetturale (tag v5.1.0) |
| `docs/RELEASE_NOTES_v5.1.1.md` | Stabilizzazione test + docs frontend |

## Politica V5.1.x

Nessuna nuova feature grossa. Solo bugfix (con test), test su contratti critici, docs prodotto/deploy. Gate release: `make check`.

## CI

| Workflow | Trigger | Gate |
|----------|---------|------|
| `.github/workflows/ci.yml` | push/PR | `make lint` + `make test` (smoke veloce) |
| `.github/workflows/full-check.yml` | push main, PR, weekly | `make check` (release gate) |
| `.github/workflows/hardening.yml` | manual | hardening + stress subset |

## Frontend API base URL

Il backend è agnostico. Il client supporta entrambe le convenzioni:

| Stack | Variabile |
|-------|-----------|
| **Vite** (MVP in `frontend/`) | `VITE_API_BASE_URL` |
| **Next.js / Vercel / v0** | `NEXT_PUBLIC_API_BASE_URL` |

## Cosa include V5.1

- TwinState canonico (`twin_state.v1`) + projection stagionale
- Workout system (validate → prescribe → feasibility → compare)
- Team learning calibration
- mader_durability, neuromuscular profile, manual load
- Security hardening (upload limits, JSON depth, CORS)
- OpenAPI 3.1 con 24 endpoint + client TypeScript generato

## Branch

- `main` — backend attuale
- `old/main` — snapshot pre-refactor architetturale
