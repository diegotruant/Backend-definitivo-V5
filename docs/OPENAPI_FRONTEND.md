# OpenAPI — guida integrazione frontend

## Cosa hai a disposizione

| Risorsa | Path / URL | Uso |
|---------|------------|-----|
| **Spec committata** | `openapi/openapi.json` | Codegen, review PR, offline |
| **Tipi TypeScript** | `frontend/src/api/generated/schema.ts` | Autocomplete request/response |
| **Client tipizzato** | `frontend/src/api/client.ts` | Tutte le 24 API, pronto all'uso |
| **Swagger UI** | `GET /docs` (server avviato) | Esplorazione interattiva |
| **OpenAPI live** | `GET /openapi.json` | Sync con server in esecuzione |

## Setup frontend

### Variabile base URL

Il client (`frontend/src/api/client.ts`) risolve l'URL in questo ordine:

1. `VITE_API_BASE_URL` — **Vite** (MVP attuale in `frontend/`)
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

In produzione punta alla URL del backend deployato (es. `https://api.tuodominio.com`).

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

## Tutti gli endpoint nel client

| Gruppo | Metodi `api.*` |
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

## Rigenerare dopo modifiche backend

```bash
make openapi-frontend
```

Poi committa:

- `openapi/openapi.json`
- `frontend/src/api/generated/schema.ts`

## Tipi request

Importa da `api/client` (alias dei componenti OpenAPI):

```typescript
import type {
  ConfirmRequest,
  SnapshotRequest,
  SeasonProjectionRequest,
  WorkoutPrescribeRequest,
} from './api/client';
```

Per campi dominio ricchi (MetabolicSnapshot, WorkoutSummary, tier UI) usa anche `contracts.ts`.

## Operation IDs

Ogni endpoint ha un `operationId` stabile (es. `profileSnapshot`, `rideIngest`) visibile in Swagger e in `frontend/src/api/generated/schema.ts` sotto `operations`.

## Errori HTTP

| Status | Significato |
|--------|-------------|
| 400 | Input non valido / ServiceError |
| 413 | Upload o power_json troppo grande |
| 422 | FIT non parsabile o attività senza potenza |

Il body è sempre `{"detail": ...}`.

## CI

`make check` non rigenera OpenAPI automaticamente. Dopo cambi a `api/routers` o `api/schemas`, esegui `make openapi-frontend` e includi i file generati nel PR.
