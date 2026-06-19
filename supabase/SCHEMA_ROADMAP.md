# Supabase Schema — Roadmap passo passo

**Progetto esistente:** https://xdqvjqqwywuguuhsehxm.supabase.co  
**Audit schema attuale:** `supabase/scripts/audit_existing_schema.sql`  
**Guida revisione V5:** `supabase/REVIEW_EXISTING_PROJECT.md`

Questo documento guida la costruzione dello schema insieme al team.
Ogni step va rivisto e approvato prima di passare al successivo.
Prima di applicare le migration, eseguire l'audit sul progetto già creato.

## Principi guida

1. **TwinState è il cuore** — `twin_states.state_json` è il blob canonico `twin_state.v1`.
2. **Il frontend legge da Supabase** — le colonne JSONB sulle `activities` sono cache di output backend.
3. **Isolamento coach** — un coach vede solo i propri atleti (RLS + JWT claims).
4. **Compatibilità backend** — JWT claim `team_id` = `coaches.id`; header `X-Athlete-Id` = `athletes.id`.
5. **Normalizzazione minima** — dati tabellari per query/lista; blob JSON per output motori.

## Mappa entità (6 step)

| Step | Tabelle | Scopo |
|------|---------|-------|
| **1** | `profiles`, `coaches`, `athletes` | Identità, tenant, RLS base |
| **2** | `twin_states`, `activities` | Cuore motore + pipeline FIT |
| **3** | `validation_events`, `coach_calibration` | Team learning + test lab |
| **4** | `workout_*` (6 tabelle) | Prescrizione e compliance |
| **5** | `integrations`, `processing_jobs` | Strava, webhook, coda ingest |
| **6** | viste materializzate / indici | Dashboard coach, performance query |

## Step 1 — in review

File: `supabase/migrations/001_identity_tenancy.sql`

## Step 2 — prossimo (dopo OK step 1)

- `twin_states` (1:1 con atleta)
- `activities` con path S3, status pipeline, JSON output backend

## Domande aperte (da risolvere nello step 1)

- [ ] Un coach = un tenant fisso, o servono più "squadre" sotto lo stesso coach?
- [ ] Tutti gli atleti hanno login app, o solo alcuni?
- [ ] Serve ruolo `assistant_coach` fin da subito?
- [ ] Admin piattaforma (voi) con accesso cross-tenant?
