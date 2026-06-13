# Connect Next.js / Vercel / v0 to the Digital Twin API

This guide is the fastest path from a **v0 or Next.js app on Vercel** to a working backend integration.

## 1. Backend URL

Deploy or run the API (see `docs/DEPLOY_BACKEND.md`). You need a public HTTPS base URL, for example:

```text
https://api.yourdomain.com
```

Local development:

```bash
make install && make run
# → http://127.0.0.1:8000
```

## 2. Environment variable (Next.js / Vercel)

In your Next.js project root, create `.env.local`:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

On **Vercel** → Project → Settings → Environment Variables:

| Name | Value | Environments |
|------|-------|----------------|
| `NEXT_PUBLIC_API_BASE_URL` | `https://api.yourdomain.com` | Production, Preview |

Redeploy after changing env vars. `NEXT_PUBLIC_*` is embedded at **build time**.

## 3. Copy or import the typed client

From this repo:

```text
frontend/src/api/client.ts
frontend/src/api/generated/schema.ts
```

In Next.js, place them under e.g. `src/lib/api/` and import:

```typescript
import { api, ApiError } from '@/lib/api/client';

export async function loadHealth() {
  return api.health();
}
```

The client resolves `NEXT_PUBLIC_API_BASE_URL` automatically (see `client.ts`).

## 4. CORS on the backend

Browser requests from `https://your-app.vercel.app` require CORS on the API.

Set on the **backend** host (not Vercel):

```bash
DIGITAL_TWIN_CORS_ORIGINS=https://your-app.vercel.app,https://your-app-*.vercel.app
```

Restart the API after changing env. If CORS is empty, the API accepts only same-origin / server-side calls.

Allowed methods: `GET`, `POST`. Allowed headers: `*`.

## 5. OpenAPI contract

| Resource | URL |
|----------|-----|
| Live spec | `GET {API_BASE}/openapi.json` |
| Swagger UI | `GET {API_BASE}/docs` |
| Committed spec | `openapi/openapi.json` in this repo |

Use Swagger to explore request shapes before wiring UI forms.

After backend changes, regenerate types:

```bash
make openapi-frontend
```

Commit `openapi/openapi.json` and `frontend/src/api/generated/schema.ts`.

## 6. JSON endpoints (majority)

```typescript
const snapshot = await api.profileSnapshot({
  mmp: { '60': 489, '300': 309, '1200': 280 },
  athlete: { weight_kg: 72, gender: 'MALE', training_years: 10, discipline: 'ENDURANCE' },
});
```

All JSON methods are on the `api` object — see `docs/OPENAPI_FRONTEND.md` for the full method table.

## 7. FIT upload with FormData

Endpoints that accept files **must not** set `Content-Type: application/json`. The client already handles this:

```typescript
// Ride ingest
await api.ingestRide({
  file: fitFile,           // File from <input type="file"> or drag-drop
  ride_date: '2026-06-01',
  weight_kg: 72,
});

// Ride summary (FIT or power array)
await api.rideSummary({
  file: fitFile,
  weight_kg: 72,
  ftp: 280,
  metabolic_snapshot: snapshot,
});

// Or power_json instead of file
await api.rideSummary({
  power_json: powerArray,
  weight_kg: 72,
});

// Test propose (multi-file)
await api.proposeTest([fitFile1, fitFile2]);

// Workout compare
await api.compareWorkout({
  workout: { title: 'Test', steps: [...] },
  file: fitFile,
  athlete_profile: { cp_w: 260, weight_kg: 72 },
});
```

**Next.js App Router tip:** call these from **client components** (`'use client'`) or Route Handlers — not from Server Components without streaming the file bytes yourself.

## 8. Error handling

```typescript
import { api, ApiError } from '@/lib/api/client';

try {
  await api.confirmTest({ ... });
} catch (e) {
  if (e instanceof ApiError) {
    // e.status: 400 | 422 | 413 | …
    // e.body: raw JSON string from backend
    const detail = JSON.parse(e.body);
    console.error(detail);
  }
}
```

| Status | Meaning |
|--------|---------|
| `422` | Pydantic validation — fix request shape |
| `400` | Business rule / engine rejection (`detail` often has `error` code) |
| `413` | Upload too large |
| `500` | Unexpected — report with request id / logs |

## 9. Backend offline / unreachable

The client uses `fetch`. There is no built-in retry. Recommended pattern:

```typescript
async function withBackend<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (e) {
    if (e instanceof TypeError) {
      throw new Error('Backend unreachable — check NEXT_PUBLIC_API_BASE_URL and CORS');
    }
    throw e;
  }
}
```

In the UI:

- Show a clear “API offline” state when `fetch` throws `TypeError`
- Health check on layout mount: `api.health()` → `{ status: "ok" }`
- Do not cache FIT uploads client-side only — persist after successful `ingestRide`

## 10. TwinState flow (typical app)

```typescript
// 1. Build from fragments
const twin = await api.twinStateBuild({ payload: { athlete_id, athlete_profile, ... } });

// 2. After ride
const updated = await api.twinStateUpdateFromRide({
  twin_state: twin,
  ride_summary: summary,
  ingest_result: ingest,
  ride_id: 'ride_123',
});

// 3. After workout compliance
const afterWorkout = await api.twinStateUpdateFromWorkout({
  twin_state: updated,
  compliance_result: compareResult,
  assignment_id: 'w1',
});

// 4. Season projection
const projection = await api.twinStateProject({
  twin_state: afterWorkout,
  calendar_plan: [...],
  start_date: '2026-06-01',
  target_date: '2026-12-01',
});
```

See `docs/API_EXAMPLES.md` for minimal JSON payloads.

## 11. Checklist before go-live

- [ ] `NEXT_PUBLIC_API_BASE_URL` set on Vercel Production
- [ ] `DIGITAL_TWIN_CORS_ORIGINS` includes your Vercel domain(s)
- [ ] `GET /health` returns 200 from the browser (not just curl)
- [ ] One FIT upload tested end-to-end (`ingestRide` or `rideSummary`)
- [ ] `make openapi-frontend` run after last backend pull

## Related docs

- `docs/OPENAPI_FRONTEND.md` — full client method list
- `docs/FRONTEND_DEVELOPER_GUIDE.md` — screens ↔ endpoints
- `docs/API_EXAMPLES.md` — copy-paste payloads
- `docs/TROUBLESHOOTING.md` — common failures
