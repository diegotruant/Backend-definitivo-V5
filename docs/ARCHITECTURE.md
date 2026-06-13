# Architecture — Backend Digital Twin V5.1

This document describes the **intended layering** after the professional refactor.
It is the reference for new contributors.

## Layers

```text
┌─────────────────────────────────────────────────────────┐
│  HTTP (api/routers/)     — parsing, status codes only   │
├─────────────────────────────────────────────────────────┤
│  Application (api/services/) — orchestration, no FastAPI  │
├─────────────────────────────────────────────────────────┤
│  Domain (engines/)       — physiology, FIT, models        │
└─────────────────────────────────────────────────────────┘
```

| Layer | Responsibility | Must NOT |
|-------|----------------|----------|
| **routers** | Multipart/JSON input, `Depends()`, `json_response()` | Call scipy, fit engines directly |
| **services** | Use-case orchestration, `ServiceError` | Import FastAPI |
| **engines** | Algorithms, tiers, scientific contracts | Know about HTTP |

## Package layout

```text
api/
  app.py              # FastAPI factory, middleware, exception handlers
  deps.py             # Service singletons (Depends)
  errors.py           # ServiceError → HTTP mapping
  schemas.py          # Pydantic request DTOs
  helpers.py          # Upload parsing, JSON safety (HTTP-adjacent)
  routers/            # One module per domain
  services/           # One class per domain use-case group

engines/
  core/               # Athlete context, tiers, security
  metabolic/          # Profiler, team learning, zones
  performance/        # Power, MMP, durability, protocols
  recovery/           # HRV, cardiac, thermal
  io/                 # FIT parser, workout summary, charts
  twin_state/         # Canonical TwinState v1
  workouts/           # Prescription, compliance, calendar
  projection/         # Season what-if
  load/               # Manual non-cycling load

tests/
  pytest_*.py         # Fast pytest suite (CI smoke + hardening)
  integration/        # Executable regression scripts
```

## Entry points

| Command | Purpose |
|---------|---------|
| `uvicorn api_app:app` | Production/dev API (shim → `api.app`) |
| `make test` | Smoke |
| `make test-all` | Full pytest + integration scripts |
| `make check` | lint + typecheck + test-all + hardening |

## OpenAPI contract

FastAPI exposes the contract at:

- `GET /openapi.json`
- `GET /docs` (Swagger UI)

Frontend teams should treat **OpenAPI + `docs/API_PAYLOAD_EXAMPLES.md`** as the integration source of truth.

## Error model

- Routers and services raise `api.errors.ServiceError` for predictable 4xx cases.
- `api.app` registers a global handler → `{"detail": ...}` (same shape as `HTTPException`).
- Unexpected exceptions remain 500; log server-side only.

## State

The API is **stateless**. Persist `TwinState`, anchors, curves and calibration models in your database; round-trip them on each call.

## Testing strategy

1. **Unit/domain** — `tests/pytest_*.py`, `tests/integration/test_*.py` (engines)
2. **HTTP contract** — `tests/integration/test_api_app.py`, `tests/pytest_hardening_api.py`
3. **Robustness** — `pytest -m hardening`
4. **Release gate** — `make check`

## Legacy imports

Flat imports (`import fit_parser`) still work but emit `DeprecationWarning`.
New code must use canonical paths: `engines.io.fit_parser`.
