# Release notes — V5.1.1

**Tag:** `v5.1.1` (stabilization — no new features)  
**Base:** `v5.1.0` architectural baseline

## Goal

Make V5.1 **ready for real frontend integration** (Next.js / Vercel / v0) without further architectural refactors.

## What's included

### Tests (regression gates)

| File | Covers |
|------|--------|
| `tests/pytest_openapi_contract.py` | Committed `openapi.json` ↔ live export, schema presence, idempotent export |
| `tests/pytest_service_layer.py` | Typed Pydantic boundaries, service orchestration, upload error codes |
| `tests/pytest_in_person_tests.py` | Mader, CP, Wingate HTTP; malformed input → 4xx |
| `tests/pytest_twin_state_roundtrip.py` | build → ride update → workout update → project |
| `tests/pytest_frontend_client_contract.py` | `client.ts` paths ↔ OpenAPI, env vars, generated types |

Shared fixtures: `tests/_fixtures.py`

### Documentation

| Doc | Purpose |
|-----|---------|
| `docs/FRONTEND_CONNECT_NEXT_VERCEL.md` | **Primary** — `NEXT_PUBLIC_API_BASE_URL`, CORS, FormData, offline handling |
| `docs/DEPLOY_BACKEND.md` | Production uvicorn, env, systemd, TLS |
| `docs/API_EXAMPLES.md` | Minimal copy-paste payloads |
| `docs/TROUBLESHOOTING.md` | CORS, uploads, TwinState, CI |
| `docs/RELEASE_NOTES_v5.1.0.md` | Baseline architecture reference |

### Policy (unchanged from V5.1.0)

- No new domain features
- Bugfix only with regression test
- OpenAPI must stay aligned (`make openapi-frontend`)

## Verification

```bash
make check
PYTHONPATH=. python3 tests/integration/test_api_app.py
```

## For frontend developers

1. Read `docs/FRONTEND_CONNECT_NEXT_VERCEL.md`
2. Copy `frontend/src/api/client.ts` + `generated/schema.ts`
3. Set `NEXT_PUBLIC_API_BASE_URL`
4. Configure `DIGITAL_TWIN_CORS_ORIGINS` on the backend

## Next phase

Maintain structure while shipping product:

- Bugfix + tests + docs only
- No new monoliths — follow router → service → engines
- Run **Full backend check** before releases
