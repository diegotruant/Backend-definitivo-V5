# Ingest pipeline architecture — S3 → VPS → DB → frontend

This document describes the **production deployment model** for a TrainingPeaks-like workflow: FIT files in object storage, computation on a VPS, persistence in Postgres/Supabase, coach UI reading precomputed JSON.

The backend repo (`Backend-definitivo-V5`) is the **compute engine**. Storage, queues, and database are built around it.

---

## System overview

```text
[Device / app / coach upload]
        │ presigned PUT
        ▼
   S3 bucket  ──event──►  Queue (SQS / Redis)
        │                        │
        │                        ▼
        │                  VPS worker (Python)
        │                        │
        │    ┌───────────────────┼───────────────────┐
        │    ▼                   ▼                   ▼
        │  RideService      TwinService         ProfileService
        │  (parse/ingest)   (state update)      (snapshot/curves)
        │    │                   │                   │
        └────┴───────────────────┴───────────────────┘
                                 │
                                 ▼
                          Postgres / Supabase
                          (activities, twin_states)
                                 │
                                 ▼
                          React coach frontend
                          (read DB; live API for what-if only)
```

---

## 1. Object storage (S3)

### Bucket layout

```text
s3://wt-activities/
  raw/{team_id}/{athlete_id}/{yyyy-mm-dd}/{activity_id}/{sha256}.fit
```

- **Upload**: presigned URL from API or Supabase Edge Function (not large multipart to VPS in production).
- **IAM**: prefix per `team_id`; app-level RLS in Postgres for coach ↔ athlete scope.
- **Dedup**: `file_hash` from `api/upload.parse_upload()` — same FIT twice must not double-count CTL.

Store the S3 URL in `activities.fit_file_url` (see `docs/FRONTEND_IMPLEMENTATION_BLUEPRINT.md`).

---

## 2. VPS backend (this repo)

### Processes

| Process | Role |
|---------|------|
| **FastAPI** (`uvicorn api_app:app`) | On-demand compute, coach tools, what-if |
| **Worker** (RQ/Celery/SQS consumer) | Async FIT pipeline after S3 event |

The worker **imports the same services** as HTTP (`RideService`, `TwinService`, `ProfileExtendedService`) — no duplicate engine wiring.

### FIT processing sequence (per activity) — athlete model (V5.3+)

```text
1. Download FIT from S3 → temp file
2. parse_upload / parse_fit_file_enhanced
3. POST /ride/ingest-with-mmp-aggregate
     → bundle + ingest + mmp_aggregate + metabolic_profile + thresholds + athlete_model
4. POST /twin/state/update-from-ride
     → pass ingest_result.active_metabolic_profile (not per-activity metabolic_snapshot)
5. Optional: sync_twin_athlete_model() for full zone_anchors + canonical MMP on twin
6. Persist activities + twin_states (single transaction)
```

Reference worker script: `tools/worker/ingest_athlete_model_pipeline.py`  
Deploy checklist: `docs/ATHLETE_MODEL_DEPLOY_CHECKLIST.md`  
SQL smoke test: `scripts/smoke_test_athlete_model.sql`

### Legacy FIT sequence (pre-athlete-model)

```text
1. Download FIT from S3 → temp file
2. parse_upload / parse_fit_file_enhanced
3. build_data_quality_report
4. RideService.ingest(stored_curve from twin)
5. RideService.build_summary(metabolic_snapshot from twin)
6. If ingest.profile_should_refresh:
     RideService.update_profile OR profile snapshot refresh
7. TwinService.update_from_ride(
       twin_state, ingest_result, ride_summary,
       metabolic_snapshot=refreshed_snapshot   # triggers metabolic_curves sync
   )
8. Persist activities + twin_states (single transaction)
```

Hook registry: `engines.twin_state.ingest_worker_hook_points()`.

Curve sync on twin: see `docs/METABOLIC_CURVES_TWIN_CONTRACT.md`.

---

## 3. Database (Postgres / Supabase)

Minimum tables (from `docs/FRONTEND_IMPLEMENTATION_BLUEPRINT.md`):

| Table | Purpose |
|-------|---------|
| `teams`, `coaches`, `athletes` | Multi-tenant, coach ↔ athlete assignment |
| `activities` | One row per FIT: `fit_file_url`, `file_hash`, `summary` JSON, `status` |
| `twin_states` | One `twin_state.v1` JSON blob per athlete |
| `activity_jobs` | `pending → processing → done \| failed` |
| `validation_events` | Lab tests vs model predictions |

### What to store where

| Data | Location | Source endpoint |
|------|----------|-----------------|
| Raw FIT | S3 | upload |
| Activity summary | `activities.summary` | `/ride/summary` |
| Rolling MMP + load | `twin_states.twin_state` + `athlete_mmp_aggregate` | `/ride/ingest-with-mmp-aggregate` |
| Stable metabolic profile | `athlete_metabolic_profile_versions` + `athlete_current_profile` | `GET /athletes/{id}/metabolic-profile/current` |
| FTP / LTHR / CP | `athlete_threshold_versions` + `athlete_current_thresholds` | `GET /athletes/{id}/thresholds/current` |
| Zone anchors | twin `zone_anchors` + API | `GET /athletes/{id}/zone-anchors/current` |
| VO₂ / substrate curves | `twin_state.metabolic_curves` | from versioned profile via twin sync |
| Measured lactate | `twin_state.lactate_state` | `/test/in-person` → `lactate_persistence` |
| Session fuel / W′ | `activities` analytics | `/profile/metabolic/curves` with `power_series` |

---

## 4. Dependency graph (new FIT, same athlete)

A new FIT is **not independent** — order matters:

```text
FIT → parse/summary → activities row (independent)
         │
         ▼
      ingest(MMP) ──depends on──► previous rolling_power_curve in twin
         │
         ├──► load_state (CTL/ATL) ──depends on──► previous load_state + this TSS
         │
         └──► profile refresh? ──depends on──► significant new best / test
                    │
                    ▼
              metabolic_snapshot + metabolic_curves refresh
                    │
                    ▼
              twin_states update (transaction with activities)
```

**Idempotency**: key `activities(file_hash, athlete_id)` — re-upload skips or replaces, never duplicates load.

---

## 5. Frontend

### Read from DB (default)

- Team dashboard → query `twin_states` + aggregates
- Activity list → `activities` ordered by date
- Digital Twin → `twin_state` + `metabolic_curves` / `lactate_state` (no live curve API)

### Call API live (on demand)

- `/coach/*` decision support
- `/projection/season`
- `/workouts/prescribe`, `/workouts/feasibility`
- `/profile/metabolic/curves` with `power_series` for **this session only**

---

## 6. Gap vs TrainingPeaks

| TrainingPeaks | This stack |
|---------------|------------|
| TSS, PMC, power curve | ✅ + TwinState cumulative model |
| FTP / zones | ✅ + dual metabolic/Coggan zones |
| — | Mader durability, VLamax/VO₂ profile, coach engine (20 endpoints) |
| — | Workout prescribe vs perform compliance |
| — | Team calibration / model accuracy tracking |
| — | Tier honesty (LAB vs MODEL badges) |

---

## 7. Implementation roadmap

| Phase | Deliverable |
|-------|-------------|
| **0** | Postgres schema + RLS (`teams`, `athletes`, `activities`, `twin_states`, `activity_jobs`) |
| **1** | Presigned S3 + `POST /activities/register` (metadata only) |
| **2** | VPS worker: S3 download → pipeline above → DB write |
| **3** | Frontend: activities + twin from DB (replace CSV MVP) |
| **4** | Job retry, dead-letter queue, failed-ingest UI |
| **5** | Garmin/webhook sync, coach notifications |

**Already in this repo (V5.2.3+):** FIT parse, ingest, summary, twin update, metabolic curves on twin, contract tests.

**Not in this repo:** S3 client, queue, ORM, activity CRUD REST, worker process.

---

## Related docs

- `docs/METABOLIC_CURVES_TWIN_CONTRACT.md` — `metabolic_curves.v1`, `lactate_state.v1`
- `docs/FRONTEND_IMPLEMENTATION_BLUEPRINT.md` — DB tables, coach pages
- `docs/FRONTEND_DEVELOPER_GUIDE.md` §8 — twin round-trip loop
- `docs/DEPLOY_BACKEND.md` — VPS API deploy
- `docs/ARCHITECTURE.md` — code layers
- `engines/twin_state/metabolic_curves_sync.py` — curve sync helpers
