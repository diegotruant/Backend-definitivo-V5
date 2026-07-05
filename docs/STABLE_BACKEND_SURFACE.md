# Stable Backend Surface — Digital Twin Backend V5.2.6

**Repository:** `diegotruant/Backend-definitivo-V5`  
**OpenAPI version:** 5.2.6  
**HTTP paths in contract:** 135  
**Chart types:** 43  

This document is **governance only**. It does not change runtime behaviour, OpenAPI, tests, or CI. It tells frontend, mobile, and Supabase teams which endpoints are official product surface versus experimental plumbing.

Canonical machine-readable inventory: `openapi/openapi.json` and `docs/API_ENDPOINT_INDEX.md`.

---

## 1. Why this document exists

The backend exposes **135 HTTP paths**. Most are real and tested, but not all belong in the **MVP product contract**.

Without a stability map, integrators tend to:

- wire every path listed in OpenAPI as if it were equally “production”;
- bypass the official ride pipeline (`/ride/full-bundle`) and re-orchestrate engines in the client;
- persist experimental JSON shapes in Supabase before they are manifest-stable;
- show model-tier metrics without the required `tier` / `status` / `warnings` UX.

This document reduces that noise by labelling every path with one of five tiers and binding four **official MVP flows**.

---

## 2. Stability tiers

| Tier | Meaning for integrators | Contract expectation |
|------|----------------------|----------------------|
| **STABLE** | Use in production MVP. Breaking changes require version bump + migration note. | Covered by product output quality tests; preferred entry point for the flow. |
| **STABLE-CANDIDATE** | Works and tested; promote to STABLE after one release cycle in a pilot screen. | Safe to integrate behind a feature flag; monitor manifest / tier fields. |
| **ADVANCED** | Real capability for power users or secondary screens. Not required for MVP. | May evolve; prefer bundle outputs when equivalent exists. |
| **LABS** | Scientific / phenotype / validation experiments. Never default product UI. | Outputs may change; always show `tier`, `confidence`, limitations. |
| **INTERNAL** | Debugging, orchestration introspection, ops. Not for end-user features. | No backward-compat promise; may move or be removed. |

**Rule:** if an endpoint is not **STABLE** or **STABLE-CANDIDATE**, do not store its payload as a required column in Supabase or show it as a headline coach metric without explicit tier UX.

---

## 3. Official MVP flows (only these four)

Integrations should implement these sequences first. Everything else is optional depth.

### Flow A — Athlete onboarding

```text
POST /profile/snapshot          → metabolic_snapshot (persist in Supabase)
POST /test/propose              → optional FIT test structure (tablet / upload)
POST /test/confirm              → confirmed snapshot
POST /twin/state/build          → twin_state.v1 (persist)
POST /twin/state/validate       → schema check before save
```

### Flow B — Daily activity (canonical ride pipeline)

```text
POST /ride/ingest               → power curve update + parse quality
POST /ride/full-bundle          → full post-parse bundle + engine_manifest
POST /twin/state/update-from-ride
POST /ride/update-profile       → only if bundle signals profile_should_refresh
```

**Do not** rebuild Flow B by chaining `/ride/summary` + many `/ride/analytics/*` calls unless you have a documented reason. The bundle is the single orchestration contract (`engines/io/full_activity_bundle.py`).

### Flow C — Workout prescription & compliance

```text
POST /workouts/validate
POST /workouts/prescribe
POST /workouts/feasibility
POST /workouts/export           → erg | mrc | zwo
… athlete completes ride …
POST /workouts/compare
POST /workouts/calendar/transition
```

Workout library metadata (`is_system_template`, citations) lives in **Supabase**, not in the backend.

### Flow D — Lactate validation → team learning

```text
POST /lab/lactate/validate-model   → includes validation_event
POST /team/calibration/update      → events[] + team calibration_model
POST /team/calibration/apply       → corrected snapshot for display
```

---

## 4. Summary by tier

| Tier | Paths | % of 135 |
|------|------:|---------:|
| STABLE | 24 | 18% |
| STABLE-CANDIDATE | 18 | 13% |
| ADVANCED | 74 | 55% |
| LABS | 14 | 10% |
| INTERNAL | 5 | 4% |

**MVP integrator focus:** 42 paths (STABLE + STABLE-CANDIDATE) cover all four flows above.

---

## 5. STABLE (24 paths)

Production MVP surface. Prefer these names in `frontend/src/api/client.ts`.

| Method | Path | operationId | MVP flow |
|--------|------|-------------|----------|
| GET | `/health` | `healthCheck` | ops |
| POST | `/ride/ingest` | `rideIngest` | B |
| POST | `/ride/full-bundle` | `rideFullBundle` | B |
| POST | `/ride/summary` | `rideSummary` | B (compat narrow) |
| POST | `/ride/update-profile` | `rideUpdateProfile` | B |
| POST | `/profile/snapshot` | `profileSnapshot` | A |
| POST | `/test/propose` | `testPropose` | A |
| POST | `/test/confirm` | `testConfirm` | A |
| POST | `/twin/state/build` | `twinStateBuild` | A |
| POST | `/twin/state/update-from-ride` | `twinStateUpdateFromRide` | B |
| POST | `/twin/state/validate` | `twinStateValidate` | A |
| POST | `/workouts/validate` | `workoutsValidate` | C |
| POST | `/workouts/prescribe` | `workoutsPrescribe` | C |
| POST | `/workouts/feasibility` | `workoutsFeasibility` | C |
| POST | `/workouts/compare` | `workoutsCompare` | C |
| POST | `/workouts/export` | `workoutsExport` | C |
| POST | `/workouts/calendar/transition` | `workoutsCalendarTransition` | C |
| POST | `/lab/lactate/validate-model` | `labLactateValidateModel` | D |
| POST | `/team/calibration/update` | `teamCalibrationUpdate` | D |
| POST | `/team/calibration/apply` | `teamCalibrationApply` | D |
| GET | `/meta/chart-types` | `metaChartTypes` | charts |
| POST | `/meta/chart-config` | `metaChartConfig` | charts |
| GET | `/meta/engine-tiers` | `metaEngineTiers` | tier UX |
| POST | `/readiness/today` | `readinessToday` | athlete home |

---

## 6. STABLE-CANDIDATE (18 paths)

Pilot-ready; promote after one release on a real screen.

| Method | Path | operationId | Notes |
|--------|------|-------------|-------|
| POST | `/ride/parse` | `rideParse` | Prefer ingest/full-bundle for product |
| POST | `/ride/data-quality` | `rideDataQuality` | Subset of bundle `data_quality_report` |
| POST | `/ride/intelligence` | `rideIntelligence` | Subset of bundle `activity_intelligence` |
| POST | `/dashboard/athlete-snapshot` | `dashboardAthleteSnapshot` | Command center aggregate |
| POST | `/coach/daily-brief` | `coachDailyBrief` | Coach home |
| POST | `/coach/session-decision` | `coachSessionDecision` | Pre-session gate |
| POST | `/coach/decision-safety` | `coachDecisionSafety` | Safety layer |
| POST | `/coach/nutrition/performance-targets` | `coachNutritionPerformanceTargets` | Fueling targets |
| POST | `/profile/metabolic/curves` | `profileMetabolicCurves` | Twin metabolic curves |
| POST | `/profile/training-load/ctl-atl-tsb` | `profileCtlAtlTsb` | Load triad |
| POST | `/twin/state/project` | `twinStateProject` | Season projection input |
| POST | `/projection/season` | `projectionSeason` | What-if season |
| POST | `/load/manual` | `loadManual` | Non-cycling stress bridge |
| POST | `/load/acwr` | `loadAcwr` | Acute:chronic ratio |
| POST | `/explainability/workout-summary-narrative` | `explainabilityWorkoutSummaryNarrative` | Coach copy |
| POST | `/explainability/metric-narrative` | `explainabilityMetricNarrative` | Metric copy |
| POST | `/workouts/progression-levels` | `workoutsProgressionLevels` | Library intelligence |
| POST | `/workouts/recommend` | `workoutsRecommend` | Library suggestions |

---

## 7. ADVANCED (74 paths)

Real engines, secondary screens, or granular analytics. When the same output exists inside `/ride/full-bundle`, **read it from the bundle** instead of calling these directly.

### ride — analytics (25)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/ride/analytics/adaptive-load` | `rideAnalyticsAdaptiveLoad` |
| POST | `/ride/analytics/cardiac` | `rideAnalyticsCardiac` |
| POST | `/ride/analytics/critical-power/fit` | `rideAnalyticsCriticalPowerFit` |
| POST | `/ride/analytics/durability/hourly-decay` | `rideAnalyticsHourlyDecay` |
| POST | `/ride/analytics/durability/index` | `rideAnalyticsDurabilityIndex` |
| POST | `/ride/analytics/durability/np-drift` | `rideAnalyticsNpDrift` |
| POST | `/ride/analytics/durability/prescription` | `rideAnalyticsDurabilityPrescription` |
| POST | `/ride/analytics/durability/tte-sustainability` | `rideAnalyticsTteSustainability` |
| POST | `/ride/analytics/efforts` | `rideAnalyticsEfforts` |
| POST | `/ride/analytics/hrv` | `rideAnalyticsHrv` |
| POST | `/ride/analytics/metabolic-flexibility` | `rideAnalyticsMetabolicFlexibility` |
| POST | `/ride/analytics/pedaling-balance` | `rideAnalyticsPedalingBalance` |
| POST | `/ride/analytics/power` | `rideAnalyticsPower` |
| POST | `/ride/analytics/resilience` | `rideAnalyticsResilience` |
| POST | `/ride/analytics/segments/climbs` | `rideAnalyticsClimbSegments` |
| POST | `/ride/analytics/segments/compare` | `rideAnalyticsCompareSegments` |
| POST | `/ride/analytics/session/classify` | `rideAnalyticsSessionClassify` |
| POST | `/ride/analytics/session/protocol-completeness` | `rideAnalyticsProtocolCompleteness` |
| POST | `/ride/analytics/statistics` | `rideAnalyticsStatistics` |
| POST | `/ride/analytics/thermal/acclimation` | `rideAnalyticsThermalAcclimation` |
| POST | `/ride/analytics/thermal/session` | `rideAnalyticsThermalSession` |
| POST | `/ride/analytics/w-prime/balance` | `rideAnalyticsWPrimeBalance` |
| POST | `/ride/analytics/zones` | `rideAnalyticsZones` |
| POST | `/ride/durability` | `rideDurability` |

### coach — extended (16)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/coach/adherence` | `coachAdherence` |
| POST | `/coach/attention` | `coachAttention` |
| POST | `/coach/attention/roster` | `coachRosterAttention` |
| POST | `/coach/checkin` | `coachCheckin` |
| POST | `/coach/communication-draft` | `coachCommunicationDraft` |
| POST | `/coach/constraints` | `coachConstraints` |
| POST | `/coach/endocrine-context` | `coachEndocrineContext` |
| POST | `/coach/environment-adjustment` | `coachEnvironmentAdjustment` |
| POST | `/coach/equipment-comfort` | `coachEquipmentComfort` |
| POST | `/coach/female-athlete-context` | `coachFemaleAthleteContext` |
| POST | `/coach/periodization` | `coachPeriodization` |
| POST | `/coach/pnei-context` | `coachPneiContext` |
| POST | `/coach/race-execution` | `coachRaceExecution` |
| POST | `/coach/strength/prescription` | `coachStrengthPrescription` |
| POST | `/coach/testing-plan` | `coachTestingPlan` |
| POST | `/coach/training-safety` | `coachTrainingSafety` |

### profile — extended (11)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/profile/cross-validate` | `profileCrossValidate` |
| POST | `/profile/detraining/apply` | `profileDetrainingApply` |
| POST | `/profile/fatmax/compare` | `profileFatmaxCompare` |
| POST | `/profile/fatmax/report` | `profileFatmaxReport` |
| POST | `/profile/glycolytic-profile` | `profileGlycolyticProfile` |
| POST | `/profile/metabolic/current` | `profileMetabolicCurrent` |
| POST | `/profile/mmp-quality` | `profileMmpQuality` |
| POST | `/profile/vlamax-from-power-series` | `profileVlamaxFromPowerSeries` |
| POST | `/profile/w-prime/tau` | `profileWPrimeTau` |

### workouts, load, history, planning, performance, explainability, race, twin

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/workouts/adapt-plan` | `workoutsAdaptPlan` |
| POST | `/load/monotony-strain` | `loadMonotonyStrain` |
| POST | `/load/risk` | `loadRisk` |
| POST | `/load/state/update` | `loadStateUpdate` |
| POST | `/load/adaptive/recommendation` | `loadAdaptiveRecommendation` |
| POST | `/load/adaptive/trend` | `loadAdaptiveTrend` |
| POST | `/history/load` | `historyLoad` |
| POST | `/history/power-curve` | `historyPowerCurve` |
| POST | `/history/records` | `historyRecords` |
| POST | `/history/summary` | `historySummary` |
| POST | `/planning/adapt-week` | `planningAdaptWeek` |
| POST | `/planning/check-load-risk` | `planningCheckLoadRisk` |
| POST | `/planning/create-season-plan` | `planningCreateSeasonPlan` |
| POST | `/performance/ability-profile` | `performanceAbilityProfile` |
| POST | `/performance/breakthroughs` | `performanceBreakthroughs` |
| POST | `/performance/neuromuscular-profile` | `performanceNeuromuscularProfile` |
| POST | `/power-source/normalize` | `powerSourceNormalize` |
| POST | `/explainability/acwr-narrative` | `explainabilityAcwrNarrative` |
| POST | `/explainability/durability-confidence` | `explainabilityDurabilityConfidence` |
| POST | `/explainability/durability-narrative` | `explainabilityDurabilityNarrative` |
| POST | `/explainability/fatmax-confidence` | `explainabilityFatmaxConfidence` |
| POST | `/explainability/fatmax-narrative` | `explainabilityFatmaxNarrative` |
| POST | `/explainability/vo2max-confidence` | `explainabilityVo2Confidence` |
| POST | `/race/gpx/analyze` | `raceGpxAnalyze` |
| POST | `/race/gpx/simulate` | `raceGpxSimulate` |
| POST | `/twin/state/update-from-workout-result` | `twinStateUpdateFromWorkout` |

---

## 8. LABS (14 paths)

Scientific validation, phenotype branches, in-person lab tooling. Use only in lab / research screens with full tier disclosure.

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/profile/snapshot/auto` | `profileSnapshotAuto` |
| POST | `/profile/snapshot/bayesian` | `profileSnapshotBayesian` |
| POST | `/profile/snapshot/phenotype` | `profileSnapshotPhenotype` |
| POST | `/profile/snapshot/segmented` | `profileSnapshotSegmented` |
| POST | `/profile/kalman/trajectory` | `profileKalmanTrajectory` |
| POST | `/profile/fatmax/lab` | `profileFatmaxLab` |
| POST | `/profile/vlamax-from-sprint` | `profileVlamaxFromSprint` |
| POST | `/test/in-person` | `testInPerson` |
| POST | `/lab/create-result` | `labCreateResult` |
| POST | `/lab/lactate/thresholds` | `labLactateThresholds` |
| POST | `/lab/parse-text` | `labParseText` |
| POST | `/lab/validate-result` | `labValidateResult` |
| POST | `/lab/vlapeak/observed` | `labVlapeakObserved` |
| POST | `/lab/vlapeak/validate` | `labVlapeakValidate` |

*Note:* `POST /lab/lactate/validate-model` is **STABLE** (Flow D) because it is the production path from lactate steps to `validation_event`.

---

## 9. INTERNAL (9 paths)

Orchestration debugging, normalisation plumbing, session-router introspection. **Not** for product UI.

| Method | Path | operationId | Purpose |
|--------|------|-------------|---------|
| POST | `/ride/analytics/session/route-decide` | `rideAnalyticsSessionRouteDecide` | Session router decision only |
| POST | `/ride/analytics/session/route-run` | `rideAnalyticsSessionRouteRun` | Session router execution only |
| POST | `/integrations/activities/deduplicate` | `integrationsDeduplicateActivities` | Ingest normalisation |
| POST | `/integrations/activity/normalize` | `integrationsNormalizeActivity` | Ingest normalisation |

*Counts: 24 + 18 + 74 + 14 + 5 = 135 paths.*

---

## 10. Supabase persistence map (MVP)

Store only STABLE-flow payloads as required relational data. Treat ADVANCED/LABS as optional JSON blobs.

| Supabase table / blob | Source endpoint | Required for MVP |
|-----------------------|-----------------|------------------|
| `athletes.metabolic_snapshot` | `/profile/snapshot` | yes |
| `athletes.twin_state` | `/twin/state/build`, `/twin/state/update-from-ride` | yes |
| `athletes.power_curve` | `/ride/ingest` | yes |
| `activities.bundle` | `/ride/full-bundle` | yes (whole JSON or selected sections) |
| `workout_assignments.prescription` | `/workouts/prescribe` | yes |
| `workout_assignments.compliance` | `/workouts/compare` | yes |
| `validation_events.event` | `/lab/lactate/validate-model` → `validation_event` | yes when lab used |
| `teams.calibration_model` | `/team/calibration/update` | yes when lab used |

Do **not** require columns sourced only from INTERNAL or LABS endpoints.

---

## 11. Bundle-first rule (ride domain)

`POST /ride/full-bundle` returns:

- `parse_report`, `data_quality_report`
- `workout_summary`, `activity_intelligence`, `activity_charts`
- `physiology_outputs`, `engine_manifest`, `manifest_summary`
- durability / pedaling / metabolic flexibility side outputs when signals allow

Before adding a new `/ride/analytics/*` call to the frontend, check whether the field is already exposed in the bundle manifest. If `engine_manifest` reports `skipped` or `partial`, show “insufficient data” — do not call the granular endpoint hoping for a different answer.

---

## 12. Tier UX (non-negotiable)

Every STABLE and STABLE-CANDIDATE response that includes modelled physiology must surface:

- `tier` or `confidence_tier` (`LAB`, `MODEL`, `ESTIMATE`, `INSUFFICIENT_DATA`)
- `status` when an engine cannot run (`success`, `skipped`, `partial`, `error`)
- `warnings[]` on ride summaries when schedules adapt (e.g. two-phase HRV)

Reference: `docs/DEVELOPER_ONBOARDING.md` § Principi non negoziabili.

---

## 13. Promotion policy

| From | To | Requirement |
|------|-----|-------------|
| STABLE-CANDIDATE | STABLE | Used in production UI one release; contract tests green; no open manifest blockers |
| ADVANCED | STABLE-CANDIDATE | Documented in a product flow; payload shape frozen in `pytest_product_output_quality.py` |
| LABS | ADVANCED | Scientific disclaimer reviewed; not the only source for a headline metric |
| INTERNAL | any product tier | **Forbidden** without new orchestration path and docs update |

Changes to this file do not change OpenAPI. When a path is promoted, update this document in the same PR that updates product docs (`API_ENDPOINT_INDEX.md`, onboarding).

---

## 14. Related documents

| Document | Role |
|----------|------|
| `docs/API_ENDPOINT_INDEX.md` | Full path list (machine companion) |
| `docs/DEVELOPER_ONBOARDING.md` | Day-1 flows for new developers |
| `docs/ENGINE_ORCHESTRATION_AUDIT.md` | How engines are wired |
| `docs/FRONTEND_DEVELOPER_GUIDE.md` | TwinState and page-level API usage |
| `docs/CONTRACT_FIRST_TESTING.md` | How stability is enforced in CI |
| `openapi/openapi.json` | Committed HTTP contract (135 paths) |

---

## 15. Changelog

| Date | Version | Change |
|------|---------|--------|
| 2026-07-05 | 1.0.0 | Initial stable surface map for V5.2.6 (135 paths, 43 charts) |

---

*Governance document only — no runtime, OpenAPI, test, or workflow changes.*
