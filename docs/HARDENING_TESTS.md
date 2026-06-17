# Backend hardening and stress tests

This suite is intentionally stricter than the normal smoke tests. It is meant to
catch crashes, runaway loops, non-JSON payloads, NaN/Inf leakage, malformed input
handling regressions, and workload sizes that are realistic for a training
product.

## Test levels

### Smoke

Fast daily check:

```bash
make test
```

Runs only the lightweight smoke suite (fast local sanity check).

### Hardening

Robustness tests for malformed payloads, sparse sensor data, parser edge cases,
API 4xx behavior, JSON safety, and bounded execution time:

```bash
make hardening-test
```

Equivalent to:

```bash
python -m pytest -q -m "hardening" tests/pytest_hardening_*.py
```

### Stress subset

Only the heavier bounded stress cases:

```bash
make stress-test
```

Equivalent to:

```bash
python -m pytest -q -m "hardening and stress" tests/pytest_hardening_*.py
```

### Full pytest package tests

All pytest-style tests in `tests/pytest_*.py`:

```bash
make test-all
```

## What the hardening suite covers

- Parser robustness on sparse 1 Hz records, gaps, cycling dynamics, respiration,
  enhanced altitude/speed, and chart generation.
- Corrupt FIT bytes return a typed `FitFileError` when a FIT parser backend is installed.
- Workout feasibility simulation with more than one thousand steps under a
  strict wall-clock deadline.
- Workout compliance with large power streams, NaN sections, missing sensors,
  and empty activities.
- FastAPI endpoints return structured 4xx/429 errors for invalid input or abuse
  scenarios instead of
  uncaught 500s.
- Large `/workouts/compare` payloads complete within a bounded deadline.
- Every returned payload is checked recursively for JSON safety and finite
  numeric values.

## Timeout strategy

The tests use `signal.setitimer()` on Unix-like systems to fail synchronous code
paths that exceed their budget. This avoids silently accepting loops or runaway
algorithmic complexity without adding external dependencies such as
`pytest-timeout`.

## Dependency behavior

FIT binary corruption tests are skipped when no FIT parser backend is installed. In a
normal installed environment, `fitdecode` is the runtime dependency and those tests
run.

## When to run them

Run hardening tests before merging changes that touch:

- `api_app.py`
- `engines/io/fit_parser.py`
- `engines/io/activity_charts.py`
- `engines/workouts/*`
- power/MMP/metabolic engines used by workout or FIT ingestion flows

Run stress tests before releases or after changing algorithms that iterate over
samples, workout steps, or intervals.
