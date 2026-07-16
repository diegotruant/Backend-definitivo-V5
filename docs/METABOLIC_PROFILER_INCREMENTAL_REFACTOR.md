# Metabolic profiler incremental refactor — Phase 5

## Scope

This phase restructures only the joint metabolic snapshot pipeline. It does not
change physiological equations, fitting thresholds, start points, penalties,
confidence rules, output masking or public error contracts.

## Extracted stages

`MetabolicProfiler._generate_metabolic_snapshot_impl()` now coordinates five
focused internal stages:

1. `_prepare_snapshot_inputs()` — MMP normalization, optional cleaning, input
   audit and expressiveness assessment.
2. `_build_fit_context()` — arrays, weights, eta/lactate-capacity resolution,
   observed threshold anchor, grids and diagnostics shell.
3. `_fit_residuals()` / `_predict_fit_powers()` — model predictions and the
   fixed-length residual vector used by SciPy.
4. `_run_multistart_fit()` — deterministic start mesh, optimizer result audit,
   APR gating and basin selection.
5. `_build_success_snapshot()` — derived curves, validation, confidence,
   masking and serialization of the public snapshot body.

Small typed dataclasses carry data between stages:

- `_PreparedSnapshotInputs`
- `_MetabolicFitContext`
- `_MetabolicFitSelection`

They are private implementation details and do not alter the API contract.

## Invariance rule

The Phase 4 and Phase 5 implementations were run against five representative
profiles: endurance, all-rounder, explosive/segmented, incomplete endurance and
covered-but-submaximal. After removing only `calculated_at`, the complete JSON
snapshots are byte-identical.

SHA-256 for both outputs:

```text
3d020c66b814fee23b98fac6d6bd28f6fbb5b8b2c99c651cc05567969e5614a8
```

## Complexity reduction

- Previous `_generate_metabolic_snapshot_impl`: 799 lines.
- Refactored orchestration method: 101 lines.
- Branch nodes in the orchestration method: 2.

The extracted numerical stages remain visible and independently testable rather
than being hidden inside nested local functions.

## Out of scope

The 337-line `generate_metabolic_snapshot_segmented()` method is intentionally
unchanged in this phase. Refactoring it should be a separate change protected by
its existing coherence and golden tests.
