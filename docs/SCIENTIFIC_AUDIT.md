# Scientific and mathematical audit

This document summarizes a scientific and mathematical review of the backend.
It focuses on model validity, numerical risks, implementation risks, and
high-value functions to add next.

## Executive summary

The backend has a strong scientific structure for an MVP/pre-production
analytics engine. Its most advanced part is the metabolic stack:

1. Mader-style metabolic profiling from MMP.
2. Bayesian posterior estimation for VO2max and VLamax.
3. Kalman tracking of metabolic state over time.
4. Optional residual neural correction.
5. Lab-data ingestion as a high-confidence anchor.

The codebase also covers power metrics, W' balance, HRV/DFA-alpha1, cardiac
response, durability, heat stress, training load, and workout summarization.

The main scientific limitation is not architecture; it is validation. Many
models are literature-informed and internally tested, but most tests use
synthetic data or contract/range checks. There is not yet a documented external
validation set against laboratory measurements.

## Recently fixed high-priority issues

The original audit identified five high-priority scientific bugs. They have now
been fixed in code and covered by `test_scientific_bugfixes.py`.

### 1. W' recovery formula

- Files: `w_prime_balance_engine.py`, `test_scientific_bugfixes.py`
- Previous issue: W' recovery below CP was proportional to total W' rather than
  to the remaining deficit.
- Current status: **fixed**.
- Current behavior:
  - Recovery uses `(W' - W'_bal) * (1 - exp(-dt / tau))`.
  - Balance is clamped to the available W' capacity.
  - `fully_depleted` now uses a relative percentage threshold instead of a
    fixed 100 J threshold.

### 2. Kalman test-anchor update and Mader observation model

- Files: `metabolic_kalman.py`, `test_scientific_bugfixes.py`
- Previous issue: automatic test-anchor updates could omit the profiler and
  fall back to a simplified observation model.
- Current status: **fixed**.
- Current behavior:
  - `MetabolicKalman.predict()` accepts an optional `profiler`.
  - `process_workout_history()` passes the profiler through to automatic
    test-anchor updates.
  - Regression tests verify that the profiler forward model is called.

### 3. Masked metabolic fields

- Files:
  - `cardiac_engine.py`
  - `metabolic_profiler_phenotype.py`
  - `detraining_engine.py`
  - `metabolic_current.py`
  - `test_scientific_bugfixes.py`
- Previous issue: `None` values from expressiveness masking could crash
  downstream code or silently trigger generic defaults.
- Current status: **fixed**.
- Current behavior:
  - Cardiac analysis skips MLSS cross-validation when MLSS is masked.
  - Phenotype enhancement refuses to synthesize energy contributions from
    generic defaults when VO2max or MLSS are masked.
  - Detraining returns `status: "partial"` when reliable core metabolic fields
    are unavailable.

### 4. HRV threshold power alignment

- Files: `hrv_engine.py`, `test_scientific_bugfixes.py`
- Previous issue: DFA-alpha1 window centers and power samples could be on
  different time axes.
- Current status: **fixed**.
- Current behavior:
  - RR windows can use elapsed activity time.
  - Threshold power is interpolated on explicit power timestamps when provided.
  - The fallback still works for simple 1 Hz arrays.

### 5. Durability elapsed-time handling

- Files: `durability_engine.py`, `test_scientific_bugfixes.py`
- Previous issue: removing zero-power samples compressed elapsed time and
  distorted first-hour/last-hour comparisons.
- Current status: **fixed**.
- Current behavior:
  - Durability uses elapsed-time windows.
  - Zero-power samples remain part of the timeline.
  - Regression tests verify first-hour and last-hour behavior with zeros.

## Remaining high-priority scientific risks

No known high-priority implementation bug from the original audit remains open.
The main high-priority risk is now **external validation**: the backend still
needs cohort-level comparisons against laboratory and field reference data
before model-derived outputs should be interpreted as lab-grade measurements.

## Medium-priority mathematical and numerical risks

### Bayesian VLamax prior may be too tight

- File: `bayesian_profiler.py`
- Risk: medium
- Issue: log-normal prior scaling appears to use coefficient of variation as a
  log-space standard deviation.
- Impact: VLamax posterior may be artificially constrained.
- Suggested fix: define an explicit `log_vlamax_std` parameter and document the
  prior.

### MCMC adaptation diagnostics include warmup history

- File: `bayesian_profiler.py`
- Risk: medium
- Issue: acceptance-rate adaptation is cumulative instead of window-local.
- Impact: less responsive proposal adaptation and less meaningful diagnostics.
- Suggested fix: track acceptance over the most recent adaptation interval.

### Normalized Power drift implementation should reuse the canonical NP engine

- File: `durability_engine.py`
- Risk: medium
- Issue: the NP drift calculation is not identical to the implementation in
  `power_engine.py`.
- Impact: durability NP drift may not match standard Coggan NP behavior.
- Suggested fix: call the canonical `normalized_power()` function from
  `power_engine.py`.

### Fat oxidation estimate ignores body mass

- File: `metabolic_flexibility_engine.py`
- Risk: medium
- Issue: the public function accepts `weight_kg`, but the simple formula does
  not use it.
- Impact: inter-athlete comparison is not mass-normalized.
- Suggested fix: either remove the parameter or implement a mass-specific model.

### ACWR and monotony should expose metric-contract uncertainty

- File: `training_variability_engine.py`
- Risk: medium
- Issue: ACWR thresholds are debated in current sports-science literature and
  monotony becomes unstable when daily TSS variance approaches zero.
- Impact: risk labels can be overinterpreted.
- Current status: partially addressed at architecture level by
  `metric_contracts.py`, but not yet integrated into this specific module.
- Suggested fix: attach the common `api_contract` / `uncertainty` fields and
  expose edge-case flags for near-zero TSS variance.

## Lower-priority issues

1. `engines.__init__` exports only a subset of HRV functions; threshold
   detection is not part of the public facade.
2. `neural_ode.py` describes near-zero initialization, but weights are small
   random values rather than exactly zero.
3. Thermal rise rate assumes valid samples are spaced at 1 Hz.
4. FIT parsing can overwrite multiple records that round to the same second.
5. Documentation around ExpressivenessReport coverage windows should be aligned
   exactly with the runtime thresholds.

## Scientific coverage by subsystem

### Strongest components

- Power metrics: NP, IF, TSS, FTP, zones.
- MMP and Mader-style profiling.
- Bayesian profiling and uncertainty estimates.
- Kalman/lab-anchor architecture.
- DFA-alpha1 implementation.
- Thermal and cardiac-drift feature set.

### Components that are scientifically plausible but heuristic

- Durability Index thresholds.
- Training-load decay rules.
- ACWR risk zones.
- Metabolic flexibility score.
- Pedaling-balance thresholds.
- MMP quality gates.
- Neural ODE corrections with small athlete-specific datasets.

### Components needing external validation

- VO2max estimate vs spirometry.
- VLamax estimate vs lactate protocol.
- MLSS estimate vs step test or lactate minimum test.
- FatMax estimate vs indirect calorimetry.
- DFA-alpha1 VT1/VT2 vs ventilatory thresholds.
- W' balance vs controlled interval tests.
- Thermal drift vs CORE sensor data in real heat sessions.

## Recommended functions to add

### 1. Validation and calibration layer

Add functions that compare model estimates with lab data:

- `validate_vo2max_against_lab()`
- `validate_mlss_against_lactate_test()`
- `validate_fatmax_against_indirect_calorimetry()`
- `calibrate_athlete_model_from_lab()`
- `model_error_report()`

Output should include bias, MAE, RMSE, confidence intervals, and Bland-Altman
limits of agreement where enough samples exist.

### 2. Extend unified uncertainty reporting

Initial unified uncertainty reporting now exists in `metric_contracts.py` and is
attached to several core outputs through `api_contract` and `uncertainty`
fields. The next step is to extend that contract to all remaining engines.

Already introduced:

- `MetricUncertainty`
- `MetricEnvelope`
- `ConfidenceLevel`
- `build_uncertainty()`
- `build_api_contract()`
- `annotate_payload()`
- `metric_envelope()`
- `summarize_section_contracts()`

Still recommended:

- add validation source metadata when lab data was used;
- attach intervals to more outputs, not only Bayesian summaries;
- propagate source-stream quality and sample counts into every metric;
- integrate the contract into `training_variability_engine.py`,
  `metabolic_flexibility_engine.py`, `thermal_engine.py`,
  `pedaling_balance.py`, and `lab_data.py`.

### 3. Public scientific provenance endpoint

Add a machine-readable map such as:

- `get_scientific_references()`
- `get_metric_provenance(metric_name)`
- `get_metric_reliability(metric_name)`

This can expose the contents of `docs/SCIENTIFIC_REFERENCES.md` to API clients.

### 4. Expanded HRV metrics

The README mentions HRV analysis broadly, but the current scientific emphasis is
DFA-alpha1. Add:

- RMSSD.
- SDNN.
- pNN50.
- artifact percentage.
- rolling HRV trend.
- HRV confidence/SQI at API level.

### 5. Athlete-specific W' recovery

Add:

- W' recovery tau estimation from intervals.
- Skiba/Bartram model variants.
- recovery model selection metadata.
- W'bal validation tests with known profiles.

### 6. Better power-duration models

Add optional models:

- 2-parameter CP.
- 3-parameter CP.
- Morton-style models.
- multi-segment power-duration fit.
- posterior model comparison.

This would improve MMP fitting and reduce dependence on one CP formulation.

### 7. Environmental normalization

Add functions to adjust or annotate performance for:

- temperature.
- humidity.
- altitude.
- heat acclimation state.
- dehydration proxy.

The thermal engine already gives a foundation for this.

### 8. Data lineage and audit trail

Every output metric should report:

- source streams used.
- sample count.
- dropout rate.
- cleaning applied.
- model version.
- reference papers.
- confidence tier.

This is important if the backend is used in coach-facing or medical-adjacent
contexts.

## Recommended implementation priority

1. Add lab-validation report functions.
2. Extend `metric_contracts.py` integration to every remaining engine.
3. Add scientific provenance lookup functions for API clients.
4. Expand HRV metrics and public API exports.
5. Add athlete-specific W' recovery tau estimation.
6. Add alternative power-duration models and model comparison.
7. Add environmental normalization and data-lineage metadata.

## Scientific positioning

The backend can be described as:

> A pre-production, evidence-informed cycling analytics backend that combines
> power-duration modelling, Mader-style metabolic inference, Bayesian
> uncertainty estimation, longitudinal Kalman tracking, HRV threshold analysis,
> training-load modelling, and thermal physiology. Some outputs implement
> established formulas directly, while others are heuristic or model-based
> estimates that require athlete-specific calibration and external validation
> before being interpreted as laboratory-grade measurements.

This phrasing is scientifically credible because it distinguishes implemented
models from validated measurements.
