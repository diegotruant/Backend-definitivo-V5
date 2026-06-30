# Release notes — V5.2.6

**Tag:** `v5.2.6`  
**Date:** 2026-06-17  
**Base:** V5.2.5

## Summary

V5.2.6 completes the **chart audit roadmap** and aligns the entire repository to a single API version string.

## API surface — 134 OpenAPI paths

| Area | New / updated |
|------|----------------|
| `meta` | `GET /meta/chart-types`, extended `POST /meta/chart-config` (42 chart types) |
| `dashboard` | `POST /dashboard/athlete-snapshot` |

## Chart catalog (42 types)

Nine new chart builders: `acwr_trend`, `monotony_strain`, `readiness_trend`, `durability_fingerprint`, `race_simulation_overlay`, `kalman_trajectory`, `pmc_forecast`, `segment_history`, `eddington_consistency`.

## Engines

- `engines/performance/consistency_engine.py` — Eddington number, segment history aggregation
- `api/chart_schemas.py` — Pydantic `ChartConfigEnvelope` validation

## Version alignment

All of the following now report **5.2.6**:

- `VERSION`, `pyproject.toml`, `.env.example`
- `api/app.py` default `DIGITAL_TWIN_API_VERSION`
- `openapi/openapi.json`
- README and developer docs (current-version references)
- Frontend typed client (`frontend/src/api/client.ts`)

## Docs

- `docs/CHART_CONFIG_CONTRACT.md` — full 42-type catalog + dashboard snapshot
- `CHANGELOG.md` [5.2.6]

## Tests

- `tests/pytest_chart_roadmap_items.py` — 11 tests
- Frontend client ↔ OpenAPI contract — **134 paths** 1:1
