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
    coachTooltip: 'Potenza stimata alla massima stabilità metabolica sostenibile. Utile per lavori soglia e pacing.',
    lowConfidenceWarning: 'MLSS richiede dati lunghi 20–60 minuti o test lattato per alta affidabilità.',
  },
  mlss_power_wkg: {
    label: 'MLSS',
    unit: 'W/kg',
    source: 'model_estimate',
    coachTooltip: 'MLSS normalizzata per peso. Utile per climber e confronto tra atleti.',
  },
  estimated_vo2max: {
    label: 'VO₂max',
    unit: 'ml/kg/min',
    source: 'model_estimate',
    coachTooltip: 'Capacità aerobica massima stimata. Se non arriva da spirometria è una stima modellata.',
  },
  estimated_vlamax_mmol_L_s: {
    label: 'VLamax',
    unit: 'mmol/L/s',
    source: 'model_estimate',
    coachTooltip: 'Capacità glicolitica. Valori alti favoriscono sprint e cambi ritmo, ma aumentano consumo carboidrati.',
    lowConfidenceWarning: 'VLamax richiede sprint/effort brevi massimali affidabili.',
  },
  fatmax_power_watts: {
    label: 'FatMax',
    unit: 'W',
    source: 'model_estimate',
    coachTooltip: 'Potenza stimata di massima ossidazione grassi. Utile per endurance e nutrizione.',
  },
  map_aerobic_watts: {
    label: 'MAP aerobica',
    unit: 'W',
    source: 'model_estimate',
    coachTooltip: 'Potenza aerobica massima stimata dal modello.',
  },
  normalized_power: {
    label: 'Normalized Power',
    unit: 'W',
    source: 'standard_formula',
    coachTooltip: 'Potenza equivalente che rappresenta meglio il costo fisiologico di una ride variabile.',
  },
  intensity_factor: {
    label: 'Intensity Factor',
    unit: '',
    source: 'standard_formula',
    coachTooltip: 'Rapporto tra Normalized Power e FTP/threshold. Misura intensità relativa.',
  },
  tss: {
    label: 'TSS',
    unit: 'pts',
    source: 'standard_formula',
    coachTooltip: 'Training Stress Score. Stima il carico complessivo della sessione.',
  },
  cardiac_drift: {
    label: 'Cardiac drift',
    unit: '%',
    source: 'heuristic',
    coachTooltip: 'Aumento della frequenza cardiaca a parità di potenza. Può indicare fatica, caldo o disidratazione.',
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
