# Production readiness assessment — V5.2.6

Assessment of backend readiness for production-style deployment (stateless API behind TLS, workers, optional auth). This is not a formal certification — it tracks known gates, fixed regressions, and remaining risks.

**Baseline:** 135 OpenAPI paths, 43 chart types, ~2275 pytest tests in full suite.

## Release gate status

| Gate | Command | Status |
|------|---------|--------|
| Lint | `make lint` | ✅ Green on `main` branch |
| Typecheck | `make typecheck` | ✅ Green |
| Full pytest | `make test-all` | ✅ ~2275 passed |
| Hardening | `make hardening-test` | ✅ Green (see fixes below) |
| Product quality | `make quality-gate` | ✅ 135 paths + 43 charts |
| OpenAPI ↔ client | `pytest_frontend_client_contract.py` | ✅ 1:1 |

## Hardening parser — tracked items

| # | Issue | Status | Evidence |
|---|-------|--------|----------|
| 1 | Sparse sensor records + cycling dynamics must not crash parser or charts | ✅ Fixed | `test_parser_sparse_sensor_records_cycling_dynamics_and_gaps_do_not_crash` |
| 2 | Corrupt FIT bytes return typed `FitFileError`, not 500 | ✅ Fixed | `test_parser_returns_typed_error_for_corrupt_fit_bytes_when_backend_is_available` |
| 3 | Chart builders on mixed streams must be JSON-safe (no NaN/Inf) | ✅ Covered | Asserted in test #1 chart loop |
| 4 | Large RR streams (~13.8k s) must finish HRV path with adaptive windowing | ✅ **Fixed — coverage verified** | `test_large_rr_workout_summary_adapts_hrv_window_count_and_finishes` in `pytest_hardening_parser.py`; complementary HTTP path in `pytest_hardening_api.py::test_ride_summary_large_rr_stream_uses_adaptive_hrv_step_and_stays_bounded`; two-phase scheduler branches in `pytest_workout_summary_two_phase.py` |
| 5 | Full bundle manifest must surface missing physiology without silent skip | ✅ Covered | `pytest_full_activity_bundle_contract.py` |

### Hardening item #4 — resolution detail

**Problem:** Endurance FIT files with one RR beat per second created excessive DFA windows; workout summary HRV could time out or block the release gate.

**Fix:** Adaptive HRV scheduling in `build_workout_summary` — `hrv_max_windows` cap, `adaptive_step_applied`, sparse/dense step modes, preservation of all RR beats with explicit warning.

**Verification:**

```bash
pytest tests/pytest_hardening_parser.py::test_large_rr_workout_summary_adapts_hrv_window_count_and_finishes -q
pytest tests/pytest_hardening_api.py::test_ride_summary_large_rr_stream_uses_adaptive_hrv_step_and_stays_bounded -q
pytest tests/pytest_workout_summary_two_phase.py -q
```

All complete within deadline budgets (`deadline(18.0)` engine, bounded HTTP).

## Production deployment checklist

| Item | Ready | Notes |
|------|-------|-------|
| Docker image | ✅ | Non-root, `pip install .`, `/health` probe |
| Env template | ✅ | `.env.example` — CORS, auth, rate limits |
| Auth modes | ✅ | `none` / `api_key` / `jwt` — `docs/DEPLOY_BACKEND.md` |
| Rate limiting | ✅ | Per-process sliding window; document edge caps for multi-worker |
| Stateless contract | ✅ | TwinState round-trip documented |
| Ingest worker spec | ✅ | `docs/INGEST_PIPELINE_ARCHITECTURE.md` |
| Secrets in repo | ✅ | None committed |

## Intentionally out of scope (application layer)

| Component | Owner |
|-----------|-------|
| Database / migrations | Frontend / platform team |
| Job queue for async ingest | Platform team |
| User management UI | Frontend |
| Email / push notifications | Platform team |

Backend returns JSON envelopes; persistence is client responsibility.

## Remaining risks (non-blocking for API release)

1. **Workout compliance V1** — sequential alignment only; outdoor pauses may need V2 interval matching.
2. **Per-process rate limits** — scale workers → scale effective quota; use gateway limits in production.
3. **Optional FIT parser backend** — corrupt-file test skips when no parser wheel installed in dev env.
4. **Experimental tiers** — `EXPERIMENTAL` metrics should stay hidden or in Labs UI.

## Recommendation

The backend is **ready for production-style API deployment** behind the documented Docker/TLS/worker setup. Hardening parser item **#4 is resolved and covered by dedicated tests** — no open blocker on large RR endurance files.

Before customer launch:

1. Run `make check` on release tag.
2. Configure `DIGITAL_TWIN_AUTH_MODE` and CORS for your domain.
3. Point ingest workers at `POST /ride/full-bundle` for canonical activity reports.
4. Monitor `/health` and 5xx rate at the gateway.

---

*Assessment V5.2.6 — last aligned with 135 OpenAPI paths, 43 chart types, ~2275 tests.*
