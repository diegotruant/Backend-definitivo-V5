# API examples — minimal real payloads

Copy-paste JSON for the most common flows. All paths are `POST` unless noted.

Base URL: `http://localhost:8000` (or your deployed API).

---

## Health

```http
GET /health
```

```json
{ "status": "ok", "version": "5.1.1" }
```

---

## Profile snapshot

```http
POST /profile/snapshot
Content-Type: application/json
```

```json
{
  "mmp": {
    "1": 1034,
    "15": 720,
    "60": 489,
    "180": 351,
    "360": 309,
    "720": 304,
    "1200": 280
  },
  "athlete": {
    "weight_kg": 72,
    "gender": "MALE",
    "training_years": 10,
    "discipline": "ENDURANCE"
  }
}
```

---

## Test confirm (after propose)

```json
{
  "proposal": {
    "status": "proposed",
    "confidence": 0.8,
    "sprint": { "peak_1s_w": 1034, "mean_w": 893, "duration_s": 13 },
    "cp_candidates": [
      { "target_label": "cp3", "mean_w": 349, "duration_s": 180, "cv_pct": 5.0, "maximality": 1.0, "source": "power" }
    ],
    "mmp_for_fit": { "1": 1034, "180": 349, "360": 308 },
    "warnings": [],
    "notes": []
  },
  "athlete": {
    "weight_kg": 72,
    "gender": "MALE",
    "training_years": 10,
    "discipline": "ENDURANCE"
  },
  "measured_on": "2026-05-15"
}
```

---

## In-person — Mader (lactate)

```json
{
  "test_type": "mader",
  "athlete": { "weight_kg": 72, "sex": "M" },
  "test_data": {
    "steps": [
      { "step": 1, "power_w": 150, "lactate_mmol": 1.2 },
      { "step": 2, "power_w": 200, "lactate_mmol": 1.8 },
      { "step": 3, "power_w": 230, "lactate_mmol": 2.6 },
      { "step": 4, "power_w": 260, "lactate_mmol": 4.1 },
      { "step": 5, "power_w": 290, "lactate_mmol": 6.8 },
      { "step": 6, "power_w": 320, "lactate_mmol": 10.2 }
    ],
    "mmp": { "60": 540, "300": 340, "1200": 285 }
  }
}
```

---

## In-person — Critical Power

```json
{
  "test_type": "critical_power",
  "athlete": { "weight_kg": 72 },
  "test_data": {
    "efforts": [
      { "duration_s": 180, "power_w": 360 },
      { "duration_s": 300, "power_w": 330 },
      { "duration_s": 720, "power_w": 295 }
    ]
  }
}
```

---

## Workout validate / prescribe

```json
{
  "workout": {
    "title": "2x3 VO2",
    "steps": [
      { "type": "warmup", "duration_s": 600, "target_pct_cp": 65 },
      { "type": "work", "duration_s": 180, "target_pct_cp": 115, "is_key_step": true },
      { "type": "recovery", "duration_s": 180, "target_pct_cp": 55 },
      { "type": "work", "duration_s": 180, "target_pct_cp": 115, "is_key_step": true }
    ]
  }
}
```

Prescribe adds `athlete_profile`:

```json
{
  "workout": { "...": "as above" },
  "athlete_profile": { "cp_w": 260, "weight_kg": 72, "w_prime_j": 19000 }
}
```

---

## Workout compare (multipart)

```http
POST /workouts/compare
Content-Type: multipart/form-data
```

| Field | Value |
|-------|-------|
| `workout_json` | `{"title":"...","steps":[...]}` |
| `athlete_profile_json` | `{"cp_w":260,"weight_kg":72}` |
| `power_json` | `[200,210,220,...]` |

Or send `file` (FIT) instead of `power_json`.

---

## TwinState — build

```json
{
  "payload": {
    "athlete_id": "athlete_1",
    "athlete_profile": { "weight_kg": 72, "cp_w": 260, "w_prime_j": 19000 },
    "metabolic_snapshot": {
      "status": "success",
      "vo2max": 52,
      "vlamax": 0.48,
      "mlss_watts": 260
    },
    "rolling_power_curve": { "60": 480, "300": 330, "1200": 275 }
  }
}
```

Response is a full `twin_state.v1` document — persist it client-side or in your DB.

---

## TwinState — update after ride

```json
{
  "twin_state": { "...": "full twin_state.v1 from build or DB" },
  "ride_summary": {
    "headline": { "np_w": 240 },
    "sections": { "hrv": { "alpha1_mean": 0.8 } }
  },
  "ingest_result": { "curve": { "60": 500 } },
  "ride_id": "ride_2026_06_01"
}
```

---

## TwinState — season projection

```json
{
  "twin_state": { "...": "current twin_state.v1" },
  "calendar_plan": [
    {
      "date": "2026-06-12",
      "workout": {
        "title": "Endurance",
        "steps": [{ "type": "work", "duration_s": 3600, "target_pct_cp": 75 }]
      }
    }
  ],
  "start_date": "2026-06-11",
  "target_date": "2026-06-20"
}
```

---

## Power source normalization

```json
{
  "activities": [
    { "power_source_id": "assioma", "mmp": { "60": 500, "300": 330, "1200": 270 } },
    { "power_source_id": "kickr", "mmp": { "60": 535, "300": 353, "1200": 289 } }
  ],
  "baseline_source_id": "assioma"
}
```

---

## Manual load (non-cycling)

```json
{
  "duration_min": 45,
  "rpe": 7,
  "modality": "strength",
  "notes": "Gym session"
}
```

---

## Ride summary (`statistics_page`)

`POST /ride/summary` (multipart: `power_json` or FIT `file`) now includes a flat
`statistics_page` object for the frontend stats grid:

```json
{
  "status": "success",
  "statistics_page": {
    "avg_power_w": 198.4,
    "avg_power_w_kg": 2.76,
    "np_w": 205.1,
    "np_w_kg": 2.85,
    "max_power_w": 420.0,
    "work_kj": 712.5,
    "avg_hr_bpm": 142,
    "max_hr_bpm": 168,
    "avg_cadence_rpm": 88,
    "max_cadence_rpm": 102,
    "ascent_m": 340,
    "descent_m": 320,
    "temperature_avg_c": 18.2,
    "speed_avg_kmh": 30.6,
    "moving_speed_avg_kmh": 31.2
  },
  "sections": {
    "statistics": { "status": "success", "metrics": { "...": "same fields" } }
  }
}
```

---

## TypeScript (client)

```typescript
import { api } from '@/lib/api/client';

const twin = await api.twinStateBuild({ payload: { athlete_id: 'a1', ... } });
const verdict = await api.inPersonTest({ test_type: 'mader', athlete: {...}, test_data: {...} });
```

See `docs/FRONTEND_CONNECT_NEXT_VERCEL.md` for Vercel setup.
