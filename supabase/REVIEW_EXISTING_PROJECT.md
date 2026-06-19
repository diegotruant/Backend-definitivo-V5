# Revisione progetto Supabase esistente → Backend V5.1

**Progetto:** `xdqvjqqwywuguuhsehxm`  
**URL:** https://xdqvjqqwywuguuhsehxm.supabase.co

Questo documento guida il confronto tra lo schema già creato e i requisiti del backend **Digital Twin V5.1**.

---

## Cosa cambia con il backend V5

| Area | Schema “vecchio” tipico | Target V5.1 |
|------|-------------------------|-------------|
| **Stato atleta** | Colonne sparse (`ftp`, `vo2max`, `latest_curve`…) | **`twin_states.state_json`** — blob `twin_state.v1` unico |
| **Attività** | `fit_url` + pochi campi | **`activities.*_json`** — cache di `/ride/summary`, `/ride/intelligence`, `/ride/durability`, `/ride/data-quality`, `/ride/ingest` |
| **Tenant** | `teams` o nessun isolamento | **`coaches`** (JWT `team_id` = `coaches.id`) + RLS |
| **Atleta guest** | Non previsto | `athletes.user_id` nullable (tablet `type: guest`) |
| **Auth backend** | Anon key only | JWT Supabase con claims `role`, `team_id`, `athlete_id` |
| **Calibrazione** | Per atleta o assente | **`coach_calibration`** — output `/team/calibration/update` |
| **Workout** | Tabella generica | Schema `workout_*` in `docs/workout_db_schema_v1.sql` |

---

## Procedura di audit (15 minuti)

### Step A — Esporta schema attuale

1. Apri [SQL Editor](https://supabase.com/dashboard/project/xdqvjqqwywuguuhsehxm/sql)
2. Esegui tutto il file `supabase/scripts/audit_existing_schema.sql`
3. Esporta i risultati (o incolla qui le sezioni 1, 2, 4, 10)

### Step B — Confronto tabella per tabella

Per ogni tabella esistente, chiediti:

| Domanda | Se NO → azione |
|---------|----------------|
| Ha RLS abilitato? | Aggiungere policy coach/athlete |
| `athlete_id` è UUID stabile usato dal backend? | Allineare a `athletes.id` |
| I JSON sono compatibili con output API V5? | Migrare formato o ricostruire via worker |
| Ci sono colonne duplicate di TwinState? | Spostare in `twin_states`, deprecare colonne |

### Step C — Scegli strategia migrazione

**Opzione 1 — Evolutiva (consigliata se hai già utenti/dati)**  
- Mantieni tabelle esistenti dove possibile  
- Aggiungi `twin_states`, `activities` nuove colonne JSONB  
- Script di backfill da colonne legacy → TwinState  
- Depreca colonne vecchie dopo validazione  

**Opzione 2 — Greenfield su stesso progetto**  
- Nuovo schema `public_v5` o rename tabelle legacy → `*_legacy`  
- Applica migration step-by-step da `supabase/migrations/`  
- Migrazione dati one-shot  

**Opzione 3 — Nuovo progetto Supabase**  
- Solo se lo schema attuale è molto diverso e senza dati produzione  

---

## Mapping nomi comuni (vecchio → nuovo)

| Possibile nome attuale | Target V5 |
|------------------------|-----------|
| `teams` | `coaches` (o view `teams` → `coaches` per compatibilità) |
| `users` / `user_profiles` | `profiles` |
| `riders` / `clients` | `athletes` |
| `sessions` / `workouts_log` | `activities` |
| `athlete_data` / `digital_twin` | `twin_states` |
| `fit_files` | path in `activities.s3_key` + bucket S3 |

---

## Checklist compatibilità backend

Configura il backend VPS con:

```env
DIGITAL_TWIN_AUTH_MODE=jwt
DIGITAL_TWIN_JWT_JWKS_URL=https://xdqvjqqwywuguuhsehxm.supabase.co/auth/v1/.well-known/jwks.json
DIGITAL_TWIN_JWT_ISSUER=https://xdqvjqqwywuguuhsehxm.supabase.co/auth/v1
DIGITAL_TWIN_REQUIRE_ATHLETE_ID=true
DIGITAL_TWIN_CORS_ORIGINS=https://tuo-frontend.it
```

JWT claims richiesti dal backend (`api/auth/principal.py`):

| Claim | Coach | Atleta |
|-------|-------|--------|
| `sub` | user uuid | user uuid |
| `role` / `roles` | `coach` | `athlete` |
| `team_id` | `coaches.id` | `coaches.id` del proprio coach |
| `athlete_id` | — | `athletes.id` |
| `athlete_ids` | lista id atleti del coach | — |

---

## Prossimo passo insieme

1. Esegui l'audit SQL e condividi l'output (almeno lista tabelle + colonne)
2. Decidiamo **evolutiva vs greenfield**
3. Finalizziamo Step 1 (`profiles`, `coaches`, `athletes`) adattato al tuo schema
4. Step 2: `twin_states` + `activities` allineati agli endpoint `/ride/*` e `/twin/*`
