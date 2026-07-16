# Metabolic profiler — policy, calibration and model constants

## Purpose

The metabolic profiler now separates three kinds of values that were previously
embedded directly in `metabolic_profiler.py`:

1. **Physiological model constants** — the Mader model parameters in
   `engines/metabolic/mader_constants.py`.
2. **Empirical calibration** — tuning derived from the current production model,
   stored in `engines/metabolic/metabolic_calibration.py`.
3. **Software policy** — input limits, strategy gates and output-quality rules,
   stored in `engines/metabolic/metabolic_fit_policy.py`.

This separation is about transparency and reproducibility. It does not imply that
an empirical calibration is a universal physiological law or that the profiler's
`confidence_score` is a statistical confidence interval.

## Default objects

```python
from engines.metabolic.metabolic_calibration import DEFAULT_METABOLIC_CALIBRATION
from engines.metabolic.metabolic_fit_policy import DEFAULT_METABOLIC_FIT_POLICY
```

Both objects are frozen dataclasses. Their default values reproduce the behavior
of the profiler before this extraction.

## Creating a profiler

The existing constructor remains compatible:

```python
profiler = MetabolicProfiler(weight=72.0, context=context)
```

A research or sensitivity run can provide explicit objects:

```python
from dataclasses import replace

policy = replace(
    DEFAULT_METABOLIC_FIT_POLICY,
    version="research-bimodality-4.0",
    bimodality_threshold=4.0,
)

profiler = MetabolicProfiler(
    weight=72.0,
    context=context,
    fit_policy=policy,
)
```

Changing a default for production should always include:

- a new policy or calibration version;
- golden-regression tests;
- sensitivity analysis on representative athletes;
- documentation of the rationale and validation population.

## Snapshot configuration manifest

Joint and segmented snapshots now contain `model_configuration`:

```json
{
  "schema_version": "1.0",
  "fit_policy": {
    "version": "1.0.0",
    "classification": "software_policy"
  },
  "empirical_calibration": {
    "version": "1.0.0",
    "classification": "empirical_calibration",
    "validation_status": "internal_empirical_calibration"
  },
  "mader_constants": {
    "classification": "physiological_model_constants"
  },
  "regularization_weights": {
    "classification": "fit_regularization"
  },
  "runtime_parameters": {}
}
```

Per-call overrides are recorded without mutating the shared policy:

```json
{
  "runtime_parameters": {
    "bimodality_threshold": {
      "value": 4.0,
      "source": "argument_override"
    }
  }
}
```

The segmented aerobic-duration threshold is recorded in the same way.

## What belongs where

### `MaderConstants`

Use for parameters intrinsic to the implemented physiological/numerical Mader
model and for backward-compatible model configuration.

### `MetabolicCalibration`

Use for production tuning such as:

- APR-to-VLamax mapping;
- fit weighting and multi-start mesh;
- VO2/MLSS coherence penalties;
- inferred lactate-capacity mapping;
- PCr residual decay;
- sprint-decomposition assumptions;
- curve-generation calibration.

These values require empirical validation and must not be described as universal.

### `MetabolicFitPolicy`

Use for operational decisions such as:

- supported input ranges;
- minimum numbers of anchors;
- joint-versus-segmented gates;
- optimizer domain;
- confidence-score caps;
- output sampling and audit limits.

## Backward compatibility

- Existing calls that do not pass policy/calibration objects retain the same
  numerical results.
- Existing per-call `bimodal_threshold` and `aerobic_min_duration_s` overrides
  remain supported.
- The five representative golden profiles produce byte-identical selected
  scientific outputs before and after this phase.
- All new snapshot fields are additive.
