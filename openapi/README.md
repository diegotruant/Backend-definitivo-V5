# OpenAPI contract — Digital Twin API

**Version:** 5.2.6  
**Paths:** 135

| File | Description |
|------|-------------|
| `openapi.json` | Full OpenAPI 3.1 document (135 HTTP paths) |
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

CI runs `scripts/check_openapi_consistency.py` and `tests/pytest_openapi_contract.py`: the committed spec, operational documentation and API index must match the live FastAPI export.

The generated TypeScript schema is checked against all 135 paths. The single known codegen gap, `/ride/full-bundle`, is temporarily allowed and tracked in GitHub issue #14; any additional missing path fails the gate.