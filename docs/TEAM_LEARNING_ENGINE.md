# Team Learning Engine

## Obiettivo

Il `Team Learning Engine` aggiunge un layer di apprendimento residuo e auditabile sopra il modello fisiologico esistente.

Il principio è:

```text
stima prima del test
→ test Mader / lattato / lab validato
→ errore osservato = misurato - predetto
→ bias atleta / fenotipo / team
→ nuova stima corretta con cap e confidenza
```

Il motore non sostituisce Mader, Kalman o il metabolic profiler. Impara solo la correzione residua, con limiti conservativi.

## File aggiunto

```text
engines/metabolic/team_learning_engine.py
```

## Concetti principali

### ValidationEvent

Rappresenta un confronto onesto fra una previsione prodotta prima del test e un valore validato.

Campi chiave:

- `athlete_id`
- `team_id`
- `parameter`: `mlss`, `vo2max`, `vlamax`, `fatmax`, `map`
- `predicted_value`
- `measured_value`
- `error_abs = measured - predicted`
- `error_pct`
- `phenotype`
- `protocol`
- `data_depth_score`
- `measurement_confidence`
- `model_version`

### TeamCalibrationModel

Contiene gli eventi validati e produce:

- statistiche di accuratezza team;
- bias per parametro;
- correzione per fenotipo;
- correzione athlete-specific;
- correzione bounded applicabile a un valore o a uno snapshot metabolico.

### CorrectionConfig

Imposta i limiti di sicurezza:

- minimo eventi team;
- minimo eventi fenotipo;
- minimo eventi atleta;
- massimo aggiustamento assoluto;
- massimo aggiustamento percentuale.

Default conservativi:

| Parametro | Cap assoluto | Cap percentuale |
|---|---:|---:|
| MLSS | 25 W | 5% |
| FatMax | 25 W | 7% |
| MAP | 35 W | 5% |
| VO2max | 4 ml/kg/min | 5% |
| VLamax | 0.08 mmol/L/s | 15% |

## Endpoint aggiunti

### `POST /team/calibration/update`

Aggiunge nuovi eventi validati a un modello team già esistente oppure ne crea uno nuovo.

Payload minimo:

```json
{
  "team_id": "wt_demo",
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

Risposta: modello serializzabile con `events` e `accuracy_report`.

### `POST /team/calibration/apply`

Applica la calibrazione a un singolo parametro oppure a uno snapshot metabolico.

Esempio parametro singolo:

```json
{
  "calibration_model": { "...": "..." },
  "parameter": "mlss",
  "predicted_value": 400,
  "athlete_id": "rider_01",
  "phenotype": "climber",
  "data_depth_score": 0.9
}
```

Esempio snapshot:

```json
{
  "calibration_model": { "...": "..." },
  "snapshot": {
    "status": "success",
    "mlss_power_watts": 400,
    "estimated_vo2max": 78,
    "estimated_vlamax_mmol_L_s": 0.42,
    "phenotype": "climber"
  },
  "athlete_id": "rider_01",
  "data_depth_score": 0.9
}
```

## Regola scientifica

La previsione deve essere salvata prima del test. Se il sistema vede prima il valore misurato, l'evento non è utile per validare il miglioramento del modello.

## Test

Aggiunto:

```text
tests/test_team_learning_engine.py
```

Verifica:

- apprendimento bias MLSS bounded;
- priorità della correzione athlete-specific quando disponibile;
- serializzazione round-trip;
- applicazione a snapshot;
- helper da prediction + lab dict.
