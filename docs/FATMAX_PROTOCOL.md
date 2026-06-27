# FATmax protocol — lab measurement vs model estimate

This document defines how the backend produces FATmax reports in
`engines/metabolic/fatmax_engine.py` and the profile endpoints
`/profile/fatmax/report`, `/profile/fatmax/lab`, and `/profile/fatmax/compare`.

## Core principle

The backend exposes **two strictly separated measurement tiers**:

| Tier | Input | MFO | Curve |
| --- | --- | --- | --- |
| `LAB_MEASURED` | Stepped VO₂/VCO₂ + power | Measured from stoichiometry | Fat/CHO g/min per step |
| `MODEL_ESTIMATE` | Metabolic snapshot / MMP | Model proxy (`mfo_tier`) | Synthetic Gaussian + logistic proxies |

The API and UI must **never** present `MODEL_ESTIMATE` outputs as indirect
calorimetry. Contract fields (`mfo_is_measured`, `mfo_is_model_proxy`,
`fatmax_interpretation`) are attached to every report.

## Scientific constants

Named in `engines/metabolic/fatmax_engine.py` (see also
`engines/core/science_contracts.py`):

| Constant | Value | Role | Reference |
| --- | --- | --- | --- |
| `IC_FAT_VO2_COEF` / `IC_FAT_VCO2_COEF` | 1.695 / 1.701 | Fat oxidation g/min from VO₂/VCO₂ | Jeukendrup & Achten 2005 |
| `IC_CHO_VCO2_COEF` / `IC_CHO_VO2_COEF` | 4.585 / 3.226 | CHO oxidation g/min | Jeukendrup & Achten 2005 |
| `FATMAX_MLSS_RATIO` | 0.68 | Field fallback when only MLSS is known | Mader 2003 contextual |
| `MAP_MLSS_RATIO` | 1.35 | MAP fallback from MLSS | Mader/MMP contextual |
| `FATMAX_BASE_THRESHOLD_FRACTION_DEFAULT` | 0.80 | Base-width band around peak fat oxidation | Protocol default |
| `FATMAX_SHIFT_RIGHT_THRESHOLD_W` | +8 W | Longitudinal right-shift classification | Coaching heuristic |
| `FATMAX_SHIFT_LEFT_THRESHOLD_W` | −8 W | Longitudinal left-shift classification | Coaching heuristic |
| `FATMAX_LAB_SMOOTH_WINDOW` | 3 | Centered moving-average window for lab fat curve | Protocol default |

## Lab curve smoothing

Before peak FATmax/MFO detection on stepped VO₂/VCO₂ data, the engine applies a
**centered moving average** (`window = 3`) to `fat_g_min`.

- Raw values are preserved as `fat_g_min_raw` on each curve point.
- Peak detection, base-width and crossover use smoothed values.
- `curve.smoothing` documents whether smoothing was applied.

Rationale: stepped lab protocols often produce single-step noise; smoothing
reduces spurious peaks without claiming additional physiological measurement.

## Carbohydrate crossover semantics

`curve.carbohydrate_crossover_w` is kept for backward compatibility.

`curve.carbohydrate_crossover` adds explicit semantics:

| `method` | Meaning |
| --- | --- |
| `indirect_calorimetry_g_min` | Lab: first step where CHO g/min ≥ fat g/min |
| `model_proxy_fraction` | Model: first step where CHO proxy ≥ fat proxy (not a lab measurement) |

## Endpoints

### `POST /profile/fatmax/lab`

- Minimum three valid gas-exchange steps (`FatmaxLabRequest.points`).
- Optional `mlss_power_w` for `%MLSS` and base-width ratio interpretation.
- Returns `measurement_tier = LAB_MEASURED`.

### `POST /profile/fatmax/report`

- Extends `MmpAthleteRequest`; optional `metabolic_snapshot` bypasses MMP rebuild.
- If snapshot must be generated and `generate_metabolic_snapshot` fails, returns
  `insufficient_data` with `reason = metabolic_snapshot_generation_failed` and
  the source snapshot payload.
- Returns `measurement_tier = MODEL_ESTIMATE` on success.

### `POST /profile/fatmax/compare`

- Requires `previous_report.summary` and `current_report.summary` objects.
- Classifies `right_shift`, `left_shift`, or `stable` using the shift thresholds.
- Appends base-width change notes when width delta exceeds ±10 W.

## Coach-facing copy

All coach interpretation strings in the engine are **English**, aligned with
`docs/COACH_UX_COPYBOOK.md` and `engines/core/science_contracts.py`.

## Regression tests

- `tests/pytest_fatmax_engine.py` — stoichiometry, lab/model tiers, compare logic
- `tests/pytest_fatmax_api.py` — HTTP smoke and validation
- `tests/pytest_fatmax_explainability.py` — lab smoothing + explainability narratives
- `tests/pytest_science_contracts.py` — `fatmax_contract_fields`

## Explainability endpoints

| Endpoint | Input | Output |
| --- | --- | --- |
| `POST /explainability/fatmax-narrative` | Full FATmax report JSON | Coach narrative string |
| `POST /explainability/fatmax-confidence` | Full FATmax report JSON | Confidence level, factors, limitations |
| `POST /explainability/workout-summary-narrative` | Workout summary with optional `sections.fatmax` | Master narrative including FATmax when present |

`build_workout_summary()` attaches `sections.fatmax` (model estimate) whenever a
successful metabolic snapshot is available for the activity.

## Implementation reference

- `engines/metabolic/fatmax_engine.py`
- `engines/core/science_contracts.py` — `fatmax_contract_fields()`
- `api/services/profile_extended_service.py` — orchestration
- `api/routers/profile_extended.py`
