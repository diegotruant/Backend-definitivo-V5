# Product Analytics Backend V1

This increment adds neutral, non-proprietary backend modules to transform the physiological engine into a more complete product platform.

## Naming rule

No endpoint, document, payload, or comment introduced in this increment uses external platform names or project commercial names. All names are descriptive and generic.

## New backend blocks

| Area | Modules | Main endpoints |
|------|--------|---------------------|
| Activity intelligence | `engines/io/activity_intelligence.py`, `engines/io/data_quality_report.py` | `/ride/intelligence`, `/ride/data-quality` |
| Athlete history | `engines/history/` | `/history/summary`, `/history/power-curve`, `/history/records`, `/history/load` |
| Readiness and load risk | `engines/readiness/` | `/readiness/today`, `/load/state/update`, `/load/risk` |
| Ability and breakthrough | `engines/performance/ability_profile.py`, `breakthrough_detector.py` | `/performance/ability-profile`, `/performance/breakthroughs` |
| Workout intelligence | `engines/workouts/recommendation_engine.py`, `progression_levels.py`, `adaptive_planner.py` | `/workouts/recommend`, `/workouts/progression-levels`, `/workouts/adapt-plan` |
| Workout export | `engines/workouts/exporters/` | `/workouts/export` |
| Planning | `engines/planning/` | `/planning/create-season-plan`, `/planning/adapt-week`, `/planning/check-load-risk` |
| Route/segment utilities | `engines/routes/` | `/ride/analytics/segments/*` |
| Integrations | `engines/integrations/` | `/integrations/activity/normalize`, deduplicate |
| Coach decision layer | `engines/coach/*`, `engines/nutrition/*` | 20× `/coach/*` — `docs/COACH_DECISION_ENGINE.md` |

## Architectural principle

The backend remains stateless:

1. The frontend or database persists activities, TwinState, curves, calendar, and history.
2. The backend receives JSON or FIT payloads.
3. The backend returns computed canonical envelopes.
4. The frontend renders without recreating the calculations.

## New high-value outputs

- best efforts for common durations
- power and heart-rate zone distribution
- auto interval detection
- chart series downsampled
- data-quality score and signal coverage
- multi-period power-curve history
- personal records
- load trends acute/chronic/balance
- non-medical readiness score
- ability profile by performance areas
- breakthrough detection on power curve
- workout recommendation
- progression levels
- adaptive plan adjustment
- structured workout text export
- season plan rule-based
- planned load risk check

## Validation performed

Current gate (V5.2.6):

- `python scripts/export_openapi.py` → **135 paths**
- `python scripts/check_openapi_consistency.py` → OpenAPI, operational docs, API index and generated TypeScript inventory checked
- `pytest tests/pytest_engines_contract_all.py tests/pytest_contract_full_codebase.py` → contract suite
- `make test-all` → full repository suite
- `pytest tests/pytest_frontend_client_contract.py` — frontend contract check; `/ride/full-bundle` codegen follow-up tracked in issue #14

Original V1 increment validation:

- `python -m compileall -q api engines`
- `python -m pytest -q tests/pytest_product_engines_v1.py` → 5 passed