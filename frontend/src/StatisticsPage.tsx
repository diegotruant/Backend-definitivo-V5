import type { ActivityStatisticsMetrics } from './contracts';

const fmt = (value: number | null | undefined, digits = 0): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  return value.toLocaleString('it-IT', { maximumFractionDigits: digits });
};

export interface StatisticsPageProps {
  metrics: ActivityStatisticsMetrics;
  title?: string;
  subtitle?: string;
}

const ROWS: { key: keyof ActivityStatisticsMetrics; label: string; unit: string; digits?: number }[] = [
  { key: 'avg_power_w', label: 'Potenza media', unit: 'W', digits: 0 },
  { key: 'avg_power_w_kg', label: 'Potenza media', unit: 'W/kg', digits: 2 },
  { key: 'np_w', label: 'Normalized Power', unit: 'W', digits: 0 },
  { key: 'np_w_kg', label: 'NP', unit: 'W/kg', digits: 2 },
  { key: 'max_power_w', label: 'Potenza max', unit: 'W', digits: 0 },
  { key: 'work_kj', label: 'Lavoro', unit: 'kJ', digits: 0 },
  { key: 'avg_hr_bpm', label: 'FC media', unit: 'bpm', digits: 0 },
  { key: 'max_hr_bpm', label: 'FC max', unit: 'bpm', digits: 0 },
  { key: 'avg_cadence_rpm', label: 'Cadenza media', unit: 'rpm', digits: 0 },
  { key: 'max_cadence_rpm', label: 'Cadenza max', unit: 'rpm', digits: 0 },
  { key: 'ascent_m', label: 'Dislivello +', unit: 'm', digits: 0 },
  { key: 'descent_m', label: 'Dislivello −', unit: 'm', digits: 0 },
  { key: 'temperature_avg_c', label: 'Temperatura media', unit: '°C', digits: 1 },
  { key: 'speed_avg_kmh', label: 'Velocità media', unit: 'km/h', digits: 1 },
  { key: 'moving_speed_avg_kmh', label: 'Velocità in movimento', unit: 'km/h', digits: 1 },
];

export function StatisticsPage({ metrics, title = 'Statistiche attività', subtitle }: StatisticsPageProps) {
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
