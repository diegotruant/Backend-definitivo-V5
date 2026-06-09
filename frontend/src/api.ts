import type {
  AthleteParams,
  MMP,
  MetabolicSnapshot,
  RideIngestResponse,
  TeamCalibrationModel,
  ValidationEvent,
  WorkoutSummary,
} from './contracts';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: init?.body instanceof FormData
      ? init.headers
      : { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => jsonFetch<{ status: string; service: string; version: string }>('/health'),

  proposeTest: (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    return jsonFetch<Record<string, unknown>>('/test/propose', { method: 'POST', body: form });
  },

  confirmTest: (payload: { proposal: Record<string, unknown>; athlete: AthleteParams; measured_on: string }) =>
    jsonFetch<Record<string, unknown>>('/test/confirm', { method: 'POST', body: JSON.stringify(payload) }),

  ingestRide: (args: { file: File; ride_date: string; weight_kg: number; stored_curve_json?: string }) => {
    const form = new FormData();
    form.append('file', args.file);
    form.append('ride_date', args.ride_date);
    form.append('weight_kg', String(args.weight_kg));
    if (args.stored_curve_json) form.append('stored_curve_json', args.stored_curve_json);
    return jsonFetch<RideIngestResponse>('/ride/ingest', { method: 'POST', body: form });
  },

  profileSnapshot: (payload: { mmp: MMP; athlete: AthleteParams }) =>
    jsonFetch<MetabolicSnapshot>('/profile/snapshot', { method: 'POST', body: JSON.stringify(payload) }),

  rideSummary: (args: {
    file?: File;
    power_json?: number[];
    weight_kg: number;
    ftp?: number;
    lthr?: number;
    gender?: string;
    training_years?: number;
    discipline?: string;
    metabolic_snapshot?: MetabolicSnapshot;
  }) => {
    const form = new FormData();
    if (args.file) form.append('file', args.file);
    if (args.power_json) form.append('power_json', JSON.stringify(args.power_json));
    form.append('weight_kg', String(args.weight_kg));
    if (args.ftp) form.append('ftp', String(args.ftp));
    if (args.lthr) form.append('lthr', String(args.lthr));
    form.append('gender', args.gender ?? 'MALE');
    form.append('training_years', String(args.training_years ?? 10));
    form.append('discipline', args.discipline ?? 'ENDURANCE');
    if (args.metabolic_snapshot) form.append('metabolic_snapshot_json', JSON.stringify(args.metabolic_snapshot));
    return jsonFetch<WorkoutSummary>('/ride/summary', { method: 'POST', body: form });
  },

  updateTeamCalibration: (payload: {
    team_id: string;
    calibration_model?: TeamCalibrationModel | null;
    events: ValidationEvent[];
  }) => jsonFetch<TeamCalibrationModel>('/team/calibration/update', { method: 'POST', body: JSON.stringify(payload) }),

  applyTeamCalibration: (payload: {
    calibration_model: TeamCalibrationModel;
    parameter?: string;
    predicted_value?: number;
    snapshot?: MetabolicSnapshot;
    athlete_id?: string;
    phenotype?: string;
    data_depth_score?: number;
  }) => jsonFetch<MetabolicSnapshot | Record<string, unknown>>('/team/calibration/apply', { method: 'POST', body: JSON.stringify(payload) }),
};
