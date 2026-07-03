# Changelog

## Unreleased — release cleanup

### Changed

- `engines/io/full_activity_bundle.py` now exposes an explicit `physiology_outputs` section in the canonical post-parse activity bundle.
- The full activity bundle manifest is context-aware: when required signals are present but an expected output is not exposed, the bundle is marked `partial` with a release blocker.
- `make lint` and `make format` now include `engines/`, because the physiology layer is part of the release-quality surface.
- `docs/ARCHITECTURE.md` documents the official activity pipeline and product engineering rules.

### Removed

- Removed duplicate `reports/ENGINE_LOCKDOWN_RUN_SUMMARY.md`; the maintained source is `docs/ENGINE_LOCKDOWN_RUN_SUMMARY.md`.

## [5.2.6] — 2026-06-17

Chart roadmap items: ACWR, readiness, durability, race overlay, Kalman, PMC forecast, dashboard snapshot.

### Added

- 9 new chart types: `acwr_trend`, `monotony_strain`, `readiness_trend`, `durability_fingerprint`, `race_simulation_overlay`, `kalman_trajectory`, `pmc_forecast`, `segment_history`, `eddington_consistency`
- `engines/performance/consistency_engine.py` — Eddington number + segment history aggregation
- `api/chart_schemas.py` — Pydantic `ChartConfigEnvelope` validation on `/meta/chart-config`
- `POST /dashboard/athlete-snapshot` — readiness, load risk, ACWR, twin highlights, chart hints
- `tests/pytest_chart_output_quality.py` — quality gate on all 42 chart types (minimal payload + HTTP + Pydantic)
- `tests/pytest_product_output_quality.py` — product gate on all **134** API paths (`make quality-gate`)
- `tests/pytest_engine_output_quality.py` — engine entry-point product gate (readiness, load, twin, charts, coach)
- `tests/product_quality.py` — shared invariants (finite floats, no null in named lists, semantic validators)
- `docs/RELEASE_NOTES_v5.2.6.md`

### Changed

- API version **5.2.6**; chart catalog **42** types; OpenAPI **134** paths
- Full repo version alignment: `VERSION`, `pyproject.toml`, `.env.example`, README, docs, `openapi/openapi.json`, frontend `client.ts`
- `chart_power_duration_curve` / HR charts no longer emit `null` entries in `series` when optional overlays are omitted
- `tests/pytest_chart_output_quality.py` — quality gate on all 42 chart types (minimal payload + HTTP + Pydantic)
- `ChartSeriesSchema` preserves `data`/`r` fields; activity `_na()` returns `type: unavailable`

## [5.2.5] — 2026-06-30

Wire all chart builders to `/meta/chart-config`; metabolic/W′/fuel partitioning charts.

### Added

- `engines/io/chart_registry.py` — 33 chart types (13 `chart_builder` + 14 `activity_charts` + 6 metabolic/session)
- `GET /meta/chart-types` — catalog with `required_keys` per chart
- `chart_config.v1` schema on metabolic curve outputs (`chart_from_metabolic_curve`)
- `session_fuel_partitioning` chart — CHO vs fat rate (g/min) + cumulative series
- `w_prime_balance`, `vo2_demand`, `lactate` chart types on meta endpoint
- `docs/CHART_CONFIG_CONTRACT.md`

### Changed

- `/meta/chart-config` `chart_type` is an open string validated against registry (was 6-type Literal)

## [5.2.4] — 2026-06-30

TwinState metabolic curves persistence, Mader bimodal contracts, ingest pipeline architecture doc.

### Added

- `engines/twin_state/metabolic_curves_sync.py` — auto-sync `metabolic_curves.v1` and `lactate_state.v1` on twin build/profile refresh
- `docs/METABOLIC_CURVES_TWIN_CONTRACT.md` — frontend/DB contract for VO₂ demand, substrate, lactate curves
- `docs/INGEST_PIPELINE_ARCHITECTURE.md` — S3 → VPS worker → Postgres → coach UI
- `tests/pytest_mader_bimodal_behavior.py` — explicit bimodal MMP + Mader ODE behavior contracts (7 tests)
- `tests/pytest_metabolic_curves_twin_sync.py` — twin curve sync contracts (6 tests)
- `POST /test/in-person` returns `lactate_persistence` bundle when Mader steps present
- `POST /ride/update-profile` returns `metabolic_curves` with refreshed snapshot

### Changed

- `build_twin_state()` auto-populates profile metabolic curves (`skip_metabolic_curves_sync: true` to opt out)
- `POST /twin/state/update-from-ride` accepts `metabolic_snapshot` and `lactate_steps` for curve refresh

## [5.2.3] — 2026-06-29

Coach layer documentation, contract-first testing, fueling INSCYD parity, recovery transparency.

### Added

- **20 coach HTTP endpoints** — full decision-support layer (`docs/COACH_DECISION_ENGINE.md`)
- `docs/CONTRACT_FIRST_TESTING.md` — product-contract test methodology
- `docs/RELEASE_NOTES_v5.2.3.md`
- `tests/pytest_engines_contract_all.py` (179 tests) — all `engines/` packages
- `tests/pytest_contract_full_codebase.py` (75 tests) — API, services, coach HTTP
- `estimated_demands.session_fat_g` on `performance_fueling_targets.v1`
- `recovery_estimation_method` on fueling + recovery curve `estimation_method` / `confidence_tier`

### Changed

- OpenAPI surface **132 paths** (was 106 in 5.2.2 docs) — coach + profile/explainability growth
- `engines/core/metric_contracts.py` — readiness/compliance scale normalization helpers
- Twin ride ingest updates `load_state`; projection uses `chronic_load` when `ctl` missing
- `compute_load_trends([])` → `insufficient_data`
- All documentation aligned to 5.2.3 / 132 paths

### Documentation

- Regenerated `docs/API_ENDPOINT_INDEX.md` from `openapi/openapi.json`
- Updated README, ARCHITECTURE, FRONTEND_DEVELOPER_GUIDE, OPENAPI_FRONTEND, HANDOFF, HARDENING_TESTS
- `docs/STRENGTH_AND_FUELING_CONTRACT.md` — CHO/FAT grams, recovery heuristic, readiness scale

## [5.2.2] — 2026-06-17

Power-series VLamax proxy (cLaMax_P) for metabolic profile.

### Added

- `engines/metabolic/power_vlamax_estimator.py`: sprint power trace → VLamax proxy
  (fixed `T_PCr = 3.5 s`; `t_Ppeak` retained only as protocol-quality metadata;
  oxidative fraction and FFM-normalized work features).
- `POST /profile/vlamax-from-power-series` — standalone estimator endpoint.
- `glycolytic_profile.power_derived_vlamax` and `vlamax_derivation.agreement`
  when `sprint_power` is supplied on `/profile/glycolytic-profile`.

### Semantics

- `estimated_vlamax_mmol_L_s` (Mader/MMP) remains the primary model parameter.
- `power_derived_vlamax` is an explicit power proxy, distinct from blood vLaPeak.
- `t_Ppeak` is **not** used as the glycolytic-window boundary; late mechanical peak
  timing is exposed as a protocol note for coach interpretation.
- `features.t_pcr_s` stays fixed at `3.5`; `features.t_p_peak_s` reports the observed
  mechanical peak timing.

### Documentation

- All docs aligned to **5.2.2** / **106 OpenAPI paths**
- New `docs/RELEASE_NOTES_v5.2.2.md`
- New `docs/VLAMAX_POWER_PROXY_PROTOCOL.md`
- `docs/FRONTEND_DEVELOPER_GUIDE.md` §6.8 power-derived VLamax
- `docs/API_PAYLOAD_EXAMPLES.md` — `/profile/vlamax-from-power-series` examples
