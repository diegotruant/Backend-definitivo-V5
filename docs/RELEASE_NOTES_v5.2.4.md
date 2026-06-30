# Release notes — V5.2.4

**Date:** 2026-06-30

## Summary

Closes the TwinState gap for coach-facing metabolic curves and documents the production ingest architecture (S3 → VPS → DB).

## Added

- **TwinState curve sync** — `metabolic_curves.v1` (VO₂ demand, substrate oxidation, energy-by-duration) auto-populated on twin build and profile refresh; `lactate_state.v1` from lab/Mader steps
- **`docs/METABOLIC_CURVES_TWIN_CONTRACT.md`** — frontend rendering contract (no client-side physiology recompute)
- **`docs/INGEST_PIPELINE_ARCHITECTURE.md`** — TrainingPeaks-like deploy model around the stateless API
- **`tests/pytest_mader_bimodal_behavior.py`** — 7 explicit bimodal MMP + Mader ODE behavior tests
- **`tests/pytest_metabolic_curves_twin_sync.py`** — 6 twin curve sync contract tests

## API changes

- `POST /twin/state/update-from-ride` — optional `metabolic_snapshot`, `lactate_steps`
- `POST /ride/update-profile` — returns `metabolic_curves` with refreshed snapshot
- `POST /test/in-person` — returns `lactate_persistence` when ≥3 lactate steps supplied

## Migration notes

- Persist `twin_state.metabolic_curves` from twin build/update responses; frontend Digital Twin should read curves from DB instead of calling `/profile/metabolic/curves` on every page load
- Re-build existing twins once (or run worker refresh) to backfill `metabolic_curves` if missing
- Opt out on import: `skip_metabolic_curves_sync: true` in twin build payload when weight is unknown

## Related docs

- `CHANGELOG.md` [5.2.4]
- `docs/CONTRACT_FIRST_TESTING.md`
