import { useEffect, useMemo, useState } from 'react'
import { api } from './api/client'
import type { ActivityStatisticsMetrics } from './contracts'
import StatisticsPage from './StatisticsPage'
import './App.css'

type CsvRow = Record<string, string>

type Athlete = {
  athlete: string
  fit_files: number
  parsed_files: number
  total_duration_h: number
  total_tss: number
  avg_quality_score: number
  ftp_estimate: number
  avg_power: number
  avg_normalized_power: number
  avg_intensity_factor: number
  avg_hr: number
  avg_durability_index: number
  best_5s: number
  best_1min: number
  best_5min: number
  best_20min: number
  estimated_vo2max: number
  estimated_vlamax: number
  mlss_power: number
  fatmax_power: number
  metabolic_confidence: number
  metabolic_status: string
  ui_display_show_values?: boolean
  ui_display_recommended_mask_fields?: string[]
  category_counts: string
  top_subtypes: string
}

type Activity = {
  athlete: string
  file: string
  duration_min: number
  avg_power: number
  normalized_power: number
  intensity_factor: number
  tss: number
  avg_hr: number
  max_power: number
  quality_score: number
  category: string
  subtype: string
  durability_index: number
  np_drift_pct: number
  classification_confidence: number
  parsed: string
}

type View = 'dashboard' | 'athletes' | 'activities' | 'metabolic' | 'statistics'
const CONFIDENCE_DISPLAY_THRESHOLD = 0.55
const PLACEHOLDER = '—'

const number = (value: string | undefined): number => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

const parseCsv = (text: string): CsvRow[] => {
  const rows: string[][] = []
  let current = ''
  let row: string[] = []
  let inQuotes = false

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i]
    const next = text[i + 1]

    if (char === '"' && inQuotes && next === '"') {
      current += '"'
      i += 1
    } else if (char === '"') {
      inQuotes = !inQuotes
    } else if (char === ',' && !inQuotes) {
      row.push(current)
      current = ''
    } else if ((char === '\n' || char === '\r') && !inQuotes) {
      if (char === '\r' && next === '\n') i += 1
      row.push(current)
      if (row.some((cell) => cell.trim() !== '')) rows.push(row)
      row = []
      current = ''
    } else {
      current += char
    }
  }

  if (current || row.length) {
    row.push(current)
    rows.push(row)
  }

  const [headers, ...body] = rows
  return body.map((cells) =>
    headers.reduce<CsvRow>((acc, header, index) => {
      acc[header] = cells[index] ?? ''
      return acc
    }, {}),
  )
}

const parseBoolean = (value: string | undefined): boolean | undefined => {
  if (!value) return undefined
  const normalized = value.trim().toLowerCase()
  if (normalized === 'true' || normalized === '1') return true
  if (normalized === 'false' || normalized === '0') return false
  return undefined
}

const parseCsvStringList = (value: string | undefined): string[] => {
  if (!value) return []
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
}

const loadCsv = async (path: string): Promise<CsvRow[]> => {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`Could not load ${path}`)
  return parseCsv(await response.text())
}

const mapAthlete = (row: CsvRow): Athlete => ({
  athlete: row.athlete,
  fit_files: number(row.fit_files),
  parsed_files: number(row.parsed_files),
  total_duration_h: number(row.total_duration_h),
  total_tss: number(row.total_tss),
  avg_quality_score: number(row.avg_quality_score),
  ftp_estimate: number(row.ftp_estimate),
  avg_power: number(row.avg_power),
  avg_normalized_power: number(row.avg_normalized_power),
  avg_intensity_factor: number(row.avg_intensity_factor),
  avg_hr: number(row.avg_hr),
  avg_durability_index: number(row.avg_durability_index),
  best_5s: number(row.best_5s),
  best_1min: number(row.best_1min),
  best_5min: number(row.best_5min),
  best_20min: number(row.best_20min),
  estimated_vo2max: number(row.estimated_vo2max),
  estimated_vlamax: number(row.estimated_vlamax),
  mlss_power: number(row.mlss_power),
  fatmax_power: number(row.fatmax_power),
  metabolic_confidence: number(row.metabolic_confidence),
  metabolic_status: row.metabolic_status,
  ui_display_show_values: parseBoolean(row.ui_display_show_values),
  ui_display_recommended_mask_fields: parseCsvStringList(row.ui_display_recommended_mask_fields),
  category_counts: row.category_counts,
  top_subtypes: row.top_subtypes,
})

const mapActivity = (row: CsvRow): Activity => ({
  athlete: row.athlete,
  file: row.file,
  duration_min: number(row.duration_min),
  avg_power: number(row.avg_power),
  normalized_power: number(row.normalized_power),
  intensity_factor: number(row.intensity_factor),
  tss: number(row.tss),
  avg_hr: number(row.avg_hr),
  max_power: number(row.max_power),
  quality_score: number(row.quality_score),
  category: row.category,
  subtype: row.subtype,
  durability_index: number(row.durability_index),
  np_drift_pct: number(row.np_drift_pct),
  classification_confidence: number(row.classification_confidence),
  parsed: row.parsed,
})

const fmt = (value: number, digits = 0) =>
  Number.isFinite(value) ? value.toLocaleString('en-US', { maximumFractionDigits: digits }) : '-'

const pct = (value: number) => `${fmt(value * 100, 0)}%`

const formatMetabolicValue = (
  value: number,
  digits: number,
  showValue: boolean,
): string => (showValue ? fmt(value, digits) : PLACEHOLDER)

function KpiCard({
  label,
  value,
  detail,
  tone = 'blue',
}: {
  label: string
  value: string
  detail: string
  tone?: 'blue' | 'green' | 'amber' | 'violet'
}) {
  return (
    <article className={`kpi kpi-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  )
}

function Pill({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: string }) {
  return <span className={`pill pill-${tone}`}>{children}</span>
}

function App() {
  const [athletes, setAthletes] = useState<Athlete[]>([])
  const [activities, setActivities] = useState<Activity[]>([])
  const [view, setView] = useState<View>('dashboard')
  const [selectedAthlete, setSelectedAthlete] = useState<string>('001_Athlete_01')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [statisticsPage, setStatisticsPage] = useState<ActivityStatisticsMetrics | null>(null)
  const [statisticsLoading, setStatisticsLoading] = useState(false)
  const [statisticsError, setStatisticsError] = useState('')

  useEffect(() => {
    Promise.all([
      loadCsv('/data/athlete_summary.csv'),
      loadCsv('/data/activity_details.csv'),
    ])
      .then(([athleteRows, activityRows]) => {
        const parsedAthletes = athleteRows.map(mapAthlete)
        setAthletes(parsedAthletes)
        setActivities(activityRows.map(mapActivity))
        setSelectedAthlete(parsedAthletes[0]?.athlete ?? '')
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const selected = athletes.find((athlete) => athlete.athlete === selectedAthlete) ?? athletes[0]
  const selectedActivities = activities.filter((activity) => activity.athlete === selected?.athlete)

  const filteredAthletes = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return athletes
    return athletes.filter((athlete) => athlete.athlete.toLowerCase().includes(term))
  }, [athletes, query])

  const totals = useMemo(() => {
    const totalTss = athletes.reduce((sum, athlete) => sum + athlete.total_tss, 0)
    const totalHours = athletes.reduce((sum, athlete) => sum + athlete.total_duration_h, 0)
    const meanQuality = athletes.reduce((sum, athlete) => sum + athlete.avg_quality_score, 0) / (athletes.length || 1)
    const meanFtp = athletes.reduce((sum, athlete) => sum + athlete.ftp_estimate, 0) / (athletes.length || 1)
    return { totalTss, totalHours, meanQuality, meanFtp }
  }, [athletes])

  const topFtp = [...athletes].sort((a, b) => b.ftp_estimate - a.ftp_estimate).slice(0, 8)
  const topVo2 = [...athletes].sort((a, b) => b.estimated_vo2max - a.estimated_vo2max).slice(0, 8)
  const activityRows = selectedActivities.slice(0, 50)
  const showMetabolicValues = selected?.ui_display_show_values ?? ((selected?.metabolic_confidence ?? 0) >= CONFIDENCE_DISPLAY_THRESHOLD)
  const recommendedMaskFields = selected?.ui_display_recommended_mask_fields ?? []
  const shouldMaskField = (fieldKey: string): boolean =>
    !showMetabolicValues
    || recommendedMaskFields.some((item) => item.toLowerCase() === fieldKey.toLowerCase())

  const loadStatisticsFromApi = async () => {
    setStatisticsLoading(true)
    setStatisticsError('')
    try {
      const power = Array.from({ length: 1800 }, (_, i) => 190 + (i % 90))
      const summary = await api.rideSummary({
        power_json: power,
        weight_kg: selected?.avg_power ? 72 : 72,
        ftp: selected?.ftp_estimate || 280,
      })
      if (summary.statistics_page) {
        setStatisticsPage(summary.statistics_page)
      } else {
        setStatisticsError('/ride/summary response does not include statistics_page.')
      }
    } catch (err) {
      setStatisticsError(err instanceof Error ? err.message : 'Error loading statistics')
    } finally {
      setStatisticsLoading(false)
    }
  }

  useEffect(() => {
    if (view === 'statistics' && !statisticsPage && !statisticsLoading) {
      void loadStatisticsFromApi()
    }
  }, [view])

  if (loading) {
    return <main className="loading">Loading backend data...</main>
  }

  if (error) {
    return <main className="loading error-state">{error}</main>
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">DT</div>
          <div>
            <strong>Digital Twin</strong>
            <span>Coach Intelligence</span>
          </div>
        </div>

        <nav className="nav">
          {[
            ['dashboard', 'Dashboard'],
            ['athletes', 'Athletes'],
            ['activities', 'Activities'],
            ['statistics', 'Ride statistics'],
            ['metabolic', 'Metabolic profile'],
          ].map(([key, label]) => (
            <button
              key={key}
              className={view === key ? 'active' : ''}
              onClick={() => setView(key as View)}
            >
              {label}
            </button>
          ))}
        </nav>

        <div className="sidebar-card">
          <span>Dataset</span>
          <strong>{athletes.length} athletes</strong>
          <small>{activities.length.toLocaleString('en-US')} FIT activities</small>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <Pill tone="green">Backend connected</Pill>
            <h1>Performance analytics for coaches</h1>
            <p>
              Modern dashboard for reading power metrics, data quality, load,
              durability, and metabolic profile outputs computed by the backend.
            </p>
          </div>
          <select value={selectedAthlete} onChange={(event) => setSelectedAthlete(event.target.value)}>
            {athletes.map((athlete) => (
              <option key={athlete.athlete} value={athlete.athlete}>
                {athlete.athlete}
              </option>
            ))}
          </select>
        </header>

        {view === 'dashboard' && (
          <>
            <section className="kpi-grid">
              <KpiCard label="Athletes monitored" value={fmt(athletes.length)} detail="full dataset" />
              <KpiCard label="Hours analyzed" value={fmt(totals.totalHours, 1)} detail="synthetic FIT timeline" tone="green" />
              <KpiCard label="Total TSS" value={fmt(totals.totalTss, 0)} detail="aggregated load" tone="violet" />
              <KpiCard label="Average quality" value={pct(totals.meanQuality)} detail="power + HR + cadence" tone="amber" />
            </section>

            <section className="panel-grid">
              <div className="panel">
                <div className="panel-header">
                  <div>
                    <span>Ranking</span>
                    <h2>Top estimated FTP</h2>
                  </div>
                  <Pill>FTP medio {fmt(totals.meanFtp, 1)} W</Pill>
                </div>
                <div className="rank-list">
                  {topFtp.map((athlete, index) => (
                    <button key={athlete.athlete} onClick={() => { setSelectedAthlete(athlete.athlete); setView('metabolic') }}>
                      <span className="rank">#{index + 1}</span>
                      <span>{athlete.athlete}</span>
                      <strong>{fmt(athlete.ftp_estimate, 1)} W</strong>
                    </button>
                  ))}
                </div>
              </div>

              <div className="panel">
                <div className="panel-header">
                  <div>
                    <span>Metabolic engine</span>
                    <h2>Top estimated VO2max</h2>
                  </div>
                  <Pill tone="amber">model-derived</Pill>
                </div>
                <div className="bar-list">
                  {topVo2.map((athlete) => (
                    <div key={athlete.athlete} className="bar-row">
                      <span>{athlete.athlete}</span>
                      <div><i style={{ width: `${Math.min(100, athlete.estimated_vo2max)}%` }} /></div>
                      <strong>{fmt(athlete.estimated_vo2max, 1)}</strong>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          </>
        )}

        {view === 'athletes' && (
          <section className="panel full">
            <div className="panel-header">
              <div>
                <span>Roster</span>
                <h2>Athletes</h2>
              </div>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search athlete..."
              />
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Athlete</th>
                    <th>FIT</th>
                    <th>FTP</th>
                    <th>NP media</th>
                    <th>IF</th>
                    <th>Quality</th>
                    <th>VO2max</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAthletes.map((athlete) => (
                    <tr key={athlete.athlete}>
                      <td><strong>{athlete.athlete}</strong></td>
                      <td>{athlete.parsed_files}/{athlete.fit_files}</td>
                      <td>{fmt(athlete.ftp_estimate, 1)} W</td>
                      <td>{fmt(athlete.avg_normalized_power, 1)} W</td>
                      <td>{fmt(athlete.avg_intensity_factor, 3)}</td>
                      <td>{pct(athlete.avg_quality_score)}</td>
                      <td>{fmt(athlete.estimated_vo2max, 1)}</td>
                      <td>
                        <button className="link-button" onClick={() => { setSelectedAthlete(athlete.athlete); setView('metabolic') }}>
                          Open profile
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {view === 'activities' && selected && (
          <section className="panel full">
            <div className="panel-header">
              <div>
                <span>{selected.athlete}</span>
                <h2>Latest analyzed activities</h2>
              </div>
              <Pill>{selectedActivities.length} file FIT</Pill>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Duration</th>
                    <th>Type</th>
                    <th>TSS</th>
                    <th>NP</th>
                    <th>IF</th>
                    <th>HR</th>
                    <th>Durability</th>
                    <th>Quality</th>
                  </tr>
                </thead>
                <tbody>
                  {activityRows.map((activity) => (
                    <tr key={`${activity.athlete}-${activity.file}`}>
                      <td><strong>{activity.file}</strong></td>
                      <td>{fmt(activity.duration_min, 0)} min</td>
                      <td><Pill tone={activity.category === 'HIIT' ? 'violet' : 'green'}>{activity.category}</Pill></td>
                      <td>{fmt(activity.tss, 1)}</td>
                      <td>{fmt(activity.normalized_power, 1)} W</td>
                      <td>{fmt(activity.intensity_factor, 3)}</td>
                      <td>{fmt(activity.avg_hr, 0)} bpm</td>
                      <td>{activity.durability_index ? `${fmt(activity.durability_index, 1)}%` : '-'}</td>
                      <td>{pct(activity.quality_score)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {view === 'statistics' && (
          <>
            {statisticsLoading && <main className="loading">Loading statistics_page from /ride/summary...</main>}
            {statisticsError && !statisticsLoading && (
              <section className="panel full">
                <p className="error-state">{statisticsError}</p>
                <button type="button" onClick={() => void loadStatisticsFromApi()}>Retry</button>
              </section>
            )}
            {statisticsPage && !statisticsLoading && (
              <StatisticsPage
                metrics={statisticsPage}
                title={`Statistics — ${selected?.athlete ?? 'athlete'}`}
                subtitle="Fields from statistics_page (POST /ride/summary)"
              />
            )}
          </>
        )}

        {view === 'metabolic' && selected && (
          <section className="profile-grid">
            <div className="athlete-hero">
              <Pill tone="green">{selected.metabolic_status}</Pill>
              <h2>{selected.athlete}</h2>
              <p>
                Profile generated from MMP aggregated across {selected.parsed_files} files.
                Metabolic estimates are model-derived and not lab-validated.
              </p>
              {!showMetabolicValues && (
                <p className="safety-note">
                  Low metabolic confidence ({fmt(selected.metabolic_confidence, 2)} &lt; {CONFIDENCE_DISPLAY_THRESHOLD}):
                  sensitive values are masked to avoid false precision.
                </p>
              )}
              <div className="hero-stats">
                <div><span>FTP</span><strong>{fmt(selected.ftp_estimate, 1)} W</strong></div>
                <div><span>Best 20'</span><strong>{fmt(selected.best_20min, 1)} W</strong></div>
                <div><span>Total TSS</span><strong>{fmt(selected.total_tss, 0)}</strong></div>
              </div>
            </div>

            <div className="metric-card"><span>Estimated VO2max</span><strong>{formatMetabolicValue(selected.estimated_vo2max, 1, !shouldMaskField('estimated_vo2max'))}</strong><small>ml/kg/min</small></div>
            <div className="metric-card"><span>VLamax</span><strong>{formatMetabolicValue(selected.estimated_vlamax, 3, !shouldMaskField('estimated_vlamax_mmol_L_s'))}</strong><small>mmol/L/s</small></div>
            <div className="metric-card"><span>MLSS</span><strong>{formatMetabolicValue(selected.mlss_power, 1, !shouldMaskField('mlss_power_watts'))}</strong><small>watt</small></div>
            <div className="metric-card"><span>FatMax</span><strong>{formatMetabolicValue(selected.fatmax_power, 1, !shouldMaskField('fatmax_power_watts'))}</strong><small>watt</small></div>

            <div className="panel full">
              <div className="panel-header">
                <div>
                  <span>Power-duration</span>
                  <h2>Best MMP values</h2>
                </div>
              </div>
              <div className="mmp-grid">
                <KpiCard label="5 sec" value={`${fmt(selected.best_5s, 0)} W`} detail="sprint" tone="violet" />
                <KpiCard label="1 min" value={`${fmt(selected.best_1min, 0)} W`} detail="anaerobic capacity" tone="amber" />
                <KpiCard label="5 min" value={`${fmt(selected.best_5min, 0)} W`} detail="VO2max power" tone="blue" />
                <KpiCard label="20 min" value={`${fmt(selected.best_20min, 0)} W`} detail="FTP proxy" tone="green" />
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  )
}

export default App
