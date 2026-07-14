# Release notes — V5.2.6

**Tag:** `v5.2.6`  
**Date:** 2026-06-17  
**Base:** V5.2.5

## Summary

V5.2.6 completes the **chart audit roadmap** and aligns the repository to a single API version string. Subsequent compatible additions kept the same version number; the current `main` baseline is therefore 135 OpenAPI paths and 43 chart types.

## API surface — 135 OpenAPI paths

| Area | New / updated |
|------|----------------|
| `meta` | `GET /meta/chart-types`, extended `POST /meta/chart-config` (43 chart types) |
| `dashboard` | `POST /dashboard/athlete-snapshot` |
| `ride` | `POST /ride/full-bundle` included in the current OpenAPI baseline |

## Chart catalog (43 types)

The chart roadmap introduced nine builders: `acwr_trend`, `monotony_strain`, `readiness_trend`, `durability_fingerprint`, `race_simulation_overlay`, `kalman_trajectory`, `pmc_forecast`, `segment_history`, `eddington_consistency`. The current registry contains 43 chart types in total.

## Engines

- `engines/performance/consistency_engine.py` — Eddington number, segment history aggregation
- `api/chart_schemas.py` — Pydantic `ChartConfigEnvelope` validation

## Version alignment

All of the following report **5.2.6**:

- `VERSION`, `pyproject.toml`, `.env.example`
- `api/app.py` default `DIGITAL_TWIN_API_VERSION`
- `openapi/openapi.json`
- README and developer docs (current-version references)
- Frontend typed client (`frontend/src/api/client.ts`)

## Docs

- `docs/CHART_CONFIG_CONTRACT.md` — full 43-type catalog + dashboard snapshot
- `CHANGELOG.md` [5.2.6]

## Tests

- `tests/pytest_chart_roadmap_items.py` — 11 tests
- OpenAPI and API index — **135 paths** checked automatically
- Generated TypeScript path inventory — all paths checked, with the single temporary `/ride/full-bundle` codegen exception tracked in issue #14