import type { AthleteRecord, MetabolicSnapshot, TeamCalibrationModel, ValidationEvent } from './contracts';

export const mockSnapshot: MetabolicSnapshot = {
  status: 'success',
  estimated_vo2max: 78.4,
  estimated_vlamax_mmol_L_s: 0.36,
  mlss_power_watts: 372,
  mlss_power_wkg: 5.31,
  fatmax_power_watts: 265,
  map_aerobic_watts: 445,
  metabolic_phenotype: 'climber-diesel',
  confidence_score: 0.86,
  warnings: [],
  expressiveness: {
    sprint_5_15s: true,
    glycolytic_20_60s: true,
    vo2max_3_12min: true,
    threshold_20_60min: true,
  },
  calibration_audit: [
    {
      parameter: 'mlss',
      original_value: 380,
      corrected_value: 372,
      applied_correction: -8,
      source: 'athlete+phenotype+team',
      confidence: 0.82,
      notes: ['Correzione limitata da cap conservativo.'],
    },
  ],
};

export const mockAthletes: AthleteRecord[] = [
  {
    id: 'rider_01',
    team_id: 'wt_team_01',
    name: 'GC Climber',
    params: { weight_kg: 70, gender: 'MALE', training_years: 12, discipline: 'ENDURANCE' },
    phenotype: 'climber-diesel',
    latest_snapshot: mockSnapshot,
  },
  {
    id: 'rider_02',
    team_id: 'wt_team_01',
    name: 'Sprinter',
    params: { weight_kg: 78, gender: 'MALE', training_years: 10, discipline: 'ROAD' },
    phenotype: 'sprinter',
    latest_snapshot: {
      ...mockSnapshot,
      estimated_vo2max: 70.2,
      estimated_vlamax_mmol_L_s: 0.62,
      mlss_power_watts: 360,
      mlss_power_wkg: 4.62,
      metabolic_phenotype: 'sprinter-glycolytic',
      confidence_score: 0.74,
    },
  },
];

export const mockValidationEvents: ValidationEvent[] = [
  {
    team_id: 'wt_team_01',
    athlete_id: 'rider_01',
    parameter: 'mlss',
    predicted_value: 380,
    measured_value: 372,
    test_date: '2026-06-09',
    model_version: 'v5',
    protocol: 'mader_lactate',
    phenotype: 'climber-diesel',
    data_depth_score: 0.92,
    measurement_confidence: 0.95,
  },
  {
    team_id: 'wt_team_01',
    athlete_id: 'rider_02',
    parameter: 'vlamax',
    predicted_value: 0.55,
    measured_value: 0.62,
    test_date: '2026-06-08',
    model_version: 'v5',
    protocol: 'wingate_lactate',
    phenotype: 'sprinter',
    data_depth_score: 0.88,
    measurement_confidence: 0.9,
  },
];

export const mockCalibrationModel: TeamCalibrationModel = {
  team_id: 'wt_team_01',
  events: mockValidationEvents,
  accuracy_report: {
    mlss: { n: 18, bias: -4.2, mae: 8.1, status: 'calibrated' },
    vo2max: { n: 9, bias: 1.2, mae: 2.5, status: 'learning' },
    vlamax: { n: 7, bias: 0.03, mae: 0.07, status: 'learning' },
  },
};
