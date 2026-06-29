# OpenAPI — frontend integration guide

## What you have available

| Resource | Path / URL | Use |
|---------|------------|-----|
| **Committed spec** | `openapi/openapi.json` | Codegen, PR review, offline |
| **TypeScript types** | `frontend/src/api/generated/schema.ts` | Autocomplete request/response |
| **Typed client** | `frontend/src/api/client.ts` | All **132** API paths, ready to use |
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

The typed client (`frontend/src/api/client.ts`) exposes **all 132 OpenAPI paths** — one `jsonFetch` call per route.

| Tag | Paths | Highlights |
|-----|------:|------------|
| ride | 32 | `rideSummary`, `rideAnalyticsZones`, `rideAnalyticsWPrimeBalance`, … |
| profile | 15 | `profileSnapshot`, `profileVlamaxFromPowerSeries`, `profileGlycolyticProfile`, … |
| workouts | 9 | `validateWorkout`, `prescribeWorkout`, `compareWorkout`, … |
| lab | 7 | lactate + vLaPeak validation |
| explainability | 6 | confidence scores + coach narratives |
| twin | 6 | `twinStateBuild`, `twinStateValidate`, `twinStateProject`, … |
| load | 5 | `manualLoad`, `loadAcwr`, adaptive trend |
| history / performance / planning / readiness / test | 13 | unchanged core flows |
| integrations / meta / race / team / health | 7 | normalize, chart-config, GPX, calibration |

**Canonical list:** `docs/API_ENDPOINT_INDEX.md` (method, path, `operationId` per row).

### Zones on activities

`POST /ride/summary` and `POST /ride/analytics/zones` return **both**:

- `metabolic_power` — MLSS/MAP 5-zone time-in-zone (needs metabolic snapshot)
- `coggan_power` — FTP 7-zone time-in-zone

Pass `metabolic_snapshot_json` or rely on auto-snapshot from ride MMP.

## Authentication

Set backend `DIGITAL_TWIN_AUTH_MODE`:

| Mode | Client headers |
|------|----------------|
| `none` | Optional `X-Athlete-Id` if `DIGITAL_TWIN_REQUIRE_ATHLETE_ID=true` |
| `api_key` | `Authorization: Bearer <key>` |
| `jwt` | `Authorization: Bearer <jwt>` + `X-Athlete-Id` on athlete-scoped routes |

JWT claims (minimum):

```json
{
  "sub": "user-uuid",
  "roles": ["coach"],
  "team_id": "team-uuid",
  "athlete_ids": ["ath-a-001", "ath-b-002"]
}
```

Athlete tokens use `"roles": ["athlete"]` and `"athlete_id": "ath-a-001"` (header optional).

## `power_json` and `hr_json`

Ride endpoints accept either a FIT upload or inline JSON streams:

- `power_json` — required for JSON-only mode; **never** synthesizes heart rate
- `hr_json` — optional measured HR stream; omit when unavailable

Check `data_provenance.measured_signals` / `synthetic_signals` in responses.

## `POST /ride/parse`

Full FIT extraction contract for persistence and coach UI:

- `available_signals`, `streams`, `quality`, `laps`, `warnings`, `file_hash`, `parser_version`
- Use before ingest when you need explicit sensor coverage and provenance

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
