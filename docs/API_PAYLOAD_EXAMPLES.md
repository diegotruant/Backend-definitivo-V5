# API Payload Examples

Local base URL:

```text
http://localhost:8000
```

## GET /health

```bash
curl http://localhost:8000/health
```

Response:

```json
{
  "status": "ok",
  "service": "digital-twin-api",
  "version": "1.0.0"
}
```

---

## POST /test/propose

Multipart form:

- `files`: one or more FIT files.

```ts
const form = new FormData()
files.forEach(f => form.append('files', f))
const res = await fetch('/test/propose', { method: 'POST', body: form })
```

UI usage:

- show the proposal to the coach;
- do not save it as an anchor until the coach confirms.

---

## POST /test/confirm

Payload:

```json
{
  "proposal": {
    "...": "full output from /test/propose"
  },
  "athlete": {
    "weight_kg": 72,
    "gender": "MALE",
    "training_years": 10,
    "discipline": "ENDURANCE",
    "active_muscle_mass_kg": 32
  },
  "measured_on": "2026-06-09"
}
```

Response to save as athlete `latest_anchor`.

---

## POST /ride/ingest

Multipart form:

- `file`: FIT.
- `ride_date`: `YYYY-MM-DD`.
- `weight_kg`: number.
- `stored_curve_json`: previous curve, optional.

```ts
const form = new FormData()
form.append('file', file)
form.append('ride_date', '2026-06-09')
form.append('weight_kg', '72')
form.append('stored_curve_json', JSON.stringify(previousCurve))
const res = await fetch('/ride/ingest', { method: 'POST', body: form })
```

Response:

```json
{
  "curve": { "5": 1020, "60": 640, "300": 440, "1200": 365 },
  "mmp_for_profiler": { "60": 640, "300": 440, "1200": 365 },
  "improvements": 3,
  "ride_usable": true,
  "profile_should_refresh": true,
  "notes": []
}
```

Always save `curve`. Use `profile_should_refresh` to decide whether to regenerate the snapshot.

---

## POST /profile/snapshot

Payload:

```json
{
  "mmp": { "5": 1050, "60": 640, "300": 440, "1200": 365, "3600": 330 },
  "athlete": {
    "weight_kg": 72,
    "gender": "MALE",
    "training_years": 10,
    "discipline": "ENDURANCE"
  }
}
```

Expected UI fields:

- `estimated_vo2max`;
- `estimated_vlamax_mmol_L_s`;
- `mlss_power_watts`;
- `fatmax_power_watts`;
- `metabolic_phenotype` or `phenotype`;
- `confidence_score`;
- `combustion_curve`;
- `zones`;
- `warnings`;
- `expressiveness`.

The frontend must handle missing/null fields.

---

## POST /ride/summary

Accepts FIT or `power_json`.

Multipart form with FIT:

```ts
const form = new FormData()
form.append('file', file)
form.append('weight_kg', '72')
form.append('ftp', '330')
form.append('gender', 'MALE')
form.append('training_years', '10')
form.append('discipline', 'ENDURANCE')
form.append('metabolic_snapshot_json', JSON.stringify(snapshot))
```

Main response:

```json
{
  "status": "success",
  "stream_metadata": { "duration_s": 14400, "has_power": true, "has_hr": true },
  "sections": {
    "power": {},
    "zones": {},
    "classification": {},
    "hrv": {},
    "cardiac": {},
    "mader_durability": {}
  },
  "headline": {}
}
```

The UI must be modular: if a section is missing or `skipped`, hide the chart and show the reason.

---

## POST /ride/durability

Multipart form:

- `file` or `power_json`;
- `weight_kg`;
- `metabolic_snapshot_json`, required.

```ts
const form = new FormData()
form.append('file', file)
form.append('weight_kg', '72')
form.append('metabolic_snapshot_json', JSON.stringify(snapshot))
```

Output to display:

- residual CP;
- residual sustainable power;
- decay;
- notes/warnings.

---

## POST /test/in-person

Generic envelope payload:

```json
{
  "test_type": "mader_lactate",
  "timestamp": "2026-06-09T09:30:00Z",
  "athlete": {
    "id": "rider_01",
    "weight_kg": 72,
    "gender": "MALE",
    "training_years": 10,
    "discipline": "ENDURANCE"
  },
  "device": {
    "name": "lab_ergometer",
    "protocol_version": "team_mader_v1"
  },
  "test_data": {
    "steps": [
      { "power_w": 200, "duration_s": 300, "lactate_mmol_l": 1.4 },
      { "power_w": 250, "duration_s": 300, "lactate_mmol_l": 1.8 },
      { "power_w": 300, "duration_s": 300, "lactate_mmol_l": 2.6 },
      { "power_w": 350, "duration_s": 300, "lactate_mmol_l": 4.2 }
    ]
  }
}
```

After coach validation, create a `ValidationEvent` for the Team Learning Engine.

---

## POST /team/calibration/update

Payload:

```json
{
  "team_id": "wt_team_01",
  "calibration_model": null,
  "events": [
    {
      "athlete_id": "rider_01",
      "parameter": "mlss",
      "predicted_value": 385,
      "measured_value": 370,
      "test_date": "2026-06-09",
      "model_version": "v5",
      "protocol": "mader_lactate",
      "phenotype": "climber",
      "data_depth_score": 0.9,
      "measurement_confidence": 0.95
    }
  ]
}
```

Response: updated `calibration_model` to save in `teams.calibration_model`.

---

## POST /team/calibration/apply

Single value:

```json
{
  "calibration_model": { "...": "saved model" },
  "parameter": "mlss",
  "predicted_value": 385,
  "athlete_id": "rider_01",
  "phenotype": "climber",
  "data_depth_score": 0.9
}
```

Snapshot:

```json
{
  "calibration_model": { "...": "saved model" },
  "snapshot": { "...": "output /profile/snapshot" },
  "athlete_id": "rider_01",
  "phenotype": "climber",
  "data_depth_score": 0.9
}
```

The UI must show the correction audit, not only the final value.
