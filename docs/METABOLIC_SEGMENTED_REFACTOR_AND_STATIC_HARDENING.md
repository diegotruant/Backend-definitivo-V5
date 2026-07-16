# Segmented metabolic refactor and static hardening

## Scope

This phase is structural. It does not change the default metabolic formulas,
fit thresholds, basin selection, confidence policy or public segmented payload.

The former `generate_metabolic_snapshot_segmented()` implementation combined
input preparation, stage execution, error handling, parameter assembly,
recomputation, confidence calculation and response serialization in one method.
Those responsibilities are now isolated behind private, typed stages.

## Extracted segmented stages

- `_prepare_segmented_inputs()`
- `_segmented_joint_fallback()`
- `_segmented_aerobic_stage_error()`
- `_segmented_full_stage_error()`
- `_resolve_segmented_parameter_pair()`
- `_segmented_missing_parameter_error()`
- `_calculate_segmented_confidence()`
- `_derive_segmented_outputs()`
- `_build_segmented_success_snapshot()`
- `_segmented_fit_diagnostics()`
- `_record_segmented_runtime()`

The public orchestrator is reduced from 337 lines to 63 lines. Its Radon
cyclomatic-complexity grade is B (7). The more complex confidence logic remains
in a dedicated method so it can be tested and simplified independently later.

## Invariance contract

Three representative calls were serialized with sorted keys after removing
only `calculated_at`:

1. normal segmented success;
2. joint fallback due to insufficient aerobic anchors;
3. explicit aerobic-duration override.

The Phase 5 and Phase 6 serializations are byte-identical and share SHA-256:

`416eccded4035cecb6402607ca5395f8f7fe8b0412862d174b89b5bb744df491`

The activity-normalizer fingerprint is also unchanged after declaring SHA-1 as
non-security use.

## Static analysis hardening

- Ruff passes on its configured repository scope and on every modified Python file.
- Mypy passes on all 75 configured source files.
- Bandit passes with the medium-or-higher severity threshold.
- Modified regions/files pass Black.
- `compileall` passes for `api`, `engines` and `tests`.

Supporting fixes made while closing the static-analysis findings:

- FIT stream arrays now have explicit NumPy array annotations.
- `_read_file_with_retry()` raises only a real `OSError`, never an optional value.
- A reused FIT parser local variable was renamed to remove ambiguous typing.
- SHA-1 activity fingerprints declare `usedforsecurity=False`; digest output is unchanged.
- GPX parsing uses the required `defusedxml` dependency directly.
- The phenotype demo builds its output path from `tempfile.gettempdir()`.

## Remaining debt deliberately not mixed into this patch

Bandit still reports 11 low-severity broad `except`/`pass` or `continue`
patterns in unrelated modules. They should be handled module-by-module with
logging and narrow exception types.

A repository-wide Black check is not clean: 37 API files, 3 script files and
123 test files would be reformatted. This is formatting debt, not a functional
failure, and should be addressed in a dedicated formatting-only commit to avoid
obscuring scientific changes.

## Validation environment

The package declares Python 3.11. The available execution environment for this
phase used Python 3.13.5 with Ruff, Mypy and Black configured for Python 3.11.
A CI run on the declared Python 3.11 target remains recommended before release.
