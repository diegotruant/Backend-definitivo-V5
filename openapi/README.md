# OpenAPI contract — Digital Twin API

This folder contains the **canonical HTTP contract** for frontend and external integrators.

| File | Purpose |
|------|---------|
| `openapi.json` | Full OpenAPI 3.1 document (42 endpoints) |

## Live spec (running server)

When the API is up:

- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- Raw JSON: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

## Regenerate after API changes

From repository root:

```bash
make openapi-frontend
```

This will:

1. Export `openapi/openapi.json` from the FastAPI app
2. Regenerate `frontend/src/api/generated/schema.ts` (TypeScript types)

## Frontend usage

```typescript
import { api } from './api/client';
import type { SnapshotRequest, HealthResponse } from './api/client';

const health = await api.health();
const snapshot = await api.profileSnapshot({ mmp: { '300': 340 }, athlete: { ... } });
```

See `docs/OPENAPI_FRONTEND.md` for the full integration guide.
