# Security Hardening — V5.1

This pass closes the input-boundary risks found in the pre-production audit.
All engine-level code was already clean (no `eval`/`exec`/`pickle`/`subprocess`,
temp files via `NamedTemporaryFile`, NaN/Inf sanitised). The fixes below target
the HTTP/ingestion boundary, consistent with the stateless design.

## Fixes applied

| # | Severity | Risk | Fix | Where |
|---|----------|------|-----|-------|
| 1 | High | XML entity-expansion / XXE on untrusted GPX | `defusedxml` parser + size cap | `engines/performance/race_prediction_engine.py` |
| 2 | High | Unbounded upload size + file count → memory DoS | `enforce_upload_size`, file-count cap, body-size middleware | `api_app.py`, `engines/core/security.py` |
| 3 | High | Unbounded projection compute (`max_days`, calendar length) | `Field(ge=1, le=MAX_PROJECTION_DAYS)`, `max_length` | `api_app.py` |
| 4 | Medium | Error messages leaked internals / attacker-controlled filename | `safe_error_detail`, server-side logging only | `api_app.py` |
| 5 | Medium | Inline `power_json` could be arbitrarily long | `MAX_POWER_SAMPLES` cap | `api_app.py` |
| 6 | Low | Deeply nested JSON → recursion exhaustion | `assert_json_depth` guard | `api_app.py`, `engines/core/security.py` |
| 7 | Low | No CORS policy | Explicit allowlist middleware (closed by default) | `api_app.py` |

## Still the product layer's responsibility (by design)

Authentication, authorization/roles, rate limiting, persistent storage, job
queue, GDPR/consent, model versioning in DB, monitoring. These differ between a
white-label WT integration and a multi-tenant SaaS and are intentionally left to
the deployment shell. The body-size middleware and limits here are a floor, not
a substitute for an API gateway with auth + rate limiting.

## Configuration

All limits are overridable via environment variables — see `.env.example`.
CORS is **closed by default**; set `DIGITAL_TWIN_CORS_ORIGINS` to the deployed
frontend origin(s).

## Tests

`tests/pytest_security_hardening.py` pins each fix. Run the full suite:

```bash
PYTHONPATH=. pytest -q tests/
```
