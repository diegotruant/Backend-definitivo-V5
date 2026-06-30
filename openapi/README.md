# OpenAPI contract — Digital Twin API

**Version:** 5.2.6  
**Paths:** 134

| File | Description |
|------|-------------|
| `openapi.json` | Full OpenAPI 3.1 document (134 HTTP paths) |
| `../docs/API_ENDPOINT_INDEX.md` | Human-readable index by tag |
| `../docs/OPENAPI_FRONTEND.md` | Frontend integration guide |

## Live exploration

- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- Raw JSON: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

## Regenerate

```bash
make openapi-frontend
```

This will:

1. Export `openapi/openapi.json` from the FastAPI app (`scripts/export_openapi.py`)
2. Regenerate `frontend/src/api/generated/schema.ts` (requires `npm install` in `frontend/`)

Commit both files (and `frontend/src/api/client.ts` if you added routes manually).

## Drift checks

CI runs `tests/pytest_openapi_contract.py` — committed spec must match live export.

`tests/pytest_frontend_client_contract.py` enforces **134 paths** in `client.ts` match OpenAPI 1:1.
