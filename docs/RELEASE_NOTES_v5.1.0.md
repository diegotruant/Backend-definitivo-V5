# Release notes — V5.1.0

**Tag:** `v5.1.0`  
**Role:** Architectural baseline (frozen reference)

## Summary

V5.1.0 is the first **professionally layered** release of the Digital Twin backend: HTTP routers, application services, domain engines, full OpenAPI contract, and typed frontend client.

## Architecture

- `api/routers/` — thin HTTP (9 domain routers)
- `api/services/` — use-case orchestration (8 services)
- `engines/` — physiology, FIT, TwinState, workouts (unchanged domain core)
- `api_app.py` — backward-compatible uvicorn entrypoint

## Features

- TwinState canonical schema `twin_state.v1`
- Workout system: validate → prescribe → feasibility → compare
- Season projection + team calibration
- 24 documented HTTP endpoints
- OpenAPI 3.1 + TypeScript codegen (`make openapi-frontend`)
- Security hardening: upload limits, JSON depth, safe error detail

## Quality

- `make check` = lint + mypy + full pytest + hardening
- `tests/integration/` regression scripts
- Stress / multitenant campaigns documented

## Branch

- `old/main` — pre-refactor snapshot
- `main` @ v5.1.0 — new architecture

## Upgrade from pre-refactor

- Import path unchanged: `uvicorn api_app:app`
- HTTP paths unchanged for existing clients
- New endpoints: twin, workouts, performance, load, team

---

See `RELEASE_NOTES_v5.1.1.md` for the stabilization release (tests + integration docs).
