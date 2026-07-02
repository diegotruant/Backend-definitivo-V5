# Health daily sync contract (HRV + calories)

Contract between the **athlete mobile app** (Oura, Google Health / Health Connect on Android) and the backend VPS.

The app team owns SDK integration and sync; the backend owns interpretation for coach dashboards.

## Data flow

```text
Oura API / Health Connect (Android)
        ↓
Athlete app (normalizes vendor JSON)
        ↓
POST /integrations/health/daily-energy  (+ existing POST /readiness/today for HRV/sleep)
        ↓
Postgres / TwinState
        ↓
Coach UI (energy load, fuelling context)
```

HRV and sleep continue to use `POST /readiness/today` with loose `hrv_status` / `sleep_status` dicts (`score` 0–1). Daily calories use the endpoint below.

## Endpoint

| Method | Path | Schema |
|--------|------|--------|
| POST | `/integrations/health/daily-energy` | `daily_energy.v1` |

## Request (athlete app → backend)

```json
{
  "health_daily": {
    "date": "2026-06-17",
    "source": "google_health",
    "total_calories_kcal": 3050,
    "active_calories_kcal": 980,
    "basal_calories_kcal": 1680,
    "steps": 11200
  },
  "athlete": {
    "weight_kg": 78,
    "height_cm": 178,
    "age": 35,
    "gender": "MALE",
    "occupation_load": "physical_job"
  },
  "training_calories_kcal": 320,
  "load_state": {
    "acute_load": 55,
    "chronic_load": 48
  }
}
```

### Vendor key aliases (normalized server-side)

| Canonical | Google Health / Health Connect | Oura (examples) |
|-----------|-------------------------------|-----------------|
| `total_calories_kcal` | `totalEnergyBurned` | `total_calories` |
| `active_calories_kcal` | `activeEnergyBurned` | `active_calories` |
| `basal_calories_kcal` | `basalEnergyBurned` | `bmr_kcal` |

If only `active_calories_kcal` + `basal_calories_kcal` are sent, total is derived.

## Response (summary)

```json
{
  "status": "success",
  "schema_version": "daily_energy.v1",
  "not_a_diet": true,
  "reported": {
    "total_calories_kcal": 3050,
    "active_calories_kcal": 980,
    "basal_calories_kcal": 1680
  },
  "derived": {
    "non_training_active_kcal": 660,
    "training_calories_kcal": 320,
    "total_per_kg": 39.1
  },
  "classifications": {
    "daily_energy_load": "high",
    "physical_job_load": "moderate",
    "occupation_hint": "physical_job"
  },
  "coach_flags": ["high_non_training_load"],
  "nutrition_energy_context": {
    "energy_availability_risk": "low",
    "high_non_training_load": true
  },
  "coach_notes": [],
  "red_flags": [],
  "limitations": []
}
```

## Coach semantics

| Field | Meaning |
|-------|---------|
| `daily_energy_load` | Overall burn vs body mass (`low` … `very_high`) |
| `physical_job_load` | Non-training active burn (`sedentary` … `very_high`) |
| `coach_flags.high_non_training_load` | ≥700 kcal active outside logged training — e.g. manual labour |
| `nutrition_energy_context` | Feeds `POST /coach/endocrine/context` via TwinState |

**Not in scope:** meal plans, macro prescriptions, medical nutrition therapy.

## TwinState

Pass the response as `daily_energy` on `POST /twin/state/build` → `daily_energy_state.v1`.

## Related

- `docs/STRENGTH_AND_FUELING_CONTRACT.md` — session fueling targets
- `POST /readiness/today` — HRV/sleep/load readiness score
- `POST /coach/nutrition/performance-targets` — bike session CHO/FAT availability
