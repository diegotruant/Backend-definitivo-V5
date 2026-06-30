/**
 * Typed HTTP client for all Digital Twin API endpoints.
 *
 * Types are generated from `openapi/openapi.json` (see `npm run codegen:api`).
 * Domain-rich interfaces remain in `../contracts.ts` for UI helpers.
 */

import type { components, operations } from './generated/schema';
import type {
  MetabolicSnapshot,
  TeamCalibrationModel,
  WorkoutSummary,
  RideIngestResponse,
} from '../contracts';

export type HealthResponse = components['schemas']['HealthResponse'];
export type ConfirmRequest = components['schemas']['ConfirmRequest'];
export type SnapshotRequest = components['schemas']['SnapshotRequest'];
export type UpdateProfileRequest = components['schemas']['UpdateProfileRequest'];
export type InPersonTestRequest = components['schemas']['InPersonTestRequest'];
export type WorkoutValidateRequest = components['schemas']['WorkoutValidateRequest'];
export type WorkoutPrescribeRequest = components['schemas']['WorkoutPrescribeRequest'];
export type WorkoutFeasibilityRequest = components['schemas']['WorkoutFeasibilityRequest'];
export type CalendarTransitionRequest = components['schemas']['CalendarTransitionRequest'];
export type TwinStateBuildRequest = components['schemas']['TwinStateBuildRequest'];
export type TwinStateUpdateRideRequest = components['schemas']['TwinStateUpdateRideRequest'];
export type TwinStateUpdateWorkoutRequest = components['schemas']['TwinStateUpdateWorkoutRequest'];
export type SeasonProjectionRequest = components['schemas']['SeasonProjectionRequest'];
export type PowerSourceNormalizationRequest = components['schemas']['PowerSourceNormalizationRequest'];
export type ManualLoadRequest = components['schemas']['ManualLoadRequest'];
export type TeamCalibrationUpdateRequest = components['schemas']['TeamCalibrationUpdateRequest'];
export type TeamCalibrationApplyRequest = components['schemas']['TeamCalibrationApplyRequest'];
export type WorkoutPrescribeResponse = components['schemas']['WorkoutPrescribeResponse'];
export type EnginePayload = components['schemas']['EnginePayload'];

export class ApiError extends Error {
  readonly status: number;
  readonly body: string;

  constructor(status: number, statusText: string, body: string) {
    super(`${status} ${statusText}: ${body}`);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

function readNextPublicApiBase(): string | undefined {
  const runtime = globalThis as {
    process?: { env?: Record<string, string | undefined> };
  };
  return runtime.process?.env?.NEXT_PUBLIC_API_BASE_URL;
}

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ??
  import.meta.env.NEXT_PUBLIC_API_BASE_URL ??
  readNextPublicApiBase() ??
  'http://localhost:8000';

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers:
      init?.body instanceof FormData
        ? init.headers
        : { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    throw new ApiError(res.status, res.statusText, await res.text());
  }
  return res.json() as Promise<T>;
}

export const api = {
  /** GET /health */
  health: () => jsonFetch<HealthResponse>('/health'),

  /** POST /test/propose */
  proposeTest: (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    return jsonFetch<EnginePayload>('/test/propose', { method: 'POST', body: form });
  },

  /** POST /test/confirm */
  confirmTest: (payload: ConfirmRequest) =>
    jsonFetch<EnginePayload>('/test/confirm', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /test/in-person */
  inPersonTest: (payload: InPersonTestRequest) =>
    jsonFetch<EnginePayload>('/test/in-person', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/ingest */
  ingestRide: (args: {
    file: File;
    ride_date: string;
    weight_kg: number;
    stored_curve_json?: string;
  }) => {
    const form = new FormData();
    form.append('file', args.file);
    form.append('ride_date', args.ride_date);
    form.append('weight_kg', String(args.weight_kg));
    if (args.stored_curve_json) form.append('stored_curve_json', args.stored_curve_json);
    return jsonFetch<RideIngestResponse>('/ride/ingest', { method: 'POST', body: form });
  },

  /** POST /ride/parse */
  rideParse: (args: { file: File }) => {
    const form = new FormData();
    form.append('file', args.file);
    return jsonFetch<EnginePayload>('/ride/parse', { method: 'POST', body: form });
  },

  /** POST /ride/update-profile */
  updateProfile: (payload: UpdateProfileRequest) =>
    jsonFetch<EnginePayload>('/ride/update-profile', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/snapshot */
  profileSnapshot: (payload: SnapshotRequest) =>
    jsonFetch<MetabolicSnapshot>('/profile/snapshot', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/summary */
  rideSummary: (args: {
    file?: File;
    power_json?: number[];
    hr_json?: number[];
    weight_kg: number;
    ftp?: number;
    lthr?: number;
    gender?: string;
    training_years?: number;
    discipline?: string;
    metabolic_snapshot?: MetabolicSnapshot;
    hrv_step_seconds?: number;
    hrv_max_windows?: number;
  }) => {
    const form = new FormData();
    if (args.file) form.append('file', args.file);
    if (args.power_json) form.append('power_json', JSON.stringify(args.power_json));
    if (args.hr_json) form.append('hr_json', JSON.stringify(args.hr_json));
    form.append('weight_kg', String(args.weight_kg));
    if (args.ftp != null) form.append('ftp', String(args.ftp));
    if (args.lthr != null) form.append('lthr', String(args.lthr));
    form.append('gender', args.gender ?? 'MALE');
    form.append('training_years', String(args.training_years ?? 10));
    form.append('discipline', args.discipline ?? 'ENDURANCE');
    if (args.metabolic_snapshot) {
      form.append('metabolic_snapshot_json', JSON.stringify(args.metabolic_snapshot));
    }
    if (args.hrv_step_seconds != null) form.append('hrv_step_seconds', String(args.hrv_step_seconds));
    if (args.hrv_max_windows != null) form.append('hrv_max_windows', String(args.hrv_max_windows));
    return jsonFetch<WorkoutSummary>('/ride/summary', { method: 'POST', body: form });
  },

  /** POST /ride/durability */
  rideDurability: (args: {
    file?: File;
    power_json?: number[];
    hr_json?: number[];
    weight_kg: number;
    metabolic_snapshot: MetabolicSnapshot;
  }) => {
    const form = new FormData();
    if (args.file) form.append('file', args.file);
    if (args.power_json) form.append('power_json', JSON.stringify(args.power_json));
    if (args.hr_json) form.append('hr_json', JSON.stringify(args.hr_json));
    form.append('weight_kg', String(args.weight_kg));
    form.append('metabolic_snapshot_json', JSON.stringify(args.metabolic_snapshot));
    return jsonFetch<EnginePayload>('/ride/durability', { method: 'POST', body: form });
  },



  /** POST /ride/intelligence */
  rideIntelligence: (args: {
    file?: File;
    power_json?: number[];
    hr_json?: number[];
    weight_kg?: number;
    ftp?: number;
    cp?: number;
    lthr?: number;
  }) => {
    const form = new FormData();
    form.append('weight_kg', String(args.weight_kg ?? 70));
    if (args.ftp != null) form.append('ftp', String(args.ftp));
    if (args.cp != null) form.append('cp', String(args.cp));
    if (args.lthr != null) form.append('lthr', String(args.lthr));
    if (args.file) form.append('file', args.file);
    if (args.power_json) form.append('power_json', JSON.stringify(args.power_json));
    if (args.hr_json) form.append('hr_json', JSON.stringify(args.hr_json));
    return jsonFetch<EnginePayload>('/ride/intelligence', { method: 'POST', body: form });
  },

  /** POST /ride/data-quality */
  rideDataQuality: (args: { file?: File; power_json?: number[]; hr_json?: number[] }) => {
    const form = new FormData();
    if (args.file) form.append('file', args.file);
    if (args.power_json) form.append('power_json', JSON.stringify(args.power_json));
    if (args.hr_json) form.append('hr_json', JSON.stringify(args.hr_json));
    return jsonFetch<EnginePayload>('/ride/data-quality', { method: 'POST', body: form });
  },

  /** POST /workouts/validate */
  validateWorkout: (payload: WorkoutValidateRequest) =>
    jsonFetch<EnginePayload>('/workouts/validate', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /workouts/prescribe */
  prescribeWorkout: (payload: WorkoutPrescribeRequest) =>
    jsonFetch<WorkoutPrescribeResponse>('/workouts/prescribe', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /workouts/feasibility */
  workoutFeasibility: (payload: WorkoutFeasibilityRequest) =>
    jsonFetch<EnginePayload>('/workouts/feasibility', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /workouts/compare */
  compareWorkout: (args: {
    workout: Record<string, unknown>;
    file?: File;
    power_json?: number[];
    athlete_profile?: Record<string, unknown>;
    tolerance_policy?: Record<string, unknown>;
  }) => {
    const form = new FormData();
    form.append('workout_json', JSON.stringify(args.workout));
    if (args.athlete_profile) {
      form.append('athlete_profile_json', JSON.stringify(args.athlete_profile));
    }
    if (args.tolerance_policy) {
      form.append('tolerance_policy_json', JSON.stringify(args.tolerance_policy));
    }
    if (args.file) form.append('file', args.file);
    if (args.power_json) form.append('power_json', JSON.stringify(args.power_json));
    return jsonFetch<EnginePayload>('/workouts/compare', { method: 'POST', body: form });
  },

  /** POST /workouts/calendar/transition */
  calendarTransition: (payload: CalendarTransitionRequest) =>
    jsonFetch<EnginePayload>('/workouts/calendar/transition', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),



  /** POST /workouts/recommend */
  recommendWorkout: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/workouts/recommend', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /workouts/progression-levels */
  workoutProgressionLevels: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/workouts/progression-levels', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /workouts/adapt-plan */
  adaptWorkoutPlan: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/workouts/adapt-plan', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /workouts/export */
  exportWorkout: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/workouts/export', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /twin/state/build */
  twinStateBuild: (payload: TwinStateBuildRequest) =>
    jsonFetch<EnginePayload>('/twin/state/build', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /twin/state/update-from-ride */
  twinStateUpdateFromRide: (payload: TwinStateUpdateRideRequest) =>
    jsonFetch<EnginePayload>('/twin/state/update-from-ride', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /twin/state/update-from-workout-result */
  twinStateUpdateFromWorkout: (payload: TwinStateUpdateWorkoutRequest) =>
    jsonFetch<EnginePayload>('/twin/state/update-from-workout-result', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /twin/state/project */
  twinStateProject: (payload: SeasonProjectionRequest) =>
    jsonFetch<EnginePayload>('/twin/state/project', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /projection/season (alias) */
  projectionSeason: (payload: SeasonProjectionRequest) =>
    jsonFetch<EnginePayload>('/projection/season', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /performance/neuromuscular-profile */
  neuromuscularProfile: (args: {
    file?: File;
    power_json?: number[];
    weight_kg?: number;
    sprint_threshold_w?: number;
  }) => {
    const form = new FormData();
    form.append('weight_kg', String(args.weight_kg ?? 70));
    if (args.sprint_threshold_w != null) {
      form.append('sprint_threshold_w', String(args.sprint_threshold_w));
    }
    if (args.file) form.append('file', args.file);
    if (args.power_json) form.append('power_json', JSON.stringify(args.power_json));
    return jsonFetch<EnginePayload>('/performance/neuromuscular-profile', { method: 'POST', body: form });
  },



  /** POST /performance/ability-profile */
  abilityProfile: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/performance/ability-profile', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /performance/breakthroughs */
  performanceBreakthroughs: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/performance/breakthroughs', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /power-source/normalize */
  powerSourceNormalize: (payload: PowerSourceNormalizationRequest) =>
    jsonFetch<EnginePayload>('/power-source/normalize', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /load/manual */
  manualLoad: (payload: ManualLoadRequest) =>
    jsonFetch<EnginePayload>('/load/manual', { method: 'POST', body: JSON.stringify(payload) }),



  /** POST /load/state/update */
  updateLoadState: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/load/state/update', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /load/risk */
  loadRisk: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/load/risk', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /readiness/today */
  readinessToday: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/readiness/today', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /coach/strength/prescription */
  coachStrengthPrescription: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/strength/prescription', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /coach/nutrition/performance-targets */
  coachNutritionPerformanceTargets: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/nutrition/performance-targets', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /coach/checkin */
  coachCheckin: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/checkin', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /coach/decision-safety */
  coachDecisionSafety: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/decision-safety', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /coach/attention */
  coachAttention: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/attention', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /coach/attention/roster */
  coachRosterAttention: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/attention/roster', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /coach/race-execution */
  coachRaceExecution: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/race-execution', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /coach/adherence */
  coachAdherence: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/adherence', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /coach/testing-plan */
  coachTestingPlan: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/testing-plan', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /coach/periodization */
  coachPeriodization: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/periodization', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /coach/communication-draft */
  coachCommunicationDraft: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/communication-draft', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /coach/environment-adjustment */
  coachEnvironmentAdjustment: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/environment-adjustment', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /coach/pnei-context */
  coachPneiContext: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/pnei-context', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /coach/endocrine-context */
  coachEndocrineContext: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/endocrine-context', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /coach/constraints */
  coachConstraints: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/constraints', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /coach/training-safety */
  coachTrainingSafety: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/training-safety', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /coach/equipment-comfort */
  coachEquipmentComfort: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/equipment-comfort', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /coach/female-athlete-context */
  coachFemaleAthleteContext: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/female-athlete-context', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /coach/daily-brief */
  coachDailyBrief: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/daily-brief', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /coach/session-decision */
  coachSessionDecision: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/coach/session-decision', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /history/summary */
  historySummary: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/history/summary', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /history/power-curve */
  historyPowerCurve: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/history/power-curve', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /history/records */
  historyRecords: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/history/records', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /history/load */
  historyLoad: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/history/load', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /planning/create-season-plan */
  createSeasonPlan: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/planning/create-season-plan', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /planning/adapt-week */
  adaptWeek: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/planning/adapt-week', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /planning/check-load-risk */
  checkPlannedLoadRisk: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/planning/check-load-risk', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /team/calibration/update */
  updateTeamCalibration: (payload: TeamCalibrationUpdateRequest) =>
    jsonFetch<TeamCalibrationModel>('/team/calibration/update', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /team/calibration/apply */
  applyTeamCalibration: (payload: TeamCalibrationApplyRequest) =>
    jsonFetch<MetabolicSnapshot | EnginePayload>('/team/calibration/apply', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** POST /explainability/acwr-narrative */
  explainabilityAcwrNarrative: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/explainability/acwr-narrative', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /explainability/durability-confidence */
  explainabilityDurabilityConfidence: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/explainability/durability-confidence', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /explainability/durability-narrative */
  explainabilityDurabilityNarrative: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/explainability/durability-narrative', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /explainability/fatmax-confidence */
  explainabilityFatmaxConfidence: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/explainability/fatmax-confidence', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /explainability/fatmax-narrative */
  explainabilityFatmaxNarrative: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/explainability/fatmax-narrative', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /explainability/metric-narrative */
  explainabilityMetricNarrative: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/explainability/metric-narrative', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /explainability/vo2max-confidence */
  explainabilityVo2maxConfidence: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/explainability/vo2max-confidence', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /explainability/workout-summary-narrative */
  explainabilityWorkoutSummaryNarrative: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/explainability/workout-summary-narrative', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /integrations/activities/deduplicate */
  integrationsActivitiesDeduplicate: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/integrations/activities/deduplicate', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /integrations/activity/normalize */
  integrationsActivityNormalize: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/integrations/activity/normalize', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /lab/create-result */
  labCreateResult: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/lab/create-result', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /lab/lactate/thresholds */
  labLactateThresholds: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/lab/lactate/thresholds', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /lab/lactate/validate-model */
  labLactateValidateModel: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/lab/lactate/validate-model', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /lab/parse-text */
  labParseText: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/lab/parse-text', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /lab/validate-result */
  labValidateResult: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/lab/validate-result', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /lab/vlapeak/observed */
  labVlapeakObserved: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/lab/vlapeak/observed', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /lab/vlapeak/validate */
  labVlapeakValidate: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/lab/vlapeak/validate', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /load/acwr */
  loadAcwr: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/load/acwr', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /load/adaptive/recommendation */
  loadAdaptiveRecommendation: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/load/adaptive/recommendation', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /load/adaptive/trend */
  loadAdaptiveTrend: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/load/adaptive/trend', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /load/monotony-strain */
  loadMonotonyStrain: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/load/monotony-strain', { method: 'POST', body: JSON.stringify(payload) }),

  /** GET /meta/chart-types */
  metaChartTypes: () => jsonFetch<EnginePayload>('/meta/chart-types'),

  /** POST /meta/chart-config */
  metaChartConfig: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/meta/chart-config', { method: 'POST', body: JSON.stringify(payload) }),

  /** GET /meta/engine-tiers */
  metaEngineTiers: () => jsonFetch<EnginePayload>('/meta/engine-tiers'),

  /** POST /dashboard/athlete-snapshot */
  dashboardAthleteSnapshot: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/dashboard/athlete-snapshot', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/cross-validate */
  profileCrossValidate: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/cross-validate', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/detraining/apply */
  profileDetrainingApply: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/detraining/apply', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/fatmax/compare */
  profileFatmaxCompare: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/fatmax/compare', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/fatmax/lab */
  profileFatmaxLab: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/fatmax/lab', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/fatmax/report */
  profileFatmaxReport: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/fatmax/report', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/glycolytic-profile */
  profileGlycolyticProfile: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/glycolytic-profile', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/kalman/trajectory */
  profileKalmanTrajectory: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/kalman/trajectory', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/metabolic/current */
  profileMetabolicCurrent: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/metabolic/current', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/metabolic/curves */
  profileMetabolicCurves: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/metabolic/curves', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/mmp-quality */
  profileMmpQuality: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/mmp-quality', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/snapshot/auto */
  profileSnapshotAuto: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/snapshot/auto', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/snapshot/bayesian */
  profileSnapshotBayesian: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/snapshot/bayesian', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/snapshot/phenotype */
  profileSnapshotPhenotype: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/snapshot/phenotype', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/snapshot/segmented */
  profileSnapshotSegmented: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/snapshot/segmented', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/training-load/ctl-atl-tsb */
  profileTrainingLoadCtlAtlTsb: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/training-load/ctl-atl-tsb', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/vlamax-from-sprint */
  profileVlamaxFromSprint: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/vlamax-from-sprint', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /profile/w-prime/tau */
  profileWPrimeTau: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/w-prime/tau', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /race/gpx/analyze */
  raceGpxAnalyze: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/race/gpx/analyze', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /race/gpx/simulate */
  raceGpxSimulate: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/race/gpx/simulate', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/analytics/adaptive-load */
  rideAnalyticsAdaptiveLoad: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/adaptive-load', { method: 'POST', body: form }),

  /** POST /ride/analytics/cardiac */
  rideAnalyticsCardiac: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/cardiac', { method: 'POST', body: form }),

  /** POST /ride/analytics/critical-power/fit */
  rideAnalyticsCriticalPowerFit: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/ride/analytics/critical-power/fit', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/analytics/durability/hourly-decay */
  rideAnalyticsDurabilityHourlyDecay: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/ride/analytics/durability/hourly-decay', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/analytics/durability/index */
  rideAnalyticsDurabilityIndex: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/ride/analytics/durability/index', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/analytics/durability/np-drift */
  rideAnalyticsDurabilityNpDrift: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/ride/analytics/durability/np-drift', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/analytics/durability/prescription */
  rideAnalyticsDurabilityPrescription: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/ride/analytics/durability/prescription', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/analytics/durability/tte-sustainability */
  rideAnalyticsDurabilityTteSustainability: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/ride/analytics/durability/tte-sustainability', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/analytics/efforts */
  rideAnalyticsEfforts: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/efforts', { method: 'POST', body: form }),

  /** POST /ride/analytics/hrv */
  rideAnalyticsHrv: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/hrv', { method: 'POST', body: form }),

  /** POST /ride/analytics/metabolic-flexibility */
  rideAnalyticsMetabolicFlexibility: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/ride/analytics/metabolic-flexibility', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/analytics/pedaling-balance */
  rideAnalyticsPedalingBalance: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/pedaling-balance', { method: 'POST', body: form }),

  /** POST /ride/analytics/power */
  rideAnalyticsPower: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/power', { method: 'POST', body: form }),

  /** POST /ride/analytics/resilience */
  rideAnalyticsResilience: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/ride/analytics/resilience', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/analytics/segments/climbs */
  rideAnalyticsSegmentsClimbs: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/segments/climbs', { method: 'POST', body: form }),

  /** POST /ride/analytics/segments/compare */
  rideAnalyticsSegmentsCompare: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/ride/analytics/segments/compare', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/analytics/session/classify */
  rideAnalyticsSessionClassify: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/session/classify', { method: 'POST', body: form }),

  /** POST /ride/analytics/session/protocol-completeness */
  rideAnalyticsSessionProtocolCompleteness: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/session/protocol-completeness', { method: 'POST', body: form }),

  /** POST /ride/analytics/session/route-decide */
  rideAnalyticsSessionRouteDecide: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/session/route-decide', { method: 'POST', body: form }),

  /** POST /ride/analytics/session/route-run */
  rideAnalyticsSessionRouteRun: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/session/route-run', { method: 'POST', body: form }),

  /** POST /ride/analytics/statistics */
  rideAnalyticsStatistics: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/statistics', { method: 'POST', body: form }),

  /** POST /ride/analytics/thermal/acclimation */
  rideAnalyticsThermalAcclimation: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/ride/analytics/thermal/acclimation', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/analytics/thermal/session */
  rideAnalyticsThermalSession: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/thermal/session', { method: 'POST', body: form }),

  /** POST /ride/analytics/w-prime/balance */
  rideAnalyticsWPrimeBalance: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/ride/analytics/w-prime/balance', { method: 'POST', body: JSON.stringify(payload) }),

  /** POST /ride/analytics/zones */
  rideAnalyticsZones: (form: FormData) => jsonFetch<EnginePayload>('/ride/analytics/zones', { method: 'POST', body: form }),

  /** POST /twin/state/validate */
  twinStateValidate: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/twin/state/validate', { method: 'POST', body: JSON.stringify(payload) }),


  /** POST /profile/vlamax-from-power-series */
  profileVlamaxFromPowerSeries: (payload: Record<string, unknown>) =>
    jsonFetch<EnginePayload>('/profile/vlamax-from-power-series', { method: 'POST', body: JSON.stringify(payload) }),

} as const;

/** OpenAPI operation ids for cross-reference with Swagger UI */
export type ApiOperationId = keyof operations;

export { API_BASE };
