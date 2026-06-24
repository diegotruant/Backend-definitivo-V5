# Supabase Schema — Roadmap V5.2.2 (rivisto)

**Backend:** Digital Twin **v5.2.2** — **106 endpoint** OpenAPI  
**Progetto Supabase:** https://xdqvjqqwywuguuhsehxm.supabase.co

> ⚠️ **Revisione necessaria:** il piano precedente (43 endpoint, V5.1) non copre
> profile extended, lab, ride analytics, glycolytic/VLamax a 3 livelli.
> Le tabelle `coaches`, `athletes`, `activities` già presenti restano valide come base,
> ma vanno **estese** — non buttate.

---

## Cosa cambia con V5.2

| Area | Prima (V5.1) | Ora (V5.2.2) |
|------|--------------|--------------|
| Endpoint HTTP | ~43 | **106** (+63) |
| VLamax | Un numero in snapshot | **3 fonti** distinte (modello / proxy potenza / sangue vLaPeak) |
| Zone | Solo Coggan | **Dual:** `metabolic_power` + `coggan_power` |
| Ride analytics | 7 route `/ride/*` | +24 route `/ride/analytics/*` |
| Lab / test | Solo `/test/*` | +7 route `/lab/*` + validazione glicolitica |
| Profilo | `/profile/snapshot` | +14 route (`kalman`, `bayesian`, `glycolytic-profile`, …) |

**Principio invariato:** il backend è stateless. Supabase persiste JSON; il worker chiama le API.

---

## Stato progetto Supabase esistente (audit)

| Tabella | Esiste | Azione V5.2 |
|---------|--------|-------------|
| `coaches` | ✅ | Tenere + RLS |
| `athletes` | ✅ | Tenere + colonne fisiologiche base |
| `activities` | ✅ | **Estendere** con colonne JSONB analytics |
| `twin_states` | ❌ | **Creare** — priorità massima |
| `profiles` | ❌ | Aggiungere (auth/ruoli) |
| `lab_results` | ❌ | Nuova (fase 2) |
| `test_sessions` | ❌ | Nuova (fase 2) |
| `processing_jobs` | ❌ | Nuova (pipeline FIT) |
| `workout_*` | ❌ | Fase 3 |

---

## Roadmap rivista (7 step)

### Step 1 — Identità e tenant ✅ bozza esistente
`profiles`, `coaches`, `athletes` + RLS  
→ Adattare allo schema già presente (non ricreare coaches/athletes)

### Step 2 — Cuore motore (priorità)
- `twin_states` — blob `twin_state.v1` con `metabolic_snapshot.glycolytic_profile`
- Estendere `activities`:
  - `summary_json` (dual zones, cadence_anchor, resilience)
  - `intelligence_json`, `durability_json`, `data_quality_json`, `ingest_json`
  - `analytics_json` — cache slice `/ride/analytics/*` usate in UI

### Step 3 — VLamax e validazione (nuovo focus V5.2)
- `validation_events` — parametro: `vlamax`, `vlapeak`, `power_proxy_vlamax`, `mlss`, `vo2max`
- `lab_results` — output `/lab/*`
- `test_sessions` — tablet + `glycolytic_validation` da Wingate
- **Mai** una colonna scalare `vlamax` senza `vlamax_source`

### Step 4 — Pipeline ingest
- `processing_jobs` — stato worker (pending → ready)
- Mapping endpoint worker → colonne DB (vedi `SCHEMA_V5.2_PERSISTENCE.md`)

### Step 5 — Workout system
- Tabelle da `docs/workout_db_schema_v1.sql`

### Step 6 — Integrazioni
- Strava tokens, dedup (`/integrations/*`)

### Step 7 — Indici e viste dashboard
- KPI coach, readiness, glycolytic flux index

---

## VLamax — regola d'oro per lo schema

Tre campi **separati**, mai fusi in UI o DB:

| Campo JSON | Fonte | Endpoint |
|------------|-------|----------|
| `estimated_vlamax_mmol_l_s` | Modello Mader/MMP | `/profile/snapshot` |
| `power_derived_vlamax` | Proxy da traccia potenza | `/profile/vlamax-from-power-series` |
| `observed_vlapeak_mmol_l_s` | Lattato sangue | `/lab/vlapeak/observed`, Wingate |

In `twin_states.state_json` vivono dentro `metabolic_snapshot.glycolytic_profile`.

---

## File di riferimento

| File | Contenuto |
|------|-----------|
| `supabase/SCHEMA_V5.2_PERSISTENCE.md` | Mapping API → colonne JSONB |
| `supabase/migrations/001_identity_tenancy.sql` | Step 1 (adattare, non applicare ciecamente) |
| `supabase/scripts/audit_existing_schema.sql` | Audit progetto esistente |
| `docs/API_ENDPOINT_INDEX.md` | Inventario 106 endpoint |
| `docs/FRONTEND_DEVELOPER_GUIDE.md` §6.8 | Semantica VLamax UI |

---

## Prossimo passo insieme

1. Mandare colonne di `coaches`, `athletes`, `activities` (query audit sezione 2)
2. Finalizzare Step 1 **adattato** (ALTER, non DROP)
3. Scrivere migration Step 2: `twin_states` + estensione `activities`
