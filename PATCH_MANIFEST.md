# Product analytics — only changed files

This archive contains only the files to add or replace manually in the repository.

Base compared: `Backend-definitivo-V5-main (1).zip`
Source: `Backend-definitivo-V5-product-analytics-v1-sanitized.zip`

## Summary

- Added files: 32
- Modified files: 29
- Deleted files: 0

No cache/build files are included.

## Manual upload steps

1. Create/use branch: `product-analytics-v1`.
2. Unzip this archive.
3. Copy the folders/files over the repository root, preserving paths.
4. Upload/commit all added and replaced files together.
5. Open a PR to `main`.

Suggested PR title:

```text
feat: add product analytics backend engines
```

## Added files

- `api/routers/history.py`
- `api/routers/planning.py`
- `api/routers/readiness.py`
- `api/services/history_service.py`
- `api/services/planning_service.py`
- `api/services/readiness_service.py`
- `docs/PRODUCT_ANALYTICS_BACKEND_V1.md`
- `engines/history/__init__.py`
- `engines/history/athlete_history.py`
- `engines/history/load_trends.py`
- `engines/history/power_curve_history.py`
- `engines/integrations/__init__.py`
- `engines/integrations/activity_normalizer.py`
- `engines/io/activity_intelligence.py`
- `engines/io/data_quality_report.py`
- `engines/performance/ability_profile.py`
- `engines/performance/breakthrough_detector.py`
- `engines/planning/__init__.py`
- `engines/planning/plan_adapter.py`
- `engines/planning/season_planner.py`
- `engines/readiness/__init__.py`
- `engines/readiness/readiness_engine.py`
- `engines/routes/__init__.py`
- `engines/routes/segment_engine.py`
- `engines/workouts/adaptive_planner.py`
- `engines/workouts/exporters/__init__.py`
- `engines/workouts/exporters/erg.py`
- `engines/workouts/exporters/mrc.py`
- `engines/workouts/exporters/zwo.py`
- `engines/workouts/progression_levels.py`
- `engines/workouts/recommendation_engine.py`
- `tests/pytest_product_engines_v1.py`

## Modified files

- `CONTRATTO_JSON_test.md`
- `DEVELOPMENT_TEAM_HANDOFF.md`
- `api/app.py`
- `api/deps.py`
- `api/routers/performance.py`
- `api/routers/ride.py`
- `api/routers/workouts.py`
- `api/schemas.py`
- `api/services/__init__.py`
- `api/services/performance_service.py`
- `api/services/ride_service.py`
- `api/services/workout_service.py`
- `docs/API_EXAMPLES.md`
- `docs/FRONTEND_DEVELOPER_GUIDE.md`
- `docs/WORKOUT_SYSTEM_BACKEND_V1.md`
- `docs/workout_db_schema_v1.sql`
- `engines/adaptive_load/trend.py`
- `engines/io/activity_charts.py`
- `engines/io/fit_parser.py`
- `engines/io/power_source_normalizer.py`
- `engines/metabolic/metabolic_profiler.py`
- `frontend/src/api/client.ts`
- `openapi/openapi.json`
- `pyproject.toml`
- `streamlit_frontend/app.py`
- `tests/pytest_backend_implementations.py`
- `tests/pytest_frontend_client_contract.py`
- `tests/pytest_openapi_contract.py`
- `tests/pytest_service_layer.py`

## Deleted files

- None

## Validation already run on the full sanitized package

```text
compileall api/ engines/     PASS
ruff                         PASS
mypy                         PASS
pytest tests/pytest_*.py      PASS — 111 passed, 6 skipped
product engine tests          PASS — 5 passed
stress simulation             PASS — 720 requests, 0 errors
```
