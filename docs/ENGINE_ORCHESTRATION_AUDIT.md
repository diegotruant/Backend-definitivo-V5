# Engine orchestration audit — V5.2.6

Audit of how physiological engines are wired from HTTP through services into release contracts. Goal: every product-facing output has a single official orchestration path and is visible in tests or manifests.

**Live codebase:** 135 OpenAPI paths, 43 chart types.

## Layering (verified)

| Layer | Location | Orchestration role |
|-------|----------|-------------------|
| HTTP | `api/routers/` | Parse multipart/JSON, map errors, no engine logic |
| Application | `api/services/` | Use-case orchestration, athlete context, `ServiceError` |
| Domain | `engines/` | Algorithms, tiers, scientific contracts |

Rule: routers never import scipy or call deep engine helpers directly.

## Activity pipeline (official)

Canonical per-ride orchestration lives in `engines/io/full_activity_bundle.py` and is exposed at **`POST /ride/full-bundle`**.

```text
parse_report
  → data_quality_report
  → workout_summary          (engines/io/workout_summary.py)
  → activity_intelligence    (engines/io/activity_intelligence.py)
  → activity_charts          (engines/io/activity_charts.py + chart_registry)
  → durability / pedaling / metabolic flexibility side outputs
  → engine_manifest          (per-engine status + release_blocker flags)
```

`/ride/summary` calls `build_workout_summary` only — narrower compatibility surface.

### Manifest expectations

`EXPECTATIONS` in `full_activity_bundle.py` maps required signals to output paths. When a required signal is present but output is missing, manifest rows are marked `partial` with `attention: release_blocker`. This prevents silent omission of physiology sections on production rides.

## Chart orchestration

| Entry | Module | Count |
|-------|--------|------:|
| `GET /meta/chart-types` | `engines/io/chart_registry.py` | 43 |
| `POST /meta/chart-config` | `chart_registry` → `chart_builder` / `activity_charts` | 43 |

Activity stream charts (`activity_*`) require 1 Hz `power[]` in payload; 14 types are registered (elevation, speed, power, HR, cadence, respiration, ambient temp, L/R balance, position, power phase, platform offset, time-in-zone, time-in-intensity, thermal).

Profile/session/load charts route through `chart_builder.py` with explicit `required_keys` validation in `api/chart_schemas.py`.

## Workout orchestration

Workout HTTP flows are orchestrated by `api/services/workout_service.py`:

| Endpoint | Engine entry |
|----------|--------------|
| `POST /workouts/validate` | `validate_workout_payload` |
| `POST /workouts/prescribe` | `materialize_workout` |
| `POST /workouts/feasibility` | `analyze_workout_feasibility` |
| `POST /workouts/compare` | `compare_workout_to_activity` |
| `POST /workouts/export` | `exporters/{erg,mrc,zwo}.py` |
| `POST /workouts/recommend` | `recommendation_engine` |
| `POST /workouts/progression-levels` | `progression_levels` |
| `POST /workouts/adapt-plan` | `adaptive_planner` |
| `POST /workouts/calendar/transition` | `calendar_engine` |

**Workout library layout:** validation, normalization, and athlete-specific prescription materialization are consolidated in **`engines/workouts/models.py`** (`validate_workout_payload`, `materialize_workout`). There is no separate `template_engine` module — prescription targets (%CP, %FTP, absolute watts) resolve inside `WorkoutStep.power_range()` and `materialize_workout()`.

Supporting modules:

```text
engines/workouts/
├── models.py
├── feasibility_engine.py
├── compliance_engine.py
├── calendar_engine.py
├── recommendation_engine.py
├── progression_levels.py
├── adaptive_planner.py
└── exporters/
```

## Coach orchestration

Coach endpoints delegate to `engines/coach/*` and `engines/nutrition/*` via `api/services/coach_service.py` (and related). High-level workflows (`daily-brief`, `session-decision`) use `engines/coach/coach_orchestrator.py` to sequence sub-engines without duplicating business rules in routers.

## Profile / twin orchestration

| Flow | Service | Engines |
|------|---------|---------|
| Metabolic snapshot | `profile_service` | `metabolic_profiler`, zones |
| Kalman / bayesian | `profile_extended_service` | kalman, bayesian snapshot |
| Twin build/update | `twin_service` | `twin_state/*`, metabolic curve sync |
| Season projection | `twin_service` / planning | `projection/season` |

Metabolic curves on twin: `docs/METABOLIC_CURVES_TWIN_CONTRACT.md`.

## Gaps and follow-ups

| Area | Status | Notes |
|------|--------|-------|
| Activity bundle | ✅ Official | Prefer `/ride/full-bundle` for new integrations |
| Workout outdoor compare | ⚠️ V1 sequential | V2 dynamic interval matching planned |
| Coach orchestrator | ✅ Wired | 20 `/coach/*` paths with contract tests |
| Chart registry | ✅ Complete | 43 types with product quality gate |
| Legacy flat imports | ⚠️ Deprecated | `import fit_parser` → use `engines.io.fit_parser` |

## Test coverage for orchestration

| Suite | What it guards |
|-------|----------------|
| `pytest_full_activity_bundle_contract.py` | Bundle schema, manifest rows, physiology exposure |
| `pytest_workout_pipeline_perfection.py` | validate → prescribe → feasibility → compare |
| `pytest_product_output_quality.py` | All 135 API paths return safe JSON |
| `pytest_chart_output_quality.py` | All 43 chart types plottable |
| `pytest_engines_contract_all.py` | Engine package import health + scale semantics |

## Recommendation

1. New ride/report features → extend `full_activity_bundle.py` + manifest `EXPECTATIONS`, then expose via `/ride/full-bundle`.
2. New workout steps → extend `models.py` validation first; keep HTTP thin in `workout_service.py`.
3. New charts → register in `chart_registry.py`, add quality-gate fixture in `pytest_chart_output_quality.py`.

---

*Audit snapshot V5.2.6 — aligned with 135 OpenAPI paths and 43 chart types.*
