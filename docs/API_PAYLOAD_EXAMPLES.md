# API Payload Examples

Base URL locale:

```text
http://localhost:8000
```

## GET /health

```bash
curl http://localhost:8000/health
```

Risposta:

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

- `files`: uno o più file FIT.

```ts
const form = new FormData()
files.forEach(f => form.append('files', f))
const res = await fetch('/test/propose', { method: 'POST', body: form })
```

Uso UI:

- mostrare proposta al coach;
- non salvare come anchor finché il coach non conferma.

---

## POST /test/confirm

Payload:

```json
{
  "proposal": {
    "...": "output completo di /test/propose"
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

Risposta da salvare come `latest_anchor` atleta.

---

## POST /ride/ingest

Multipart form:

- `file`: FIT.
- `ride_date`: `YYYY-MM-DD`.
- `weight_kg`: number.
- `stored_curve_json`: curva precedente, opzionale.

```ts
const form = new FormData()
form.append('file', file)
form.append('ride_date', '2026-06-09')
form.append('weight_kg', '72')
form.append('stored_curve_json', JSON.stringify(previousCurve))
const res = await fetch('/ride/ingest', { method: 'POST', body: form })
```

Risposta:

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

Salvare sempre `curve`. Usare `profile_should_refresh` per decidere se rigenerare snapshot.

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

Campi UI attesi:

- `estimated_vo2max`;
- `estimated_vlamax_mmol_L_s`;
- `mlss_power_watts`;
- `fatmax_power_watts`;
- `metabolic_phenotype` o `phenotype`;
- `confidence_score`;
- `combustion_curve`;
- `zones`;
- `warnings`;
- `expressiveness`.

Il frontend deve gestire campi mancanti/null.

---

## POST /ride/summary

Accetta FIT o `power_json`.

Multipart form con FIT:

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

Risposta principale:

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

La UI deve essere modulare: se una sezione manca o è `skipped`, nascondere il grafico e mostrare il motivo.

---

## POST /ride/durability

Multipart form:

- `file` o `power_json`;
- `weight_kg`;
- `metabolic_snapshot_json`, obbligatorio.

```ts
const form = new FormData()
form.append('file', file)
form.append('weight_kg', '72')
form.append('metabolic_snapshot_json', JSON.stringify(snapshot))
```

Output da visualizzare:

- CP residua;
- potenza sostenibile residua;
- decadimento;
- note/warning.

---

## POST /test/in-person

Payload envelope generico:

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

Dopo la validazione coach, creare `ValidationEvent` per il Team Learning Engine.

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

Risposta: `calibration_model` aggiornato da salvare su `teams.calibration_model`.

---

## POST /team/calibration/apply

Singolo valore:

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

La UI deve mostrare l'audit della correzione, non solo il valore finale.
