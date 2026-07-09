# Athlete model deploy checklist

Operational steps after merging `cursor/athlete-model-unification-d0d1` (or equivalent).

---

## 1. Database migrations (order matters)

Run in Supabase SQL editor or migration runner:

| # | File | Tables |
|---|------|--------|
| 1 | `supabase/migrations/004_mmp_aggregate.sql` | `activity_mmp_points`, `athlete_mmp_aggregate` |
| 2 | `supabase/migrations/005_metabolic_profile_versions.sql` | `athlete_metabolic_profile_versions`, `athlete_current_profile` |
| 3 | `supabase/migrations/006_athlete_threshold_versions.sql` | `athlete_threshold_versions`, `athlete_current_thresholds` |

**Verify:** `scripts/smoke_test_athlete_model.sql` section 1 returns 6 tables.

---

## 2. Environment variables (API + worker)

```bash
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service_role_key>
```

Without these, stores fall back to in-memory (dev only).

Optional API:

```bash
DIGITAL_TWIN_CORS_ORIGINS=https://your-frontend.vercel.app
```

---

## 3. Worker sequence (per FIT)

Reference implementation: `tools/worker/ingest_athlete_model_pipeline.py`

```text
1. Download FIT from S3
2. POST /ride/ingest-with-mmp-aggregate
     - athlete_id, activity_id, activity_file_id, ride_date, weight_kg
     - optional: ftp, lthr (coach override)
3. Read response:
     - mmp_aggregate.mmp_status  → collecting | provisional | published
     - metabolic_profile         → created/skipped
     - thresholds                → created/skipped
     - athlete_model             → snapshot + zone_anchors for twin
     - ingest.active_metabolic_profile → pass to twin update
4. POST /twin/state/update-from-ride
     - ingest_result (include active_metabolic_profile + canonical curve)
     - ride_summary from bundle.workout_summary
5. Persist activities.summary + twin_states (single transaction)
```

Hook registry: `engines.twin_state.ingest_worker_hook_points()`

---

## 4. MMP status gates

| Status | Frontend MMP curve | Metabolic profile | Thresholds |
|--------|-------------------|-------------------|------------|
| `collecting` | hidden | not created | not created |
| `provisional` | visible | not created | not created |
| `published` | visible | versioned profile | versioned FTP/LTHR/CP |

**Published requires:** ≥ 8 activities, ≥ 4 duration families including MAP + threshold.

---

## 5. Frontend integration

Replace per-activity metabolic reads with athlete-level endpoints:

| Endpoint | Use |
|----------|-----|
| `GET /athletes/{id}/metabolic-profile/current` | VO2max, VLamax, MLSS, MAP, phenotype |
| `GET /athletes/{id}/thresholds/current` | FTP, LTHR, CP |
| `GET /athletes/{id}/zone-anchors/current` | Zone prescription anchors |

Client methods: `getAthleteMetabolicProfileCurrent`, `getAthleteThresholdsCurrent`, `getAthleteZoneAnchorsCurrent`

**Do not use** `bundle.metabolic_snapshot` or `bundle.classification` as stable athlete identity (`do_not_use_as_athlete_profile: true`).

---

## 6. Manual acceptance test

1. Ingest **8+ distinct FITs** for one `athlete_id`
2. Confirm `athlete_mmp_aggregate.mmp_status = 'published'`
3. Confirm exactly **one** `is_active = true` row in `athlete_metabolic_profile_versions`
4. Confirm `athlete_current_profile` points to that row
5. Call the 3 GET endpoints → `status: "available"`
6. Ingest a FIT that does **not** improve MMP → no new profile version
7. Dashboard twin highlights show `mmp_source: athlete_mmp_aggregate`

---

## 7. Rollback

- Migrations are additive; rollback = stop worker from calling new endpoints
- Old twin `metabolic_snapshot` path still works if versioned profile missing
- Per-activity bundle fields remain for session diagnostics (deprecated tags)

---

## Related

- `docs/INGEST_PIPELINE_ARCHITECTURE.md` — full S3 → VPS → DB flow
- `docs/METABOLIC_CURVES_TWIN_CONTRACT.md` — twin curve sync
- `scripts/smoke_test_athlete_model.sql` — SQL verification queries
