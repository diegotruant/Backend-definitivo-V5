// Core TypeScript contracts for the Digital Twin frontend.
// These are intentionally permissive because backend engines may add fields.

export type ModelStatus = 'success' | 'error' | 'skipped' | 'insufficient_data' | 'unavailable' | string;
export type MetricSource = 'measured' | 'standard_formula' | 'model_estimate' | 'team_calibrated' | 'heuristic' | 'experimental';

export interface AthleteParams {
  weight_kg: number;
  gender: string;
  training_years: number;
  discipline: string;
  active_muscle_mass_kg?: number | null;
}

export interface AthleteRecord {
  id: string;
  team_id: string;
  name: string;
  params: AthleteParams;
  phenotype?: string | null;
  latest_anchor?: Record<string, unknown> | null;
  latest_curve?: Record<string, unknown> | null;
  latest_snapshot?: MetabolicSnapshot | null;
}

export type MMP = Record<string, number>;

export interface MetabolicSnapshot {
  status?: ModelStatus;
  estimated_vo2max?: number | null;
  estimated_vlamax_mmol_L_s?: number | null;
  mlss_power_watts?: number | null;
  mlss_power_wkg?: number | null;
  fatmax_power_watts?: number | null;
  map_aerobic_watts?: number | null;
  metabolic_phenotype?: string | null;
  phenotype?: string | null;
  confidence_score?: number | null;
  warnings?: string[];
  limitations?: string[];
  expressiveness?: Record<string, unknown>;
  combustion_curve?: unknown;
  zones?: unknown;
  cross_validation?: unknown;
  calibration_audit?: CalibrationAudit[];
  [key: string]: unknown;
}

export interface RideIngestResponse {
  curve: Record<string, unknown>;
  mmp_for_profiler: MMP;
  improvements: number;
  ride_usable: boolean;
  profile_should_refresh: boolean;
  notes: string[];
}

export interface WorkoutSummary {
  status: ModelStatus;
  schema_version?: string;
  stream_metadata?: Record<string, unknown>;
  sections?: Record<string, unknown>;
  headline?: Record<string, unknown>;
  warnings?: string[];
  [key: string]: unknown;
}

export interface ValidationEvent {
  athlete_id: string;
  team_id?: string;
  parameter: 'mlss' | 'vo2max' | 'vlamax' | 'fatmax' | 'map' | string;
  predicted_value: number;
  measured_value: number;
  test_date: string;
  model_version: string;
  protocol: string;
  phenotype?: string | null;
  data_depth_score?: number;
  measurement_confidence?: number;
}

export interface CalibrationAudit {
  parameter: string;
  original_value: number;
  corrected_value: number;
  applied_correction: number;
  source?: string;
  confidence?: number;
  notes?: string[];
  [key: string]: unknown;
}

export interface TeamCalibrationModel {
  team_id: string;
  events?: ValidationEvent[];
  accuracy_report?: Record<string, unknown>;
  [key: string]: unknown;
}
