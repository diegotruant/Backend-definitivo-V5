import type { ActivityStatisticsMetrics } from './contracts';

const fmt = (value: number | null | undefined, digits = 0): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  return value.toLocaleString('en-US', { maximumFractionDigits: digits });
};

export interface StatisticsPageProps {
  metrics: ActivityStatisticsMetrics;
  title?: string;
  subtitle?: string;
}

const ROWS: { key: keyof ActivityStatisticsMetrics; label: string; unit: string; digits?: number }[] = [
  { key: 'avg_power_w', label: 'Average power', unit: 'W', digits: 0 },
  { key: 'avg_power_w_kg', label: 'Average power', unit: 'W/kg', digits: 2 },
  { key: 'np_w', label: 'Normalized Power', unit: 'W', digits: 0 },
  { key: 'np_w_kg', label: 'NP', unit: 'W/kg', digits: 2 },
  { key: 'max_power_w', label: 'Max power', unit: 'W', digits: 0 },
  { key: 'work_kj', label: 'Work', unit: 'kJ', digits: 0 },
  { key: 'avg_hr_bpm', label: 'Average HR', unit: 'bpm', digits: 0 },
  { key: 'max_hr_bpm', label: 'Max HR', unit: 'bpm', digits: 0 },
  { key: 'avg_cadence_rpm', label: 'Average cadence', unit: 'rpm', digits: 0 },
  { key: 'max_cadence_rpm', label: 'Max cadence', unit: 'rpm', digits: 0 },
  { key: 'ascent_m', label: 'Elevation gain', unit: 'm', digits: 0 },
  { key: 'descent_m', label: 'Elevation loss', unit: 'm', digits: 0 },
  { key: 'temperature_avg_c', label: 'Average temperature', unit: '°C', digits: 1 },
  { key: 'speed_avg_kmh', label: 'Average speed', unit: 'km/h', digits: 1 },
  { key: 'moving_speed_avg_kmh', label: 'Moving speed', unit: 'km/h', digits: 1 },
];

export function StatisticsPage({ metrics, title = 'Activity statistics', subtitle }: StatisticsPageProps) {
  return (
    <section className="panel full statistics-page">
      <div className="panel-header">
        <div>
          <span>Ride summary</span>
          <h2>{title}</h2>
          {subtitle ? <p className="statistics-subtitle">{subtitle}</p> : null}
        </div>
      </div>
      <div className="statistics-grid">
        {ROWS.map((row) => (
          <article key={row.key} className="statistics-card">
            <span>{row.label}</span>
            <strong>
              {fmt(metrics[row.key], row.digits ?? 0)}
              {metrics[row.key] != null ? ` ${row.unit}` : ''}
            </strong>
          </article>
        ))}
      </div>
    </section>
  );
}

export default StatisticsPage;
