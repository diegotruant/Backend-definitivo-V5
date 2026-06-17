# OpenAPI — frontend integration guide

## What you have available

| Resource | Path / URL | Use |
|---------|------------|-----|
| **Committed spec** | `openapi/openapi.json` | Codegen, PR review, offline |
| **TypeScript types** | `frontend/src/api/generated/schema.ts` | Autocomplete request/response |
| **Typed client** | `frontend/src/api/client.ts` | All 42 APIs, ready to use |
| **Swagger UI** | `GET /docs` (server running) | Interactive exploration |
| **Live OpenAPI** | `GET /openapi.json` | Sync with running server |

## Frontend setup

### Base URL variable

The client (`frontend/src/api/client.ts`) resolves the URL in this order:

1. `VITE_API_BASE_URL` — **Vite** (current MVP in `frontend/`)
2. `NEXT_PUBLIC_API_BASE_URL` — **Next.js / Vercel / v0**
3. fallback `http://localhost:8000`

**Vite** (`.env.local`):

```bash
VITE_API_BASE_URL=http://localhost:8000
```

**Next.js / Vercel** (`.env.local`):

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

In production, point to the deployed backend URL (e.g. `https://api.yourdomain.com`).

```typescript
import { api, ApiError } from '@/api/client';

try {
  const summary = await api.rideSummary({
    file: fitFile,
    weight_kg: 72,
    metabolic_snapshot: snapshot,
  });
} catch (e) {
  if (e instanceof ApiError) {
    console.error(e.status, e.body);
  }
}
```

## All endpoints in the client

| Group | `api.*` methods |
|--------|----------------|
| Health | `health()` |
| Test | `proposeTest`, `confirmTest`, `inPersonTest` |
| Ride | `ingestRide`, `updateProfile`, `rideSummary`, `rideDurability` |
| Profile | `profileSnapshot` |
| Workouts | `validateWorkout`, `prescribeWorkout`, `workoutFeasibility`, `compareWorkout`, `calendarTransition` |
| Twin | `twinStateBuild`, `twinStateUpdateFromRide`, `twinStateUpdateFromWorkout`, `twinStateProject`, `projectionSeason` |
| Performance | `neuromuscularProfile`, `powerSourceNormalize` |
| Load | `manualLoad` |
| Team | `updateTeamCalibration`, `applyTeamCalibration` |

## Regenerate after backend changes

```bash
make openapi-frontend
```

Then commit:

- `openapi/openapi.json`
- `frontend/src/api/generated/schema.ts`

## Request types

Import from `api/client` (aliases of OpenAPI components):

```typescript
import type {
  ConfirmRequest,
  SnapshotRequest,
  SeasonProjectionRequest,
  WorkoutPrescribeRequest,
} from './api/client';
```

For richer domain fields (MetabolicSnapshot, WorkoutSummary, UI tiers), also use `contracts.ts`.

## Operation IDs

Each endpoint has a stable `operationId` (e.g. `profileSnapshot`, `rideIngest`) visible in Swagger and in `frontend/src/api/generated/schema.ts` under `operations`.

## HTTP errors

| Status | Meaning |
|--------|-------------|
| 400 | Invalid input / ServiceError |
| 429 | Rate limit exceeded (`RATE_LIMITED`) |
| 413 | Upload or power_json too large |
| 422 | Unparseable FIT or activity without power |

The body is always `{"detail": ...}`.

If backend env `DIGITAL_TWIN_REQUIRE_ATHLETE_ID=true` is enabled, athlete-scoped
endpoints also require header `X-Athlete-Id`.

## CI

`make check` does not regenerate OpenAPI automatically. After changes to `api/routers` or `api/schemas`, run `make openapi-frontend` and include the generated files in the PR.
