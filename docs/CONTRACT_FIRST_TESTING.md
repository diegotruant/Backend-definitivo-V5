# Contract-first testing

This document describes the **product-contract test methodology** used to harden Backend-definitivo-V5. It complements coverage-driven tests (`pytest_phase4_coverage_depth.py`, etc.) with tests written to **find bugs**, not mirror current implementation.

## Principle

1. Write a test that states what coaches, frontend, and API clients **must** see.
2. Run the test — a failure is a **real bug**.
3. Fix production code (engine, service, schema), not the test — unless the contract was wrong after product clarification.

## Test suites

| File | Focus | Run |
|------|-------|-----|
| `tests/pytest_engines_contract_all.py` | All `engines/*` packages, scale semantics, status codes, parametric import health | `pytest tests/pytest_engines_contract_all.py` |
| `tests/pytest_contract_full_codebase.py` | API serialization, auth, schemas, services, coach HTTP, ride/workout wire contracts | `pytest tests/pytest_contract_full_codebase.py` |
| `tests/pytest_contract_bug_hunt.py` | Readiness/compliance 0–1 vs 0–100, twin wrapping, planning validation | `pytest tests/pytest_contract_bug_hunt.py` |
| `tests/pytest_workout_pipeline_perfection.py` | Workout validate → prescribe → feasibility → compare | `pytest tests/pytest_workout_pipeline_perfection.py` |
| `tests/pytest_product_perfection_full.py` | End-to-end product chains, all 20 coach endpoints | `pytest tests/pytest_product_perfection_full.py` |
| `tests/pytest_science_contracts.py` | Scientific tier labels, fatmax/vlamax disclaimers | `pytest tests/pytest_science_contracts.py` |
| `tests/pytest_chart_output_quality.py` | **All 43 chart types** — minimal payload, no `null` in `series`, Pydantic envelope | `pytest tests/pytest_chart_output_quality.py` |
| `tests/pytest_product_output_quality.py` | **All 135 API paths** — realistic minimal payload, 200 JSON, finite floats, no null in named lists | `pytest tests/pytest_product_output_quality.py` |
| `tests/pytest_engine_output_quality.py` | **Engine entry points** — readiness, load, charts, twin, coach, registry (43 charts) | `pytest tests/pytest_engine_output_quality.py` |
| `make quality-gate` | Runs chart + API + engine product gates | `make quality-gate` |
| `tests/pytest_chart_config_registry.py` | Chart registry wiring and spot checks | `pytest tests/pytest_chart_config_registry.py` |
| `tests/pytest_performance_coach_curves.py` | W′ balance, fuel demand, recovery behavior (not just output presence) | `pytest tests/pytest_performance_coach_curves.py` |
| `tests/pytest_frontend_client_contract.py` | OpenAPI ↔ `client.ts` 1:1 (135 paths) | `pytest tests/pytest_frontend_client_contract.py` |
| `tests/pytest_openapi_contract.py` | Committed spec ↔ live `app.openapi()` | `pytest tests/pytest_openapi_contract.py` |

## What contract tests catch (examples)

| Bug class | Example contract |
|-----------|------------------|
| Scale | `readiness_score: 0.82` must not trigger `readiness_low` |
| Compliance | `compliance_score: 0.65` must not flag low compliance |
| Twin wrap | `last_compliance_results[].result.compliance_score` must be read |
| Empty data | `compute_load_trends([])` → `insufficient_data`, not success with zeros |
| Fueling parity | `session_fat_g` present when `power_series` supplied |
| Recovery honesty | `estimation_method: empirical_formula` on recovery curve |
| W′ behavior | Variable supra-CP power depletes W′ more than steady sub-CP |
| JSON safety | HTTP responses never contain `NaN` or `Infinity` |
| Chart series | No `null` entries in `series[]`; each item has `name` + plottable `x`/`y`/`data`/`values`/`r` |
| API product gate | Every OpenAPI path: 200 + no forbidden `status` + no NaN/Inf + no null in `series`/`steps`/… lists |
| Engine product gate | Public engine entry points return success bodies passing the same JSON invariants |

## Coverage tests vs contract tests

| Type | Files | Purpose |
|------|-------|---------|
| **Contract** | `pytest_*contract*`, `pytest_*perfection*` | Product truth, regression on semantics |
| **Coverage** | `pytest_phase4_coverage_depth.py`, `pytest_phase5_coverage_*.py` | Line/branch coverage, private helper paths |
| **Hardening** | `pytest_hardening_*.py` | Malformed input, 4xx not 500, timeouts |
| **Golden** | `pytest_golden_*.py`, `tests/assets/fit/` | Versioned scientific fixtures |

Coverage tests are **not useless** — they exercise edge branches. Contract tests ensure the branches mean the right thing for users.

## Critical behavior tests (not just output presence)

These areas have explicit **behavior** assertions:

- **W′ depletion** — `pytest_performance_coach_curves.py`: variable power vs steady; recovery penalty when `min_w_prime_balance_pct < 40`
- **Metabolic curves on TwinState** — `pytest_metabolic_curves_twin_sync.py`: build/update sync `metabolic_curves.v1` + `lactate_state.v1`
- **Mader / glycolytic** — `pytest_mader_bimodal_behavior.py` (bimodal segmented routing + forward ODE CP loss), `pytest_phase5_test_protocols_port.py`, `pytest_golden_scientific.py`, `pytest_fatmax_engine.py`
- **Workout pipeline** — partial prescribe resolution, compare without perfect score without power
- **Coach HTTP** — semantic contracts on all 20 `/coach/*` paths in `pytest_contract_full_codebase.py`

## Running the full gate

```bash
# Contract suites (fast, ~2 s)
pytest tests/pytest_engines_contract_all.py tests/pytest_contract_full_codebase.py tests/pytest_contract_bug_hunt.py -q

# Full product suite (~3 min)
make test-all

# Release gate
make check
```

## Adding new contract tests

When adding an engine or endpoint:

1. State the **production contract** in a test name and docstring.
2. Prefer service or HTTP layer when the bug would affect frontend.
3. Do not assert implementation details (private functions, exact heuristic constants) unless they are documented product behavior.
4. Add the endpoint to `docs/API_ENDPOINT_INDEX.md` via `make openapi-frontend`.

## Related docs

- `docs/STRENGTH_AND_FUELING_CONTRACT.md` — fueling `estimated_demands`
- `docs/COACH_DECISION_ENGINE.md` — coach endpoint contracts
- `docs/HARDENING_TESTS.md` — robustness and stress
- `engines/core/metric_contracts.py` — shared scale helpers
