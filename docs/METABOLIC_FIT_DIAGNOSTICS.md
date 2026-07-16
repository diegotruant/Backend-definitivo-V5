# Metabolic fit diagnostics contract

The metabolic profiler exposes a JSON-safe `fit_diagnostics` object. It describes
how the numerical fit was obtained without exposing stack traces, internal exception
messages or raw athlete data.

## Joint fit

```json
{
  "fit_method": "joint",
  "input_anchor_count": 8,
  "fit_anchor_count": 7,
  "sprint_fit_floor_s": 30.0,
  "attempted_starts": 24,
  "candidate_starts": 24,
  "converged_starts": 24,
  "nonconverged_starts": 0,
  "exception_starts": 0,
  "invalid_result_starts": 0,
  "apr_gate_applied": true,
  "candidate_pool_size": 8,
  "selected_start": [50.0, 0.5],
  "selected_residual_cost": 1234.5,
  "selected_basin_score": 2345.6,
  "selected_optimizer": {
    "converged": true,
    "status_code": 2,
    "function_evaluations": 15,
    "jacobian_evaluations": 12,
    "optimality": 0.002,
    "cost": 617.25
  }
}
```

The following invariants hold:

- `attempted_starts = candidate_starts + exception_starts + invalid_result_starts`;
- `candidate_starts = converged_starts + nonconverged_starts`;
- a candidate is accepted only when its parameter and residual arrays are finite;
- a non-converged but finite SciPy result remains auditable and is explicitly flagged.

## Segmented fit

A segmented result contains the two stage diagnostics separately:

```json
{
  "fit_method": "segmented",
  "aerobic_stage": {"fit_method": "joint"},
  "full_curve_stage": {"fit_method": "joint"},
  "combined_parameter_sources": {
    "vo2max": "aerobic_stage",
    "vlamax": "full_curve_stage"
  }
}
```

## Stable public errors

| `error_code` | Meaning |
|---|---|
| `insufficient_mmp_anchors` | Fewer than three usable MMP anchors |
| `metabolic_input_processing_failed` | Input normalization or preparation failed |
| `metabolic_fit_failed` | No finite optimizer candidate was produced |
| `metabolic_snapshot_failed` | Unexpected failure after or during model construction |
| `segmented_aerobic_fit_failed` | Aerobic stage failed |
| `segmented_full_curve_fit_failed` | Full-curve stage failed |
| `segmented_parameter_missing` | A segmented stage completed without a required parameter |

Detailed exceptions remain in server logs. Public payloads contain stable messages and
must not contain the original exception text.

## Quality flags

`model_metadata.quality_flags` can include:

- `multistart_partial_failures`;
- `selected_optimizer_not_converged`.

These flags add observability. This phase does not change the fitting objective,
physiological equations, parameter bounds or basin-selection formula.
