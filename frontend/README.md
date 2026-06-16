# Digital Twin Coach Frontend

Modern coach-facing dashboard for the Digital Twin backend reports.

## What it shows

- Coach overview dashboard
- Athlete roster
- Activity table per athlete
- Metabolic profile per athlete
- Power-duration highlights
- Data quality, TSS, FTP, NP, IF, HR, durability and metabolic estimates

## Data source

The first MVP reads the backend-generated CSV reports from:

```text
frontend/public/data/athlete_summary.csv
frontend/public/data/activity_details.csv
```

These are copied from:

```text
reports/synthetic_fit_analysis/
```

## Commands

```bash
npm install
npm run dev
npm run build
npm run lint
```

## Design direction

The interface uses a professional dark palette with blue/green accents, glass
panels, compact KPI cards and coach-oriented navigation:

- Dashboard
- Athletes
- Activities
- Metabolic profile

## Next steps

- Replace CSV loading with API endpoints when the backend is served over HTTP.
- Add athlete comparison charts.
- Add per-activity detail pages.
- Add metabolic trend views over time.
- Add authentication and coach/team workspaces.
