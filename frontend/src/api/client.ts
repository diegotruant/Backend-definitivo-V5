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
} as const;

/** OpenAPI operation ids for cross-reference with Swagger UI */
export type ApiOperationId = keyof operations;

export { API_BASE };
