import type { MetricSource } from './contracts';

export interface MetricDefinition {
  label: string;
  unit: string;
  source: MetricSource;
  coachTooltip: string;
  lowConfidenceWarning?: string;
}

export const metricDictionary: Record<string, MetricDefinition> = {
  mlss_power_watts: {
    label: 'MLSS',
    unit: 'W',
    source: 'model_estimate',
    coachTooltip: 'Estimated power at maximum sustainable metabolic steady state. Useful for threshold work and pacing.',
    lowConfidenceWarning: 'MLSS needs long 20–60 minute data or lactate testing for high reliability.',
  },
  mlss_power_wkg: {
    label: 'MLSS',
    unit: 'W/kg',
    source: 'model_estimate',
    coachTooltip: 'Weight-normalized MLSS. Useful for climbers and athlete comparison.',
  },
  estimated_vo2max: {
    label: 'VO₂max',
    unit: 'ml/kg/min',
    source: 'model_estimate',
    coachTooltip: 'Estimated maximal aerobic capacity. If not measured by spirometry, this is model-derived.',
  },
  estimated_vlamax_mmol_L_s: {
    label: 'VLamax',
    unit: 'mmol/L/s',
    source: 'model_estimate',
    coachTooltip: 'Glycolytic capacity. Higher values support sprinting and surges but increase carbohydrate demand.',
    lowConfidenceWarning: 'VLamax requires reliable maximal short sprint efforts.',
  },
  fatmax_power_watts: {
    label: 'FatMax',
    unit: 'W',
    source: 'model_estimate',
    coachTooltip: 'Estimated power at maximal fat oxidation. Useful for endurance and nutrition planning.',
  },
  map_aerobic_watts: {
    label: 'Aerobic MAP',
    unit: 'W',
    source: 'model_estimate',
    coachTooltip: 'Estimated maximal aerobic power from the model.',
  },
  normalized_power: {
    label: 'Normalized Power',
    unit: 'W',
    source: 'standard_formula',
    coachTooltip: 'Equivalent power that better represents physiological cost during variable rides.',
  },
  intensity_factor: {
    label: 'Intensity Factor',
    unit: '',
    source: 'standard_formula',
    coachTooltip: 'Ratio between Normalized Power and FTP/threshold. Measures relative intensity.',
  },
  tss: {
    label: 'TSS',
    unit: 'pts',
    source: 'standard_formula',
    coachTooltip: 'Training Stress Score. Estimates overall session load.',
  },
  cardiac_drift: {
    label: 'Cardiac drift',
    unit: '%',
    source: 'heuristic',
    coachTooltip: 'Heart-rate increase at constant power. Can indicate fatigue, heat, or dehydration.',
  },
};

export function confidenceLabel(score?: number | null): 'High' | 'Moderate' | 'Low' | 'Unavailable' {
  if (score == null) return 'Unavailable';
  if (score >= 0.8) return 'High';
  if (score >= 0.55) return 'Moderate';
  return 'Low';
}

export function statusColor(status?: string, confidence?: number | null): 'green' | 'yellow' | 'red' | 'gray' {
  if (!status || status === 'unavailable' || status === 'skipped') return 'gray';
  if (status !== 'success') return 'red';
  if (confidence != null && confidence < 0.55) return 'yellow';
  return 'green';
}
