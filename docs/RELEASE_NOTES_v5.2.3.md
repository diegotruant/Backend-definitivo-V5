# Release notes — V5.2.3

**Tag:** `v5.2.3`  
**Date:** 2026-06-29  
**Base:** V5.2.2

## Summary

V5.2.3 completes the **coach decision layer** over HTTP, hardens the product with **contract-first testing** across engines and the full API stack, and closes audit gaps on **fueling INSCYD parity** (CHO + FAT grams) and **recovery formula transparency**.

## API surface — 132 OpenAPI paths

| Tag | Paths | New since 5.2.2 |
|-----|------:|-----------------|
| **coach** | **20** | Full coach decision-support layer |
| profile | 19 | +4 (metabolic curves, fatmax, etc.) |
| explainability | 8 | +2 (fatmax narratives/confidence) |
| ride | 32 | unchanged |
| workouts | 9 | unchanged |
| + 10 other tags | 44 | see `docs/API_ENDPOINT_INDEX.md` |

The typed frontend client (`frontend/src/api/client.ts`) covers **all 132 paths** 1:1 with `openapi/openapi.json` (`pytest_frontend_client_contract.py`).

## Coach layer (20 endpoints)

Documented in `docs/COACH_DECISION_ENGINE.md`. Highlights:

- `daily-brief`, `session-decision` — orchestrated coach workflow
- `decision-safety`, `attention`, `adherence`, `testing-plan`
- `strength/prescription`, `nutrition/performance-targets`
- `periodization`, `race-execution`, `communication-draft`
- Context: `pnei-context`, `endocrine-context`, `environment-adjustment`, `constraints`, `training-safety`, `equipment-comfort`, `female-athlete-context`

All communication and prescription outputs require **human coach review** (`coach_review_required`, `not_autonomous`).

## Performance fueling — INSCYD parity

`POST /coach/nutrition/performance-targets` (`performance_fueling_targets.v1`) now exposes absolute session substrate grams in `estimated_demands`:

| Field | Meaning |
|-------|---------|
| `session_carbohydrate_g` | Total modeled CHO oxidation demand (g) |
| `session_fat_g` | Total modeled fat oxidation demand (g) |
| `estimated_recovery_hours` | From `post_effort_recovery` curve when power stream supplied |
| `recovery_estimation_method` | `"empirical_formula"` when recovery curve used |

Requires `power_series` (or precomputed `metabolic_curves.session_fuel_demand`) for gram estimates. See `docs/STRENGTH_AND_FUELING_CONTRACT.md`.

## Recovery curve transparency

`build_post_effort_recovery_curve` summary now includes:

- `estimation_method: "empirical_formula"`
- `confidence_tier: "HEURISTIC"`
- `formula_note` — documents the coach-facing heuristic (not a biomarker)

Formula: `6 h + duration×8 h + intensity excess×26 h + TSS×0.10 h + W′ depletion penalty`, capped 6–72 h.

## Contract-first testing

New methodology: tests encode **product truth**; failures require engine/service fixes, not test changes.

| Suite | Tests | Scope |
|-------|------:|-------|
| `pytest_engines_contract_all.py` | 179 | Every `engines/` package + import health |
| `pytest_contract_full_codebase.py` | 75 | API plumbing, schemas, services, coach HTTP |
| `pytest_contract_bug_hunt.py` | 17 | Scale bugs (readiness/compliance 0–1 vs 0–100) |
| `pytest_workout_pipeline_perfection.py` | 29 | validate → prescribe → feasibility → compare |
| `pytest_product_perfection_full.py` | 47 | Readiness, planning, 20 coach endpoints |

Full suite: **~1843 passed** (`pytest tests/pytest_*.py`).

See `docs/CONTRACT_FIRST_TESTING.md`.

## Engine fixes (contract-driven)

- Readiness `0.8` normalized to 80% across coach, nutrition, strength, workouts, adaptive load
- Twin ride ingest updates `load_state` from TSS/training_load
- Projection seeds CTL from `chronic_load` when `ctl` absent
- `compute_load_trends([])` → `insufficient_data`
- Twin wrapped `last_compliance_results` unwrapped by coach engines
- `w_prime_kj` → joules in twin metrics

## Metric contracts (`engines/core/metric_contracts.py`)

Shared helpers:

- `normalize_readiness_score()` — 0–1 or 0–100 → 0–100
- `normalize_compliance_score()` — 0–1 or 0–100 → 0–1 fraction
- `readiness_score_from_state()` — TwinState readiness dict
- `unwrap_compliance_record()` — wrapped workout compliance rows

## Documentation updated

All docs aligned to **5.2.3** / **132 OpenAPI paths**. See `CHANGELOG.md`.

## Upgrade notes for frontend

1. Use `estimated_demands.session_fat_g` alongside `session_carbohydrate_g` on fueling cards.
2. Show `recovery_estimation_method` when displaying recovery hours from fueling.
3. Integrate coach endpoints from `docs/COACH_DECISION_ENGINE.md` — client already has all 20 paths.
4. Readiness/compliance may arrive as **fraction (0–1)** or **percent (0–100)**; backend normalizes internally — UI should send one convention consistently.
