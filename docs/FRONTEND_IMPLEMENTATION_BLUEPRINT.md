# Frontend Implementation Blueprint — WT Physiological Digital Twin

## 1. Frontend mission

The frontend must make a very deep physiological backend understandable to three different users:

1. **Coach** — wants to know what to do in training tomorrow.
2. **Performance scientist** — wants to know how accurate the model is and why.
3. **Sport director / management** — wants to understand team status, availability, and race role.

Developers must not invent cycling interpretations: they must use the contracts, metric dictionaries, and UX rules below.

---

## 2. Recommended application architecture

### Suggested stack

- React + TypeScript.
- Chart library: Recharts, ECharts, or Nivo.
- State: TanStack Query for APIs + Zustand/Redux only if needed.
- Form: React Hook Form.
- Tables: TanStack Table.
- Backend base URL configurable via `.env`.

### Recommended folders

```text
frontend/src/
  api/
    client.ts
    endpoints.ts
  contracts/
    athlete.ts
    profile.ts
    activity.ts
    testing.ts
    teamLearning.ts
  dictionary/
    metricDictionary.ts
    coachCopy.ts
  components/
    kpi/
    charts/
    quality/
    layout/
  pages/
    TeamCommandCenter.tsx
    AthleteDigitalTwin.tsx
    ActivityAnalysis.tsx
    TestingLab.tsx
    ModelAccuracy.tsx
    CoachPlanner.tsx
    DataQualityCenter.tsx
  mocks/
    mockData.ts
```

---

## 3. Frontend/database data model

The backend is stateless. An external DB is required. Minimum tables:

### `teams`

| Field | Type | Notes |
|---|---|---|
| `id` | string | team id |
| `name` | string | team name |
| `calibration_model` | jsonb | output `/team/calibration/update` |
| `created_at` | timestamp | |

### `athletes`

| Field | Type | Notes |
|---|---|---|
| `id` | string | athlete id |
| `team_id` | string | FK |
| `name` | string | |
| `weight_kg` | number | updateable |
| `gender` | string | value for physiological model |
| `training_years` | number | |
| `discipline` | string | ENDURANCE, ROAD, TT, etc. |
| `phenotype` | string | from snapshot or coach |
| `latest_anchor` | jsonb | output `/test/confirm` |
| `latest_curve` | jsonb | output `/ride/ingest` |
| `latest_snapshot` | jsonb | output `/profile/snapshot` or calibrated |

### `activities`

| Field | Type | Notes |
|---|---|---|
| `id` | string | |
| `athlete_id` | string | |
| `date` | date | |
| `fit_file_url` | string | storage |
| `summary` | jsonb | output `/ride/summary` |
| `durability` | jsonb | output `/ride/durability` |
| `mmp_for_profiler` | jsonb | from ingest |
| `profile_should_refresh` | boolean | |

### `validation_events`

Each validated test must save the prior prediction.

| Field | Type | Notes |
|---|---|---|
| `id` | string | |
| `team_id` | string | |
| `athlete_id` | string | |
| `parameter` | string | mlss, vo2max, vlamax, fatmax, map |
| `predicted_value` | number | estimate before test |
| `measured_value` | number | validated test value |
| `error_abs` | number | measured - predicted |
| `error_pct` | number | |
| `protocol` | string | mader_lactate, lab_vo2, wingate |
| `phenotype` | string | climber, sprinter, etc. |
| `data_depth_score` | number | 0-1 |
| `measurement_confidence` | number | 0-1 |
| `model_version` | string | backend/model version |
| `test_date` | date | |

---

## 4. Main pages

# 4.1 Team Command Center

## Purpose

Initial view for WT staff. It must answer within 10 seconds:

- Who is ready?
- Who has physiological warnings or poor data quality?
- Is the model improving?
- Which athletes should be tested?

## Layout

### Header

- Team name.
- Last sync date.
- Number of athletes.
- Badge: `Team calibration: None / Learning / Calibrated / High confidence`.

### KPI cards

1. Athletes with green profile.
2. Athletes with yellow warning.
3. Athletes with red warning.
4. Team MLSS MAE.
5. Number of validated tests in the last 90 days.
6. Athletes to retest.

### Athlete table

Columns:

- Athlete name.
- Phenotype.
- MLSS W/kg.
- VO2max.
- VLamax.
- Durability score.
- Data depth.
- Last test.
- Model status.
- Recommended action.

### Charts

- Bar chart: athlete status by color.
- Line chart: MLSS accuracy over time.
- Scatter: MLSS W/kg vs durability score.
- Bar chart: missing tests per athlete.

---

# 4.2 Athlete Digital Twin

## Purpose

The most important page. It must show the athlete's physiological twin.

## Sections

### A. Athlete header

- Name.
- Role/phenotype.
- Weight.
- Last update.
- Profile confidence.
- Last anchor: test type and date.

### B. Physiological KPIs

Show 6 cards:

1. MLSS W.
2. MLSS W/kg.
3. VO2max.
4. VLamax.
5. FatMax W.
6. MAP W.

Each card must have:

- value;
- unit;
- badge: measured/model/calibrated/low confidence;
- trend vs latest snapshot;
- tooltip "what it means for the coach".

### C. Metabolic map

Recommended chart:

- X-axis: power W;
- lines/areas: fats, carbohydrates, lactate contribution, or combustion curve;
- vertical markers: FatMax, MLSS, MAP.

If the backend does not provide a full curve, show a simplified zone-based view.

### D. Power duration curve

- logarithmic X-axis: duration 5s, 15s, 1m, 5m, 20m, 60m;
- Y-axis: watts or W/kg;
- current curve;
- previous bests;
- highlighted missing points.

### E. Expressiveness checklist

Show whether the profile is built on complete data:

- 5-15 s sprint: present/missing;
- 20-60 s glycolytic: present/missing;
- 3-12 min VO2max: present/missing;
- 20-60 min threshold: present/missing.

If a window is missing, do not blame the user: show "A targeted test is needed".

### F. Learning audit

If team calibration has been applied:

- base model value;
- athlete correction;
- phenotype correction;
- team correction;
- final value;
- applied cap;
- confidence.

UI example:

```text
Final MLSS: 372 W
Base model: 380 W
Athlete correction: -5 W
Phenotype correction: -2 W
Team correction: -1 W
Expected error: ±8 W
```

---

# 4.3 Activity Analysis

## Purpose

Analyze a single ride or race.

## Input

- FIT file or already uploaded activity.
- Athlete weight.
- Optional FTP/MLSS.
- Optional metabolic snapshot.

## Sections

### A. Summary cards

- Duration.
- Distance.
- Elevation gain.
- NP.
- IF.
- TSS.
- Work kJ.
- VI.

### B. Timeline

Multi-series chart:

- power;
- heart rate;
- cadence;
- altitude;
- core temperature if available.

### C. Zone distribution

- time in power zones;
- time in metabolic zones;
- comparison between workout target and actual.

### D. Cardiac response

If HR is present:

- cardiac drift;
- aerobic decoupling;
- HR recovery;
- cardiac efficiency.

Traffic light:

- green: stable;
- yellow: moderate drift;
- red: high drift / possible fatigue or heat.

### E. Durability

Show:

- estimated residual CP;
- sustainable power after fatigue;
- decay curve;
- coach interpretation.

Suggested sentence:

> The athlete maintains good sustainable capacity after accumulated load: a positive indicator for long races.

---

# 4.4 Testing Lab

## Purpose

Allow staff to upload tests, validate them, and create anchors.

## FIT test flow

1. Upload 1+ FIT files.
2. Call `/test/propose`.
3. Show proposal:
   - files used;
   - best segments found;
   - sprint;
   - CP/MMP;
   - warnings.
4. Coach confirms or rejects.
5. If confirmed: `/test/confirm`.
6. Save anchor in DB.

## In-person/lactate flow

1. Tablet/test form:
   - protocol;
   - athlete;
   - power/lactate steps;
   - device;
   - notes.
2. Call `/test/in-person`.
3. Show result.
4. If validated, create `ValidationEvent` for Team Learning.

## Essential rule

Before saving the measured value, save the model prediction. Without pre-test prediction, scientifically valid learning does not exist.

---

# 4.5 Model Accuracy & Learning

## Purpose

This is the page that makes the product unique.

It must show that the system is not a black box: it knows its own error.

## KPI

For each parameter:

- N validated tests;
- mean bias;
- MAE;
- RMSE if available;
- error %;
- confidence;
- status: insufficient / learning / calibrated.

## Charts

1. Line chart: MLSS error over time.
2. Bar chart: MAE by parameter.
3. Scatter: predicted vs measured.
4. Bar chart: correction by phenotype.
5. Table: validated events.

## Events table

Columns:

- Date.
- Athlete.
- Parameter.
- Predicted.
- Measured.
- Error.
- Protocol.
- Phenotype.
- Data quality.
- Model version.

## Important copy

Use this sentence on the page:

> The model is calibrated only with validated tests. Every correction is bounded by conservative physiological thresholds and tracked in the audit.

---

# 4.6 Coach Planner

## Purpose

Translate the profile into practical targets.

## Sections

### A. Target zones

- endurance;
- FatMax;
- tempo;
- MLSS;
- VO2max;
- anaerobic/sprint.

### B. Training focus

Generate cards from simple rules:

- High VLamax + GC goal: focus endurance/threshold, limit glycolytic work.
- Low VLamax + sprint need: include neuromuscular work.
- Stable MLSS + low durability: long sessions with final blocks.
- High cardiac drift: base endurance/recovery/heat/hydration check.

### C. Race role suggestion

It must not decide automatically, but suggest:

- GC/climber;
- endurance domestique;
- lead-out;
- sprinter;
- breakaway rider;
- TT specialist.

---

# 4.7 Data Quality Center

## Purpose

Avoid decisions based on poor data.

## Checklist

- Power present?
- HR present?
- RR present?
- Cadence present?
- Temperature/core temp present?
- Stable power meter?
- Complete MMP?
- Recent last test?
- Reliable latest anchor?
- Calibrated snapshot?

## Output

Global traffic light:

- Green: sufficient data.
- Yellow: use caution.
- Red: test required.

---

## 5. Physiological design system

### Traffic-light colors

- Green: reliable / OK.
- Yellow: caution / incomplete data.
- Red: unreliable / test required.
- Blue: physiological model.
- Purple: learned calibration.
- Gray: not available.

### Mandatory badges

- `Measured`
- `Standard formula`
- `Model estimate`
- `Team calibrated`
- `Low confidence`
- `Insufficient data`
- `Experimental`

### Mandatory tooltips

Every advanced metric must have a tooltip:

1. what it means;
2. how to use it;
3. which data it comes from;
4. how reliable it is.

---

## 6. Charts to implement

| Chart | Page | Type |
|---|---|---|
| Power duration curve | Athlete Digital Twin | line, x log |
| Combustion curve | Athlete Digital Twin | stacked area / line |
| Zone distribution | Activity Analysis | stacked bar / donut |
| Activity timeline | Activity Analysis | multi-line |
| Durability decay | Activity Analysis | line |
| Predicted vs measured | Model Accuracy | scatter |
| Error over time | Model Accuracy | line |
| MAE by parameter | Model Accuracy | bar |
| Team athlete status | Command Center | bar |
| Data completeness | Data Quality | checklist/radar |

---

## 7. Endpoint usage recipes

### Create profile from FIT test

```ts
const proposal = await api.proposeTest(files)
// coach review screen
const anchor = await api.confirmTest({ proposal, athlete, measured_on })
storeAthleteAnchor(anchor)
```

### Import activity

```ts
const ingest = await api.ingestRide({ file, ride_date, weight_kg, stored_curve_json })
storeCurve(ingest.curve)
if (ingest.profile_should_refresh) {
  const snapshot = await api.profileSnapshot({ mmp: ingest.mmp_for_profiler, athlete })
  storeSnapshot(snapshot)
}
```

### Apply team calibration

```ts
const calibrated = await api.applyTeamCalibration({
  calibration_model: team.calibration_model,
  snapshot,
  athlete_id: athlete.id,
  phenotype: athlete.phenotype,
  data_depth_score: snapshot.confidence_score ?? 1
})
```

### Update team calibration after validated test

```ts
const updatedModel = await api.updateTeamCalibration({
  team_id: team.id,
  calibration_model: team.calibration_model,
  events: [validationEvent]
})
storeTeamCalibration(updatedModel)
```

---

## 8. Anti-error rules for developers

1. Do not compute physiology in the frontend.
2. Do not invent missing values.
3. Do not hide severe warnings.
4. Do not confuse FTP with MLSS.
5. Do not show VO2max/VLamax as measured when they are estimated.
6. Do not apply team calibration if `calibration_model` is empty.
7. Do not use validated tests without saving pre-test prediction.
8. Do not show charts without units.
9. Do not aggregate athletes with different units without normalizing W/kg.
10. Do not claim "the model never fails". Use "expected error reduced and tracked".

---

## 9. Definition of Done for the first serious frontend

The first release is acceptable if it includes:

- Login/team selector, even mocked.
- Athlete list.
- FIT upload for tests.
- FIT upload for rides.
- Athlete Digital Twin with KPI and warnings.
- Activity Analysis with summary and zones.
- Testing Lab with coach confirmation.
- Model Accuracy with at least events table and MAE by parameter.
- JSON persistence for anchor, curve, snapshot, calibration model.
- Metric tooltips.
- Loading/error/empty states.

It is not necessary to have all advanced charts immediately. It is necessary to avoid miscommunicating physiology.
