# Team Learning Engine

## Objective

The `Team Learning Engine` adds an auditable residual-learning layer on top of the existing physiological model.

The principle is:

```text
estimate before the test
→ validated Mader / lactate / lab test
→ observed error = measured - predicted
→ athlete / phenotype / team bias
→ new corrected estimate with cap and confidence
```

The engine does not replace Mader, Kalman, or the metabolic profiler. It learns only the residual correction, with conservative limits.

## Added file

```text
engines/metabolic/team_learning_engine.py
```

## Main concepts

### ValidationEvent

Represents an honest comparison between a prediction produced before the test and a validated value.

Key fields:

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

Contains validated events and produces:

- team accuracy statistics;
- bias per parameter;
- phenotype correction;
- athlete-specific correction;
- bounded correction applicable to a value or a metabolic snapshot.

### CorrectionConfig

Sets safety limits:

- minimum team events;
- minimum phenotype events;
- minimum athlete events;
- maximum absolute adjustment;
- maximum percentage adjustment.

Conservative defaults:

| Parameter | Absolute cap | Percentage cap |
|---|---:|---:|
| MLSS | 25 W | 5% |
| FatMax | 25 W | 7% |
| MAP | 35 W | 5% |
| VO2max | 4 ml/kg/min | 5% |
| VLamax | 0.08 mmol/L/s | 15% |

## Added endpoints

### `POST /team/calibration/update`

Adds new validated events to an existing team model or creates a new one.

Minimum payload:

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

Response: serializable model with `events` and `accuracy_report`.

### `POST /team/calibration/apply`

Applies calibration to a single parameter or to a metabolic snapshot.

Single-parameter example:

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

Snapshot example:

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

## Scientific rule

The prediction must be saved before the test. If the system sees the measured value first, the event is not useful for validating model improvement.

## Tests

Added:

```text
tests/test_team_learning_engine.py
```

Verifies:

- bounded MLSS bias learning;
- priority of athlete-specific correction when available;
- round-trip serialization;
- application to snapshot;
- helper from prediction + lab dict.
