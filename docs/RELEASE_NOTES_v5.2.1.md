# Release notes — V5.2.1

**Tag:** `v5.2.1`  
**Date:** 2026-06-17  
**Base:** `v5.2.0` (full engine API) + dual zone systems

## Summary

V5.2.1 completes the **coach-facing zone model**: metabolic MLSS zones and Coggan FTP zones are returned **together** so the coach chooses which system to prescribe. It builds on V5.2.0, which exposed engine-only capabilities over HTTP (**105 OpenAPI paths**).

## Highlights

### V5.2.0 — Full engine HTTP coverage

- **105 documented endpoints** (was ~43 in V5.1.x)
- New router groups: `profile` (extended), `lab`, `ride/analytics`, `load` (extended), `explainability`, `race`, `integrations`, `meta`
- `api/engine_schemas.py` + domain services orchestrating `engines/`
- Frontend `client.ts` aligned with full OpenAPI surface
- Smoke tests: `tests/pytest_engine_api_coverage.py`

### V5.2.1 — Dual zone systems

- `zones_engine` v1.1.0: `metabolic_power` (MLSS/MAP 5-zone) + `coggan_power` (7-zone FTP)
- `build_workout_summary()` wires metabolic snapshot into zones automatically
- `/ride/analytics/zones` accepts optional `metabolic_snapshot_json`
- Seiler VT1/VT2 default from MLSS when snapshot is present
- Tests: `tests/pytest_metabolic_zones.py`

## OpenAPI inventory (105 paths)

| Tag | Count |
|-----|------:|
| ride | 32 |
| profile | 14 |
| workouts | 9 |
| lab | 7 |
| explainability | 6 |
| twin | 6 |
| load | 5 |
| history | 4 |
| performance | 4 |
| planning | 3 |
| readiness | 3 |
| test | 3 |
| integrations | 2 |
| meta | 2 |
| race | 2 |
| team | 2 |
| health | 1 |

Full list: `docs/API_ENDPOINT_INDEX.md`

## Upgrade notes

1. Run `make openapi-frontend` after pulling — commit `openapi/openapi.json` + `schema.ts` if changed.
2. Activity UI: read `sections.zones.metabolic_power` and `sections.zones.coggan_power` separately; show `systems_available` and `coach_note`.
3. Profile zones (`/profile/snapshot` → `zones`) are definitions; ride zones include **time-in-zone** for the session.

## Release gate

```bash
make check
```

## Prior releases

- `docs/RELEASE_NOTES_v5.1.1.md` — frontend stabilization (tests + docs)
- `docs/RELEASE_NOTES_v5.1.0.md` — architectural baseline (router/service/engines)
