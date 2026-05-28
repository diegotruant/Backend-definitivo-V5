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

## High-priority bugs and scientific risks

### 1. W' recovery formula likely overestimates recovery

- File: `w_prime_balance_engine.py`
- Risk: high
- Issue: W' recovery below CP appears proportional to total W' rather than to
  the remaining deficit `(W' - W'_bal)`.
- Why it matters: W' balance is used to estimate depletion and recovery during
  intervals. A wrong recovery equation can systematically distort interval
  readiness and "fully depleted" flags.
- Suggested fix:
  - Use `recovery = (w_prime - current_balance) * (1 - exp(-dt / tau))`.
  - Clamp balance to `[0, w_prime]`.
  - Add a deterministic test against a known W'bal profile.

### 2. Kalman update does not consistently use the Mader observation model

- File: `metabolic_kalman.py`
- Risk: high
- Issue: the automatic daily update path can call the Kalman update without
  passing the metabolic profiler, so the observation model may fall back to a
  simplified exponential approximation rather than the documented Mader forward
  model.
- Why it matters: the posterior VO2max/VLamax update can diverge from the
  mathematical model described in the README and tests.
- Suggested fix:
  - Pass the profiler through `predict()` and `process_workout_history()`.
  - Add tests showing that test anchors use the Mader observation model when a
    profiler is provided.

### 3. Masked metabolic fields can crash or produce default-based outputs

- Files:
  - `cardiac_engine.py`
  - `metabolic_profiler_phenotype.py`
  - `detraining_engine.py`
  - `metabolic_current.py`
- Risk: high
- Issue: the expressiveness gate can return `status == "success"` while some
  fields such as `mlss_power_watts`, `estimated_vo2max`, or VLamax are `None`.
  Some downstream modules cast these values to float or replace missing values
  with generic defaults.
- Why it matters:
  - Potential runtime exceptions.
  - Silent production of physiologically misleading values.
  - Frontend/API consumers may receive apparently precise values derived from
    defaults rather than measured or model-supported data.
- Suggested fix:
  - Treat masked fields as unavailable, not as generic defaults.
  - Return `status: "partial"` or explicit `reliability` metadata.
  - Use `unmasked_estimates` only for audit/debug, not for coach-facing values.

### 4. HRV threshold detection can misalign RR time and power time

- File: `hrv_engine.py`
- Risk: high
- Issue: DFA-alpha1 window centers are derived from cumulative RR time, while
  power is indexed as if the RR stream starts exactly at activity second zero.
- Why it matters: if HR data starts late, has gaps, or is offset from power,
  estimated VT1/VT2 power can be wrong.
- Suggested fix:
  - Use explicit FIT timestamps or elapsed seconds for RR and power.
  - Interpolate power on the RR timeline instead of direct array indexing.

### 5. Durability metrics compress time by removing zero-power samples

- File: `durability_engine.py`
- Risk: high
- Issue: removing all zero-power samples before first-hour/last-hour comparison
  compresses the timeline.
- Why it matters: stops, descents, traffic lights, or coasting can make the
  "first hour" and "last hour" no longer represent real hours.
- Suggested fix:
  - Keep the original 1 Hz timeline.
  - Use moving-time masks if needed, but preserve elapsed-time windows.

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

### ACWR and monotony should expose uncertainty and caveats

- File: `training_variability_engine.py`
- Risk: medium
- Issue: ACWR thresholds are debated in current sports-science literature and
  monotony becomes unstable when daily TSS variance approaches zero.
- Impact: risk labels can be overinterpreted.
- Suggested fix: expose `method: heuristic`, confidence, and edge-case flags.

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

### 2. Stronger uncertainty reporting

Add a unified uncertainty object:

- point estimate
- lower/upper interval
- method
- reliability tier
- input coverage
- reason for masking
- validation source, if present

This should be used by metabolic, HRV, cardiac, durability, and thermal
outputs.

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

1. Fix W' recovery formula and tests.
2. Fix Kalman profiler pass-through.
3. Add strict handling for masked metabolic values.
4. Preserve elapsed time in durability metrics.
5. Align RR and power timelines for DFA threshold detection.
6. Add lab-validation report functions.
7. Add unified uncertainty/provenance objects.
8. Expand HRV metrics and public API exports.

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
