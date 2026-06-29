# API endpoint index — Digital Twin API 5.2.3

Canonical inventory of **132 HTTP paths** from `openapi/openapi.json`.
Regenerate after API changes: `make openapi-frontend`.

| Tag | Paths |
|-----|------:|
| ride | 32 |
| coach | 20 |
| profile | 19 |
| workouts | 9 |
| explainability | 8 |
| lab | 7 |
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

## Full list by tag

### ride (32)

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
| POST | `/ride/analytics/session/route-decide` | `rideAnalyticsSessionRouteDecide` |
| POST | `/ride/analytics/session/route-run` | `rideAnalyticsSessionRouteRun` |
| POST | `/ride/analytics/statistics` | `rideAnalyticsStatistics` |
| POST | `/ride/analytics/thermal/acclimation` | `rideAnalyticsThermalAcclimation` |
| POST | `/ride/analytics/thermal/session` | `rideAnalyticsThermalSession` |
| POST | `/ride/analytics/w-prime/balance` | `rideAnalyticsWPrimeBalance` |
| POST | `/ride/analytics/zones` | `rideAnalyticsZones` |
| POST | `/ride/data-quality` | `rideDataQuality` |
| POST | `/ride/durability` | `rideDurability` |
| POST | `/ride/ingest` | `rideIngest` |
| POST | `/ride/intelligence` | `rideIntelligence` |
| POST | `/ride/parse` | `rideParse` |
| POST | `/ride/summary` | `rideSummary` |
| POST | `/ride/update-profile` | `rideUpdateProfile` |

### coach (20)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/coach/adherence` | `coachAdherence` |
| POST | `/coach/attention` | `coachAttention` |
| POST | `/coach/attention/roster` | `coachRosterAttention` |
| POST | `/coach/checkin` | `coachCheckin` |
| POST | `/coach/communication-draft` | `coachCommunicationDraft` |
| POST | `/coach/constraints` | `coachConstraints` |
| POST | `/coach/daily-brief` | `coachDailyBrief` |
| POST | `/coach/decision-safety` | `coachDecisionSafety` |
| POST | `/coach/endocrine-context` | `coachEndocrineContext` |
| POST | `/coach/environment-adjustment` | `coachEnvironmentAdjustment` |
| POST | `/coach/equipment-comfort` | `coachEquipmentComfort` |
| POST | `/coach/female-athlete-context` | `coachFemaleAthleteContext` |
| POST | `/coach/nutrition/performance-targets` | `coachNutritionPerformanceTargets` |
| POST | `/coach/periodization` | `coachPeriodization` |
| POST | `/coach/pnei-context` | `coachPneiContext` |
| POST | `/coach/race-execution` | `coachRaceExecution` |
| POST | `/coach/session-decision` | `coachSessionDecision` |
| POST | `/coach/strength/prescription` | `coachStrengthPrescription` |
| POST | `/coach/testing-plan` | `coachTestingPlan` |
| POST | `/coach/training-safety` | `coachTrainingSafety` |

### profile (19)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/profile/cross-validate` | `profileCrossValidate` |
| POST | `/profile/detraining/apply` | `profileDetrainingApply` |
| POST | `/profile/fatmax/compare` | `profileFatmaxCompare` |
| POST | `/profile/fatmax/lab` | `profileFatmaxLab` |
| POST | `/profile/fatmax/report` | `profileFatmaxReport` |
| POST | `/profile/glycolytic-profile` | `profileGlycolyticProfile` |
| POST | `/profile/kalman/trajectory` | `profileKalmanTrajectory` |
| POST | `/profile/metabolic/current` | `profileMetabolicCurrent` |
| POST | `/profile/metabolic/curves` | `profileMetabolicCurves` |
| POST | `/profile/mmp-quality` | `profileMmpQuality` |
| POST | `/profile/snapshot` | `profileSnapshot` |
| POST | `/profile/snapshot/auto` | `profileSnapshotAuto` |
| POST | `/profile/snapshot/bayesian` | `profileSnapshotBayesian` |
| POST | `/profile/snapshot/phenotype` | `profileSnapshotPhenotype` |
| POST | `/profile/snapshot/segmented` | `profileSnapshotSegmented` |
| POST | `/profile/training-load/ctl-atl-tsb` | `profileCtlAtlTsb` |
| POST | `/profile/vlamax-from-power-series` | `profileVlamaxFromPowerSeries` |
| POST | `/profile/vlamax-from-sprint` | `profileVlamaxFromSprint` |
| POST | `/profile/w-prime/tau` | `profileWPrimeTau` |

### workouts (9)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/workouts/adapt-plan` | `workoutsAdaptPlan` |
| POST | `/workouts/calendar/transition` | `workoutsCalendarTransition` |
| POST | `/workouts/compare` | `workoutsCompare` |
| POST | `/workouts/export` | `workoutsExport` |
| POST | `/workouts/feasibility` | `workoutsFeasibility` |
| POST | `/workouts/prescribe` | `workoutsPrescribe` |
| POST | `/workouts/progression-levels` | `workoutsProgressionLevels` |
| POST | `/workouts/recommend` | `workoutsRecommend` |
| POST | `/workouts/validate` | `workoutsValidate` |

### explainability (8)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/explainability/acwr-narrative` | `explainabilityAcwrNarrative` |
| POST | `/explainability/durability-confidence` | `explainabilityDurabilityConfidence` |
| POST | `/explainability/durability-narrative` | `explainabilityDurabilityNarrative` |
| POST | `/explainability/fatmax-confidence` | `explainabilityFatmaxConfidence` |
| POST | `/explainability/fatmax-narrative` | `explainabilityFatmaxNarrative` |
| POST | `/explainability/metric-narrative` | `explainabilityMetricNarrative` |
| POST | `/explainability/vo2max-confidence` | `explainabilityVo2Confidence` |
| POST | `/explainability/workout-summary-narrative` | `explainabilityWorkoutSummaryNarrative` |

### lab (7)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/lab/create-result` | `labCreateResult` |
| POST | `/lab/lactate/thresholds` | `labLactateThresholds` |
| POST | `/lab/lactate/validate-model` | `labLactateValidateModel` |
| POST | `/lab/parse-text` | `labParseText` |
| POST | `/lab/validate-result` | `labValidateResult` |
| POST | `/lab/vlapeak/observed` | `labVlapeakObserved` |
| POST | `/lab/vlapeak/validate` | `labVlapeakValidate` |

### twin (6)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/projection/season` | `projectionSeason` |
| POST | `/twin/state/build` | `twinStateBuild` |
| POST | `/twin/state/project` | `twinStateProject` |
| POST | `/twin/state/update-from-ride` | `twinStateUpdateFromRide` |
| POST | `/twin/state/update-from-workout-result` | `twinStateUpdateFromWorkout` |
| POST | `/twin/state/validate` | `twinStateValidate` |

### load (5)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/load/acwr` | `loadAcwr` |
| POST | `/load/adaptive/recommendation` | `loadAdaptiveRecommendation` |
| POST | `/load/adaptive/trend` | `loadAdaptiveTrend` |
| POST | `/load/manual` | `loadManual` |
| POST | `/load/monotony-strain` | `loadMonotonyStrain` |

### history (4)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/history/load` | `historyLoad` |
| POST | `/history/power-curve` | `historyPowerCurve` |
| POST | `/history/records` | `historyRecords` |
| POST | `/history/summary` | `historySummary` |

### performance (4)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/performance/ability-profile` | `performanceAbilityProfile` |
| POST | `/performance/breakthroughs` | `performanceBreakthroughs` |
| POST | `/performance/neuromuscular-profile` | `performanceNeuromuscularProfile` |
| POST | `/power-source/normalize` | `powerSourceNormalize` |

### planning (3)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/planning/adapt-week` | `planningAdaptWeek` |
| POST | `/planning/check-load-risk` | `planningCheckLoadRisk` |
| POST | `/planning/create-season-plan` | `planningCreateSeasonPlan` |

### readiness (3)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/load/risk` | `loadRisk` |
| POST | `/load/state/update` | `loadStateUpdate` |
| POST | `/readiness/today` | `readinessToday` |

### test (3)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/test/confirm` | `testConfirm` |
| POST | `/test/in-person` | `testInPerson` |
| POST | `/test/propose` | `testPropose` |

### integrations (2)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/integrations/activities/deduplicate` | `integrationsDeduplicateActivities` |
| POST | `/integrations/activity/normalize` | `integrationsNormalizeActivity` |

### meta (2)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/meta/chart-config` | `metaChartConfig` |
| GET | `/meta/engine-tiers` | `metaEngineTiers` |

### race (2)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/race/gpx/analyze` | `raceGpxAnalyze` |
| POST | `/race/gpx/simulate` | `raceGpxSimulate` |

### team (2)

| Method | Path | operationId |
|--------|------|-------------|
| POST | `/team/calibration/apply` | `teamCalibrationApply` |
| POST | `/team/calibration/update` | `teamCalibrationUpdate` |

### health (1)

| Method | Path | operationId |
|--------|------|-------------|
| GET | `/health` | `healthCheck` |
