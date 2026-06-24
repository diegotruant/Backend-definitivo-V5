# Engine Lockdown Run Summary

## Scope

This report summarizes the first CI runs for PR #4 (`engine-audit-lockdown-v1`), which adds `tests/pytest_engine_lockdown_v1.py`.

The goal of the PR is to add a permanent safety net for the Python engine layer, not to add product features.

## Branch / PR

- Branch: `engine-audit-lockdown-v1`
- PR: #4 — `test: add engine audit lockdown suite`
- Base branch: `main`
- Base SHA at creation: `b2e0e3b179849946a0bf471ea2cee1d1537b3a6c`

## Commits tested

### Commit 1

- SHA: `6e639dc029a2e947c9b75389e16ca2421813eb29`
- Change: initial lockdown suite
- CI result:
  - `CI`: success
  - `Full backend check`: failure
- Failing job:
  - `full-check`
  - step: `Release gate (lint + typecheck + test-all + hardening)`

### Commit 2

- SHA: `7176c8276b7b8204b494aba67c65d5cdfadc47ef`
- Change: split hard gates from audit diagnostics using `pytest.mark.xfail(strict=False)`
- CI result:
  - `CI`: success
  - `Full backend check`: failure
- Rerun result:
  - `full-check`: failure again
  - failing step: `Release gate (lint + typecheck + test-all + hardening)`

## What is known

The lightweight CI passes on the PR branch.

The full release gate still fails after the diagnostic split, so this is not a transient GitHub Actions failure.

The GitHub connector output available to ChatGPT exposes the workflow/job status and setup steps, but truncates the detailed pytest failure section. No artifact was available for the failed full-check run at the time of this summary.

## Current interpretation

The PR is correctly acting as a radar: it adds coverage, and the full gate is surfacing a problem that needs more detailed visibility.

At this stage, we should not merge PR #4 into `main` until the failing full-check output is made explicit.

## Likely next action

Add a dedicated CI/reporting step for the lockdown suite so failures are visible without relying on truncated job logs.

Recommended next patch:

1. Add a workflow step that runs:
   - `python -m pytest -q tests/pytest_engine_lockdown_v1.py --tb=short`
2. Save the output to a text file.
3. Upload that file as a GitHub Actions artifact.
4. Keep the PR as draft until the full-check is green or the failing signal is classified.

## Hard gates currently intended as blockers

These tests should remain blocking:

- model safety metadata is bounded and penalizes missing inputs
- power work/kJ uses elapsed time, not sample count
- exact 3-second sprints are detected
- measured lactate capacity is clipped to plausible range
- Mader durability uses unmasked MLSS fallback
- readiness with missing inputs exposes low confidence metadata
- load risk cold-start exposes metadata
- workout recommendation blocks power targets without CP/FTP
- ability profile hides W/kg without body mass
- short load trend exposes cold-start metadata

## Audit diagnostics currently non-blocking

These tests are marked as `xfail(strict=False)` to provide signal without breaking the release gate:

- import every engine submodule, including legacy/optional modules
- data quality with minimal optional-sensor input
- season planner with non-positive weekly hours
- mechanistic Mader durability bounds on a constant above-threshold ride
- static fallback scan for high-risk 70/75 kg or 250 W literals

## Merge recommendation

Do not merge yet.

Next step is not to remove tests. Next step is to improve the CI output so the failing full-check can be diagnosed precisely.
