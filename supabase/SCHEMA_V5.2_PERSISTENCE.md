# Mapping persistenza Supabase ↔ API V5.2.2

Questo documento definisce **cosa salvare** in Supabase per ogni dominio API.
Non serve una colonna per ogni endpoint — si raggruppa per **blob canonico** vs **cache attività**.

---

## Strategia a 3 livelli

```
Livello 1 — CANONICO (sempre persistere)
  twin_states.state_json          → TwinState v1 completo
  athletes                        → dati anagrafici/fisiologici input motori

Livello 2 — PER ATTIVITÀ (persistere dopo ingest)
  activities.*_json               → output /ride/* e /ride/analytics/* usati in UI

Livello 3 — ON-DEMAND (ricalcolabile, cache opzionale)
  explainability, race simulate, meta/chart-config
```

---

## TwinState — campi critici V5.2

Path in `state_json` (JSONB):

```json
{
  "schema_version": "twin_state.v1",
  "athlete_id": "uuid",
  "metabolic_snapshot": {
    "glycolytic_profile": {
      "estimated_vlamax_mmol_l_s": 0.45,
      "power_derived_vlamax": { "estimated_vlamax_mmol_l_s": 0.52, "method": "power_series_glycolytic_proxy_v1" },
      "vlamax_derivation": { "agreement": { "verdict": "coherent" } },
      "glycolytic_flux_index": 72
    }
  },
  "rolling_power_curve": {},
  "load_state": {},
  "readiness_state": {},
  "physiological_resilience": {},
  "power_source_state": {}
}
```

**Tabella:** `twin_states (athlete_id PK, state_json jsonb, schema_version text, updated_at)`

---

## Activities — colonne JSONB consigliate

| Colonna | Endpoint worker | Contenuto chiave V5.2 |
|---------|-----------------|----------------------|
| `summary_json` | `POST /ride/summary` | `sections.zones.metabolic_power`, `sections.zones.coggan_power`, `cadence_anchor` |
| `intelligence_json` | `POST /ride/intelligence` | best efforts, chart series |
| `durability_json` | `POST /ride/durability` | Mader session durability |
| `data_quality_json` | `POST /ride/data-quality` | sensor flags |
| `ingest_json` | `POST /ride/ingest` | MMP curve update, `profile_should_refresh` |
| `analytics_json` | `/ride/analytics/*` selezionati | oggetto con chiavi per slice usate in UI |

### `analytics_json` — struttura suggerita

```json
{
  "zones": {},
  "statistics": {},
  "power": {},
  "hrv": {},
  "cardiac": {},
  "w_prime_balance": {},
  "metabolic_flexibility": {},
  "adaptive_load": {},
  "segments": {},
  "resilience": {}
}
```

Il worker popola **solo** le chiavi necessarie alla pagina Activity Analysis (fase 1: `zones`, `statistics`, `power`, `hrv`).

---

## Pipeline worker — sequenza V5.2

```
FIT su S3
  → INSERT activities (status=pending)
  → POST /ride/data-quality
  → POST /ride/ingest
  → POST /ride/summary
  → POST /ride/intelligence
  → POST /ride/durability
  → POST /ride/analytics/zones
  → POST /ride/analytics/statistics
  → POST /ride/analytics/power
  → [se sprint] POST /profile/vlamax-from-power-series
  → POST /twin/state/update-from-ride
  → [se profile_should_refresh] POST /profile/snapshot → merge TwinState
  → UPDATE activities SET status=ready, *_json=...
  → UPSERT twin_states
```

---

## Profilo atleta — endpoint e dove salvare

| Endpoint | Dove persistere |
|----------|-----------------|
| `POST /profile/snapshot` | `twin_states.state_json.metabolic_snapshot` |
| `POST /profile/glycolytic-profile` | idem + eventuale cache `athletes.glycolytic_profile_json` |
| `POST /profile/vlamax-from-power-series` | dentro glycolytic_profile o `activities.analytics_json` per sprint |
| `POST /profile/kalman/trajectory` | `athletes.kalman_trajectory_json` (opzionale) |
| `POST /profile/snapshot/bayesian` | `athletes.bayesian_snapshot_json` (opzionale) |
| `POST /test/confirm` | TwinState `measured_anchor` + `validation_events` |
| `POST /lab/vlapeak/validate` | `validation_events` + `lab_results` |

---

## validation_events — parametri V5.2

| parameter | predicted from | measured from |
|-----------|----------------|---------------|
| `vlamax` | Mader snapshot | test confermato |
| `vlapeak` | `predicted_vlapeak` | `/lab/vlapeak/observed` |
| `power_proxy_vlamax` | `estimated_vlamax_mmol_l_s` | `power_derived_vlamax` |
| `mlss` | snapshot CP | test lattato |
| `vo2max` | snapshot | lab/spiro |

---

## Endpoint che NON richiedono colonna dedicata

| Gruppo | Motivo |
|--------|--------|
| `/explainability/*` | Narrative rigenerabili |
| `/meta/*` | Config statica |
| `/integrations/*` | Transiente pipeline |
| `/race/gpx/*` | Cache opzionale `race_analyses` solo se feature attiva |

---

## Migrazione da schema esistente

Per `activities` già presente:

```sql
-- Esempio: aggiungere colonne mancanti senza perdere dati
ALTER TABLE activities ADD COLUMN IF NOT EXISTS summary_json jsonb;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS intelligence_json jsonb;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS durability_json jsonb;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS data_quality_json jsonb;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS ingest_json jsonb;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS analytics_json jsonb;
ALTER TABLE activities ADD COLUMN IF NOT EXISTS processing_status text DEFAULT 'pending';
ALTER TABLE activities ADD COLUMN IF NOT EXISTS backend_version text DEFAULT '5.2.2';
```

Se avete colonne legacy (`summary`, `fit_url` senza `_json`), mappiamole nella revisione colonne.

---

## Checklist compatibilità frontend

Dopo ogni migration:

```bash
make openapi-frontend   # rigenera client.ts con 106 endpoint
```

Il frontend legge da Supabase; chiama il backend solo per azioni live (prescribe, test, simulate).
