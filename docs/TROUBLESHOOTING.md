# Troubleshooting

Common issues when running or integrating the Digital Twin API.

---

## CI / quality gate

| Symptom | Fix |
|---------|-----|
| `make check` fails on OpenAPI | Run `make openapi-frontend`, commit `openapi/openapi.json` + `schema.ts` |
| `pytest_openapi_contract` drift | Same as above — live `app.openapi()` must match committed file |
| mypy errors in `api/` | Run `make typecheck`, fix types before merge |
| Full-check workflow timeout | Normal on cold runner; re-run `workflow_dispatch` |

---

## Frontend / CORS

| Symptom | Cause | Fix |
|---------|-------|-----|
| Browser: “blocked by CORS” | `DIGITAL_TWIN_CORS_ORIGINS` empty or wrong | Set backend env to your Vercel URL(s), restart API |
| `fetch` TypeError, no response | Wrong `NEXT_PUBLIC_API_BASE_URL` or API down | Check `/health` in browser; fix env; redeploy Vercel |
| 422 on every request | Body shape mismatch | Compare with `GET /docs` or `docs/API_EXAMPLES.md` |
| Works in curl, fails in browser | CORS or mixed content (HTTP page → HTTPS API) | Use HTTPS everywhere |

---

## Uploads (FIT / FormData)

| Symptom | Cause | Fix |
|---------|-------|-----|
| 413 Payload Too Large | FIT > `MAX_UPLOAD_BYTES` | Increase env or compress; default 40 MB |
| 400 INVALID_FIT_FILE | Corrupt or non-cycling FIT | Re-export from device; try another file |
| 400 on `power_json` | Invalid JSON string in form field | Pass valid JSON array string |
| 400 empty power | `power_json: "[]"` | Need non-empty power stream for compare/summary |
| Upload works in Postman, not browser | Manual `Content-Type: multipart` header | Let `fetch` set boundary — use `api.*` client |

---

## TwinState

| Symptom | Cause | Fix |
|---------|-------|-----|
| 422 on `/twin/state/project` | `twin_state` missing required fields | Use full `twin_state.v1` from build or DB |
| 400 `PAYLOAD_TOO_DEEP` | Nested JSON > `MAX_JSON_DEPTH` | Flatten payload |
| 422 `max_days` | Value > 400 | Lower `max_days` in request |
| Projection empty / warning | Sparse metabolic snapshot | Add `metabolic_snapshot` + curve in build payload |

---

## Performance

| Symptom | Notes |
|---------|-------|
| `/profile/snapshot` slow (10s+) | Expected under load — scipy profiler; not a correctness bug |
| FIT 30–60 min slow (2–3s p95) | Parser + summary pipeline; scale workers |
| Timeout 502 from proxy | Increase nginx `proxy_read_timeout` to 120s+ |

---

## OpenAPI / client mismatch

| Symptom | Fix |
|---------|-----|
| TS type errors after pull | `make openapi-frontend` in backend repo, copy new `schema.ts` |
| `client.ts` path not in spec | Regenerate OpenAPI; paths must match 24 endpoints |
| `pytest_frontend_client_contract` fails | Align client + openapi in same commit |

---

## In-person tests

| Symptom | Fix |
|---------|-----|
| Mader returns error | Need ≥4 lactate steps with ascending power |
| CP test fails | Need ≥3 efforts with `duration_s` + `power_w` |
| Wingate fails | Need `power_stream` + `body_weight_kg` |
| 422 `test_type` | Use: `mader`, `incrementale`, `curva_pc`, `critical_power`, `wingate` |

---

## Logs and debugging

```bash
# Local verbose
uvicorn api_app:app --reload --log-level debug

# Quick contract check
PYTHONPATH=. python3 tests/integration/test_api_app.py

# Single pytest file
python3 -m pytest -q tests/pytest_twin_state_roundtrip.py -v
```

---

## Getting help

1. Reproduce with minimal payload from `docs/API_EXAMPLES.md`
2. Note status code + `detail` body
3. Check whether issue is CI, HTTP contract, or engine logic
4. Add a pytest regression if fixing a bug
