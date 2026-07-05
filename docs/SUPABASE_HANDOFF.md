# Supabase Handoff — Digital Twin Backend V5.2.6

**Repository:** `diegotruant/Backend-definitivo-V5`  
**Versione backend:** 5.2.6  
**Audience:** team Supabase / platform / frontend  
**Companion:** `docs/FRONTEND_API_FACADE.md`, `docs/INGEST_PIPELINE_ARCHITECTURE.md`

---

## 1. Scopo

Questo documento definisce il **confine operativo** tra quattro attori del sistema Digital Twin:

| Attore | Ruolo |
|--------|-------|
| **Backend** (questo repo) | Compute engine stateless — calcola e restituisce JSON |
| **Supabase** | Persistenza, auth, RLS, storage, job orchestration, read model |
| **Frontend** | Legge DB, chiama backend solo per calcolo live / ingest / decision support |
| **Worker ingest** | Pipeline asincrona FIT: Storage → backend → Supabase |

### Obiettivi

- Definire il confine operativo tra backend, Supabase, frontend e worker ingest.
- Chiarire che il **backend calcola** e restituisce JSON (`status`, `warnings`, `confidence`, `missing_inputs`, `quality_flags`).
- Chiarire che **Supabase salva**, protegge, organizza e orchestra.
- Evitare duplicazione dei motori fisiologici Python in SQL, trigger o Edge Functions.
- Il backend **non deve diventare** Supabase.
- Supabase **non deve duplicare** i motori fisiologici.

---

## 2. Regola base

Usare sempre questo principio:

```text
Backend produce JSON  →  Supabase salva JSON  →  Frontend mostra JSON
```

```text
┌──────────────┐     JSON      ┌──────────────┐     read      ┌──────────────┐
│   Backend    │ ────────────► │   Supabase   │ ────────────► │   Frontend   │
│  (compute)   │               │  (persist)   │               │   (display)  │
└──────────────┘               └──────┬───────┘               └──────────────┘
                                      │
                                      │ job + storage
                               ┌──────▼───────┐
                               │ Worker ingest│
                               └──────────────┘
```

- **Scrittura JSON:** worker server-side, Edge Function autorizzata o RPC service — mai componente React leaf.
- **Lettura JSON:** frontend via Supabase client con RLS.
- **Trasformazione fisiologica:** solo backend Python.

---

## 3. Responsabilità backend

### Il backend DEVE

| Responsabilità | Dettaglio |
|----------------|-----------|
| Ricevere input | FIT file (multipart), JSON streams (`power_json`, `hr_json`), payload fisiologici |
| Calcolare metriche | Motori in `engines/` |
| Produrre JSON | Contratti versionati (`twin_state.v1`, `metabolic_curves.v1`, …) |
| Validare contratti | `twinStateValidate`, schema Pydantic |
| Restituire metadati qualità | `warnings`, `confidence_score`, `missing_inputs`, `quality_flags`, `tier`, `status` |
| Restare stateless | Nessuna sessione atleta tra richieste |

### Il backend NON DEVE salvare permanentemente

| Dato | Dove va |
|------|---------|
| Utenti | Supabase Auth |
| Team | `teams` |
| Atleti | `athletes` |
| Attività | `activities` |
| TwinState | `twin_states` |
| File FIT raw | Supabase Storage |
| Workout calendar | `workout_assignments` |
| Validation history | `validation_events` |
| Job queue | `activity_jobs` |

Il backend può usare file temporanei in memoria o `/tmp` durante una richiesta HTTP.

---

## 4. Responsabilità Supabase

Supabase deve gestire:

| Area | Contenuto |
|------|-----------|
| Auth | Login, JWT, refresh |
| Ruoli | owner, admin, coach, performance_scientist, viewer, athlete |
| Team / coach / atleti | Tabelle §7 + relazioni |
| Relazioni coach-atleta | `coach_athletes` |
| Storage FIT | Bucket `fit-files` |
| Job ingest | `activity_jobs` |
| Activities / TwinState | `activities`, `twin_states` |
| Validation / workout | `validation_events`, `workout_assignments` |
| Calibrazione team | `teams.calibration_model`, `team_calibration_models` |
| Audit | `audit_log` |
| RLS multi-tenant | Ogni riga scoped a `team_id` |

**Regola:** Supabase salva i JSON prodotti dal backend **senza reinterpretarli**.

| ✅ Corretto | ❌ Vietato |
|-------------|-----------|
| `INSERT summary = response_json` | Ricalcolare TSS in trigger SQL |
| `UPDATE twin_state = backend_output` | Derivare VO₂max in VIEW con formule proprie |
| Indici su `team_id`, `date` | Edge Function che replica `engines/metabolic_*` |

---

## 5. Responsabilità frontend

Il frontend deve:

| Obbligo | Dettaglio |
|---------|-----------|
| Leggere da Supabase | Twin, activities, assignments come default |
| Chiamare backend live | Solo calcolo nuovo, what-if, decision support, ingest sincrono (dev) |
| Mostrare qualità dati | `warnings`, `confidence`, `missing_inputs`, `status`, `tier` |
| Non inventare fisiologia | Nessun calcolo VO₂max, CTL, zone, parsing FIT in TS |
| Usare facade | Vedi `docs/FRONTEND_API_FACADE.md` |

---

## 6. Responsabilità worker ingest

Il worker (processo server-side separato) deve:

| Obbligo | Dettaglio |
|---------|-----------|
| Leggere job pending | `activity_jobs.status = 'pending'` |
| Scaricare FIT | Da Supabase Storage (`uploaded_files.storage_path`) |
| Chiamare backend | Sequenza §12 — stessi contratti di `api.*` |
| Salvare risultati | JSON integralmente in Supabase |
| Aggiornare TwinState | In transazione con `activities` |
| Marcare job | `done` o `failed` con error payload |
| Garantire idempotenza | UNIQUE (`athlete_id`, `file_hash`) — §15 |

Hook registry backend: `engines.twin_state.ingest_worker_hook_points()`.

---

## 7. Tabelle minime richieste

### `teams`

| Aspetto | Dettaglio |
|---------|-----------|
| **Scopo** | Tenant radice; calibrazione modello squadra |
| **Campi principali** | `id`, `name`, `slug`, `created_at`, `updated_at` |
| **JSONB** | `calibration_model`, `settings` |
| **Relazioni** | 1:N coaches, athletes, activities |
| **Vincoli** | `slug` UNIQUE |
| **Note** | `calibration_model` = law per apply team-wide |

### `coaches`

| Aspetto | Dettaglio |
|---------|-----------|
| **Scopo** | Profilo coach legato ad Auth |
| **Campi principali** | `id`, `user_id`, `team_id`, `name`, `email`, `role` |
| **JSONB** | — |
| **Relazioni** | N:1 teams; N:M athletes via `coach_athletes` |
| **Vincoli** | UNIQUE (`team_id`, `user_id`) |
| **Note** | RLS: coach vede solo proprio `team_id` |

### `athletes`

| Aspetto | Dettaglio |
|---------|-----------|
| **Scopo** | Anagrafica + headline denormalizzati |
| **Campi principali** | `id`, `team_id`, `name`, `email`, `gender`, `birth_date`, `weight_kg`, `height_cm`, `discipline`, `training_years`, `phenotype`, `status` |
| **JSONB** | `latest_anchor`, `latest_snapshot`, `latest_curve` |
| **Relazioni** | N:1 teams; 1:1 twin_states; 1:N activities |
| **Vincoli** | index (`team_id`, `status`) |
| **Note** | Headline = cache; source of truth = `twin_states.twin_state` |

### `coach_athletes`

| Aspetto | Dettaglio |
|---------|-----------|
| **Scopo** | Assegnazione coach ↔ atleta |
| **Campi principali** | `id`, `coach_id`, `athlete_id`, `team_id`, `relationship_role` |
| **JSONB** | — |
| **Relazioni** | FK coaches, athletes, teams |
| **Vincoli** | UNIQUE (`coach_id`, `athlete_id`) |
| **Note** | RLS atleta: solo proprio `athlete_id` |

### `uploaded_files`

| Aspetto | Dettaglio |
|---------|-----------|
| **Scopo** | Registro file su Storage |
| **Campi principali** | `id`, `team_id`, `athlete_id`, `bucket`, `storage_path`, `original_filename`, `file_hash`, `mime_type`, `size_bytes`, `uploaded_by` |
| **JSONB** | — |
| **Relazioni** | N:1 athletes; ref da activities, activity_jobs |
| **Vincoli** | UNIQUE (`athlete_id`, `file_hash`) |
| **Note** | Worker scarica da `storage_path` |

### `activities`

| Aspetto | Dettaglio |
|---------|-----------|
| **Scopo** | Una riga per uscita analizzata |
| **Campi principali** | `id`, `team_id`, `athlete_id`, `uploaded_file_id`, `date`, `started_at`, `source`, `file_hash`, `fit_file_url`, `status`, `profile_should_refresh` |
| **JSONB** | `summary`, `data_quality`, `parse_report`, `activity_intelligence`, `activity_charts`, `durability`, `mmp_for_profiler`, `warnings` |
| **Relazioni** | N:1 athletes; ref da twin_states, workout_assignments |
| **Vincoli** | UNIQUE (`athlete_id`, `file_hash`) |
| **Note** | `status`: `uploaded` → `processing` → `done` \| `failed` |

### `activity_jobs`

| Aspetto | Dettaglio |
|---------|-----------|
| **Scopo** | Coda ingest asincrona |
| **Campi principali** | `id`, `team_id`, `athlete_id`, `activity_id`, `uploaded_file_id`, `status`, `attempts`, `max_attempts`, `locked_at`, `locked_by`, `started_at`, `finished_at`, `error_code`, `error_message` |
| **JSONB** | `error_payload` |
| **Relazioni** | FK activities, uploaded_files |
| **Vincoli** | partial index su `status = 'pending'` |
| **Note** | Worker: `FOR UPDATE SKIP LOCKED` |

### `twin_states`

| Aspetto | Dettaglio |
|---------|-----------|
| **Scopo** | Entità centrale — `twin_state.v1` |
| **Campi principali** | `id`, `team_id`, `athlete_id`, `version`, `state_confidence`, `updated_from_activity_id` |
| **JSONB** | `twin_state` |
| **Relazioni** | 1:1 athletes (UNIQUE `athlete_id`) |
| **Vincoli** | UNIQUE (`athlete_id`, `version`) |
| **Note** | Vedi `docs/METABOLIC_CURVES_TWIN_CONTRACT.md` |

### `validation_events`

| Aspetto | Dettaglio |
|---------|-----------|
| **Scopo** | Test validati vs predizione modello |
| **Campi principali** | `parameter`, `predicted_value`, `measured_value`, `error_abs`, `error_pct`, `protocol`, `phenotype`, `data_depth_score`, `measurement_confidence`, `model_version`, `test_date` |
| **JSONB** | `raw_payload`, `backend_result` |
| **Relazioni** | N:1 teams, athletes |
| **Vincoli** | index (`athlete_id`, `parameter`, `test_date`) |
| **Note** | Salvare `predicted_value` **prima** del test |

### `workout_assignments`

| Aspetto | Dettaglio |
|---------|-----------|
| **Scopo** | Workout assegnato + compliance |
| **Campi principali** | `id`, `team_id`, `athlete_id`, `coach_id`, `date`, `status`, `completed_activity_id` |
| **JSONB** | `template`, `prescription`, `feasibility`, `compliance_result` |
| **Relazioni** | FK athletes, coaches, activities |
| **Vincoli** | index (`athlete_id`, `date`) |
| **Note** | `prescription` da `/workouts/prescribe` |

### `team_calibration_models`

| Aspetto | Dettaglio |
|---------|-----------|
| **Scopo** | Storico versioni calibrazione team |
| **Campi principali** | `id`, `team_id`, `model_version`, `created_by` |
| **JSONB** | `calibration_model`, `source_validation_events` |
| **Relazioni** | N:1 teams |
| **Vincoli** | index (`team_id`, `created_at` DESC) |
| **Note** | Fase 2 MVP — `teams.calibration_model` = current |

### `audit_log`

| Aspetto | Dettaglio |
|---------|-----------|
| **Scopo** | Tracciamento azioni sensibili |
| **Campi principali** | `id`, `team_id`, `actor_user_id`, `entity_type`, `entity_id`, `action` |
| **JSONB** | `payload` |
| **Relazioni** | N:1 teams |
| **Vincoli** | append-only |
| **Note** | Fase 2 MVP completo |

---

## 8. Campi consigliati

### `teams`

`id`, `name`, `slug`, `calibration_model` jsonb, `settings` jsonb, `created_at`, `updated_at`

### `coaches`

`id`, `user_id`, `team_id`, `name`, `email`, `role`, `created_at`, `updated_at`

### `athletes`

`id`, `team_id`, `name`, `email`, `gender`, `birth_date`, `weight_kg`, `height_cm`, `discipline`, `training_years`, `phenotype`, `latest_anchor` jsonb, `latest_snapshot` jsonb, `latest_curve` jsonb, `status`, `created_at`, `updated_at`

### `coach_athletes`

`id`, `coach_id`, `athlete_id`, `team_id`, `relationship_role`, `created_at`

### `uploaded_files`

`id`, `team_id`, `athlete_id`, `bucket`, `storage_path`, `original_filename`, `file_hash`, `mime_type`, `size_bytes`, `uploaded_by`, `created_at`

### `activities`

`id`, `team_id`, `athlete_id`, `uploaded_file_id`, `date`, `started_at`, `source`, `file_hash`, `fit_file_url`, `status`, `summary` jsonb, `data_quality` jsonb, `parse_report` jsonb, `activity_intelligence` jsonb, `activity_charts` jsonb, `durability` jsonb, `mmp_for_profiler` jsonb, `profile_should_refresh` boolean, `warnings` jsonb, `created_at`, `updated_at`

### `activity_jobs`

`id`, `team_id`, `athlete_id`, `activity_id`, `uploaded_file_id`, `status`, `attempts`, `max_attempts`, `locked_at`, `locked_by`, `started_at`, `finished_at`, `error_code`, `error_message`, `error_payload` jsonb, `created_at`, `updated_at`

### `twin_states`

`id`, `team_id`, `athlete_id`, `version`, `twin_state` jsonb, `state_confidence`, `updated_from_activity_id`, `created_at`, `updated_at`

### `validation_events`

`id`, `team_id`, `athlete_id`, `parameter`, `predicted_value`, `measured_value`, `error_abs`, `error_pct`, `protocol`, `phenotype`, `data_depth_score`, `measurement_confidence`, `model_version`, `test_date`, `raw_payload` jsonb, `backend_result` jsonb, `created_at`

### `workout_assignments`

`id`, `team_id`, `athlete_id`, `coach_id`, `date`, `status`, `template` jsonb, `prescription` jsonb, `feasibility` jsonb, `completed_activity_id`, `compliance_result` jsonb, `created_at`, `updated_at`

### `team_calibration_models`

`id`, `team_id`, `model_version`, `calibration_model` jsonb, `source_validation_events` jsonb, `created_by`, `created_at`

### `audit_log`

`id`, `team_id`, `actor_user_id`, `entity_type`, `entity_id`, `action`, `payload` jsonb, `created_at`

---

## 9. Supabase Storage

### Bucket consigliati

| Bucket | Scopo |
|--------|-------|
| `fit-files` | FIT raw immutabili |
| `exports` | Export workout erg/mrc/zwo, CSV |
| `reports` | PDF report, snapshot export |

### Layout FIT consigliato

```text
fit-files/{team_id}/{athlete_id}/{yyyy-mm-dd}/{activity_id}/{file_hash}.fit
```

### Flusso upload

1. Il **frontend carica il FIT su Storage** (presigned URL — non tramite FastAPI in produzione).
2. **Supabase salva metadati** in `uploaded_files`.
3. **Supabase crea** `activities` (status `uploaded`) e `activity_jobs` (status `pending`).
4. Il **worker processa** il job.
5. Il **backend riceve il file solo per calcolo** (download worker → multipart al backend).

### Regole

- RLS Storage per prefix `{team_id}/`
- Dedup via `file_hash` prima di nuovo job
- `activities.fit_file_url` = path o signed URL reference

---

## 10. RLS

### Principi

| Principio | Dettaglio |
|-----------|-----------|
| Team scope | Ogni accesso filtrato per `team_id` |
| Athlete scope | Ogni accesso atleta filtrato per `athlete_id` |
| Coach | Vede solo atleti assegnati via `coach_athletes` |
| Admin / owner | Vede tutto il team |
| Atleta | Vede solo se stesso |
| Worker | Service role server-side — mai nel browser |

### Ruoli consigliati

| Ruolo | Accesso tipico |
|-------|----------------|
| `owner` | Team completo + billing/settings |
| `admin` | Tutti gli atleti del team, calibrazione |
| `coach` | Atleti assegnati, upload, prescribe |
| `performance_scientist` | Read team + validation_events, Model Accuracy |
| `viewer` | Read-only roster e twin |
| `athlete` | Solo propri dati |

### Esempio concettuale policy

```sql
-- athletes: coach SELECT WHERE team_id = auth_team_id()
--            AND athlete_id IN (SELECT athlete_id FROM coach_athletes WHERE coach_id = auth_coach_id())
-- twin_states: stesso scope via athlete_id
-- activity_jobs: coach SELECT; worker ALL con service role
```

---

## 11. Service role e worker

| Attore | Service role |
|--------|--------------|
| **Frontend** | ❌ Mai — solo chiave anon/public + JWT utente |
| **Worker** | ✅ Server-side only |

Il worker deve:

- Girare **server-side** (VPS, container, Edge Function long-running con secret).
- Leggere e lockare `activity_jobs`.
- Leggare file da Storage.
- Chiamare backend HTTP.
- Aggiornare `activities`, `twin_states`, `activity_jobs` in transazione.

**Mai** includere `SUPABASE_SERVICE_ROLE_KEY` nel bundle frontend o in variabili `NEXT_PUBLIC_*`.

---

## 12. Pipeline nuova attività

Flusso end-to-end obbligatorio:

```text
 1. Frontend carica FIT su Supabase Storage
 2. Supabase salva uploaded_files
 3. Supabase crea activities con status uploaded
 4. Supabase crea activity_jobs con status pending
 5. Worker prende il job (FOR UPDATE SKIP LOCKED)
 6. Worker imposta job status processing (+ locked_at, locked_by)
 7. Worker scarica il FIT da Storage
 8. Worker chiama backend:
      POST /ride/parse
      POST /ride/data-quality
      POST /ride/summary
      POST /ride/ingest
      POST /twin/state/update-from-ride
 9. Worker salva in transazione:
      activities.parse_report
      activities.data_quality
      activities.summary
      activities.mmp_for_profiler
      activities.profile_should_refresh
      twin_states.twin_state
10. Worker imposta activities.status = done
11. Worker imposta activity_jobs.status = done, finished_at
12. Frontend aggiorna UI (TanStack Query invalidation / Realtime)
```

**Idempotenza:** se `file_hash` già esiste per `athlete_id`, non ricalcolare load — ritornare esistente o replace esplicito documentato.

---

## 13. Endpoint backend usati dal worker

### MVP (sequenza obbligatoria)

| Metodo | Path | Client `api.*` |
|--------|------|----------------|
| POST | `/ride/parse` | `rideParse` |
| POST | `/ride/data-quality` | `rideDataQuality` |
| POST | `/ride/summary` | `rideSummary` |
| POST | `/ride/ingest` | `ingestRide` |
| POST | `/twin/state/update-from-ride` | `twinStateUpdateFromRide` |

### Candidato futuro

| Metodo | Path | Note |
|--------|------|------|
| POST | `/ride/full-bundle` | `rideFullBundle` — usare **solo** quando il contratto bundle è congelato e il worker è aggiornato |

Non adottare `/ride/full-bundle` in MVP senza allineamento esplicito backend + worker + frontend facade.

---

## 14. JSON da salvare come jsonb

Supabase deve salvare **senza alterare**:

| Payload backend | Destinazione tipica |
|-----------------|---------------------|
| Ride summary | `activities.summary` |
| Data quality report | `activities.data_quality` |
| Parse report | `activities.parse_report` |
| Activity intelligence | `activities.activity_intelligence` |
| Activity charts | `activities.activity_charts` |
| Durability | `activities.durability` |
| Profile snapshot | `athletes.latest_snapshot`, `twin_state.metabolic_snapshot` |
| Metabolic curves | `twin_state.metabolic_curves` |
| TwinState completo | `twin_states.twin_state` (`twin_state.v1`) |
| Validation result | `validation_events.backend_result` |
| Workout prescription | `workout_assignments.prescription` |
| Workout feasibility | `workout_assignments.feasibility` |
| Workout compliance | `workout_assignments.compliance_result` |
| Coach decision output | cache effimera o colonna JSON opzionale |
| Team calibration model | `teams.calibration_model`, `team_calibration_models` |

### Regola

```text
Non normalizzare prematuramente tutto.
Salvare JSONB completi + pochi campi indicizzati/scalari per liste e filtri.
```

---

## 15. Indici e vincoli consigliati

### Indici

```text
teams.slug
coaches.user_id
coaches.team_id
athletes.team_id
coach_athletes.coach_id
coach_athletes.athlete_id
activities.athlete_id
activities.team_id
activities.date
activities.file_hash
activity_jobs.status
activity_jobs.created_at
twin_states.athlete_id
validation_events.athlete_id
validation_events.parameter
validation_events.test_date
workout_assignments.athlete_id
workout_assignments.date
```

### Vincoli unici

```text
UNIQUE (athlete_id, file_hash)          ON activities
UNIQUE (athlete_id, version)            ON twin_states
UNIQUE (coach_id, athlete_id)           ON coach_athletes
UNIQUE (athlete_id, file_hash)          ON uploaded_files  (dedup upload)
UNIQUE (team_id, slug)                  ON teams
```

---

## 16. Cosa NON deve fare Supabase

Supabase **non** deve:

- Calcolare VO₂max
- Calcolare VLamax
- Calcolare MLSS
- Calcolare FatMax
- Calcolare W′
- Calcolare CTL / ATL / TSB
- Fare parsing FIT
- Interpretare RR / HRV
- Duplicare zone metaboliche
- Riscrivere motori Python
- Inventare `confidence_score`
- Modificare payload fisiologici senza passare dal backend

---

## 17. Cosa può fare Supabase

Supabase **può**:

- Salvare JSON
- Filtrare e indicizzare
- Proteggere con RLS
- Orchestrare job
- Notificare (email, push, webhook)
- Schedulare job (pg_cron, queue esterna)

### Campi derivati semplici (ammessi)

Copiati **da output backend**, non ricalcolati:

| Campo derivato | Fonte |
|----------------|-------|
| `latest_activity_date` | `MAX(activities.date)` o copy da twin |
| `activity_count` | `COUNT(activities)` |
| `last_job_status` | `activity_jobs.status` latest |
| `athlete_status_color` | copy da `twin_state` cross_validation |
| `has_recent_warning` | copy da warnings in summary/twin |
| `latest_twin_confidence` | copy da `state_confidence` |
| `latest_mlss_w` | copy da `metabolic_snapshot` |
| `latest_vo2max` | copy da snapshot headline |
| `latest_vlamax` | copy da snapshot headline |

Aggiornare questi campi in **trigger/worker post-backend**, mai con formule fisiologiche proprie.

---

## 18. Frontend read model

### Team Command Center

| Legge da | Contenuto |
|----------|-----------|
| `teams` | nome, calibration_model headline |
| `athletes` | roster, status, headline KPI |
| `twin_states` | confidence, cross_validation |
| `activities` (latest) | ultima uscita per atleta |
| `validation_events` (latest) | test recenti |
| `workout_assignments` (current week) | piano settimana |

### Athlete Digital Twin

| Legge da | Contenuto |
|----------|-----------|
| `athletes` | anagrafica, headline |
| `twin_states` | blob completo |
| `validation_events` | storico test |
| `activities` (latest) | ultima uscita |

### Activity Analysis

| Legge da | Contenuto |
|----------|-----------|
| `activities` | summary, charts, durability |
| `activity_jobs` | progresso ingest |
| `uploaded_files` | metadata file |

### Testing Lab

| Legge da | Contenuto |
|----------|-----------|
| `validation_events` | eventi test |
| `athletes.latest_anchor` | anchor misurato |
| `athletes.latest_snapshot` | snapshot pre-test |

### Coach Planner

| Legge da | Contenuto |
|----------|-----------|
| `workout_assignments` | piano e compliance |
| `twin_states` | contesto fattibilità |
| `activities` (recent) | uscite recenti |

Backend live solo per prescribe/feasibility/compare e coach decision — vedi `docs/FRONTEND_API_FACADE.md`.

---

## 19. Error handling

Ogni job fallito deve persistere:

| Campo | Contenuto |
|-------|-----------|
| `error_code` | Codice macchina |
| `error_message` | Messaggio coach-safe |
| `error_payload` | Response body, stack troncato |
| `attempts` | Numero tentativo |
| `finished_at` | Timestamp fine |

### Esempi `error_code`

| Codice | Causa |
|--------|-------|
| `fit_parse_failed` | FIT corrotto o non Garmin |
| `missing_power_data` | Backend 422 — no power stream |
| `backend_timeout` | Timeout HTTP worker → backend |
| `backend_422` | Validazione input fallita |
| `duplicate_file` | `file_hash` già processato |
| `storage_download_failed` | File non trovato su Storage |

### Distinzione UI

| Tipo | Presentazione |
|------|---------------|
| Errore tecnico job | Banner rosso + `activity_jobs` failed |
| Dato fisiologico mancante | Empty state informativo (non errore job) |
| Low confidence | Badge giallo su metrica |

---

## 20. Sicurezza

| Componente | Credenziali |
|------------|-------------|
| **Frontend** | Solo chiavi pubbliche Supabase (`anon` key) + JWT utente |
| **Worker** | `service_role` server-side only |
| **Backend** | `api_key`, JWT, o header `X-Athlete-Id` secondo deploy finale (`docs/DEPLOY_BACKEND.md`) |

### Divieti

- ❌ `service_role` nel frontend o env `NEXT_PUBLIC_*`
- ❌ Backend esposto senza auth in production
- ❌ Storage bucket pubblico senza policy prefix team

---

## 21. Ambienti

Prevedere tre ambienti:

| Ambiente | Uso |
|----------|-----|
| `local` | Dev frontend + backend locale + Supabase local o project dev |
| `staging` | QA integrazione worker + RLS |
| `production` | Coach live |

Ogni ambiente deve avere:

- Supabase project separato **oppure** schema separato
- Backend URL dedicato (`BACKEND_BASE_URL`)
- Storage bucket dedicato
- Chiavi separate (anon, service_role, backend api_key)
- Policy RLS testate con utenti di prova per ogni ruolo §10

---

## 22. Minimum Supabase MVP

### Fase 1 (obbligatorio)

- [ ] Auth
- [ ] `teams`, `coaches`, `athletes`, `coach_athletes`
- [ ] `uploaded_files`, `activities`, `activity_jobs`
- [ ] `twin_states`, `validation_events`, `workout_assignments`
- [ ] Storage bucket `fit-files`
- [ ] RLS base (team + coach + athlete)
- [ ] Worker con service role

### Fase 2 (rimandare)

- `team_calibration_models` avanzati
- `audit_log` completo
- Notifiche push/email
- Dashboard aggregate materializzate
- Billing
- Multi-tenant avanzato (sub-team, federations)

---

## 23. Definition of Done Supabase

Il layer Supabase è **pronto per MVP** quando:

- [ ] Esiste migration SQL (`supabase/migrations/`)
- [ ] Esistono RLS policy testate per ogni ruolo
- [ ] Esiste bucket FIT con policy Storage
- [ ] Il frontend può creare atleta
- [ ] Il frontend può caricare FIT su Storage
- [ ] Viene creato un `activity_job` automaticamente
- [ ] Il worker può processare il job end-to-end
- [ ] L'attività viene salvata con JSON backend intatti
- [ ] Il TwinState viene aggiornato in transazione
- [ ] Il coach vede solo i propri atleti
- [ ] L'atleta vede solo se stesso
- [ ] Il file duplicato non aggiorna due volte il carico (idempotenza)
- [ ] Gli errori job sono visibili in UI (`error_code`, `error_message`)
- [ ] Nessun calcolo fisiologico è duplicato in SQL

---

## 24. Deliverable richiesti al team Supabase

Il team Supabase produrrà in **PR successive** (non in questa PR):

### SQL migrations

```text
supabase/migrations/001_initial_schema.sql
supabase/migrations/002_rls_policies.sql
supabase/migrations/003_storage_policies.sql
```

### Documentazione

```text
docs/SUPABASE_SCHEMA.md
docs/SUPABASE_RLS.md
docs/SUPABASE_WORKER_FLOW.md
```

### Esempi TypeScript (Supabase client)

| Esempio | Operazione |
|---------|------------|
| `createAthlete` | INSERT athletes + twin_states vuoto |
| `uploadFit` | Storage upload + uploaded_files + activities + activity_jobs |
| `createActivityJob` | INSERT activity_jobs pending (se non auto) |
| `readAthleteDashboard` | SELECT athletes + twin_states headline |
| `readActivityAnalysis` | SELECT activities + activity_jobs |
| `readTwinState` | SELECT twin_states per athlete_id |

Gli esempi devono usare il client Supabase con JWT utente (non service role) per il frontend; il worker avrà modulo separato con service role.

---

## Documenti correlati

| Documento | Contenuto |
|-----------|-----------|
| `docs/INGEST_PIPELINE_ARCHITECTURE.md` | Pipeline S3/VPS equivalente |
| `docs/FRONTEND_API_FACADE.md` | Flussi frontend |
| `docs/METABOLIC_CURVES_TWIN_CONTRACT.md` | Struttura twin_state |
| `docs/FRONTEND_IMPLEMENTATION_BLUEPRINT.md` | Pagine coach |
| `docs/API_ENDPOINT_INDEX.md` | 135 path backend |

---

## Changelog

| Date | Version | Change |
|------|---------|--------|
| 2026-07-05 | 1.0.0 | Initial Supabase handoff contract for V5.2.6 |
| 2026-07-05 | 1.1.0 | Full 24-section handoff: RLS roles, pipeline, indices, DoD, deliverables |

---

*Documento di handoff platform — nessuna modifica a runtime backend, OpenAPI, workflow, frontend, test, Makefile o README in questa revisione.*
