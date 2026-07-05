# Frontend API Facade — Digital Twin Backend V5.2.6

**Repository:** `diegotruant/Backend-definitivo-V5`  
**Versione backend:** 5.2.6  
**Client tipizzato:** `frontend/src/api/client.ts` (135 metodi — trasporto HTTP)  
**Companion:** `docs/STABLE_BACKEND_SURFACE.md`, `docs/FRONTEND_DEVELOPER_GUIDE.md`

---

## 1. Scopo

Questo documento definisce la **facciata frontend ufficiale** del backend Digital Twin.

Il backend espone **135 endpoint OpenAPI**, ma il frontend non deve usarli tutti in modo diretto e confuso. L'obiettivo è trasformare quella superficie ampia in **pochi flussi prodotto** comprensibili da coach e sviluppatori frontend.

```text
135 endpoint backend  →  pochi flussi frontend comprensibili
```

### Cosa stabilisce questo documento

| Obiettivo | Dettaglio |
|-----------|-----------|
| Facciata ufficiale | Nomi di dominio stabili (`onboardAthlete`, non `api.proposeTest` sparsi nei `.tsx`) |
| Riduzione complessità | 7 flussi MVP + 6 pagine prodotto ufficiali |
| Supabase vs backend | Quando **leggere** da DB e quando **chiamare** il backend live |
| Nessuna duplicazione fisiologica | Il frontend non ricalcola motori Python; mostra output backend con tier e warning |

### Layer architetturali

```text
┌─────────────────────────────────────────────────────────┐
│  Pagine React (Team Command Center, Digital Twin, …)    │
└──────────────────────────┬──────────────────────────────┘
                           │ facade.* / hooks
┌──────────────────────────▼──────────────────────────────┐
│  frontend/src/services/*Facade.ts                       │
└────────────┬─────────────────────────────┬──────────────┘
             │ Supabase (read/write)        │ api.* (compute)
┌────────────▼──────────────┐  ┌───────────▼──────────────┐
│  Postgres / Supabase       │  │  FastAPI V5.2.6          │
│  teams, athletes, …        │  │  stateless engines       │
└────────────────────────────┘  └──────────────────────────┘
```

**Regola:** i componenti leaf **non** importano `api` né fanno `fetch` sparsi. Passano da facade/hooks.

---

## 2. Principio generale

### Backend stateless

Il backend **non** è il database dell'atleta. È un motore di calcolo: riceve payload, esegue motori fisiologici, restituisce JSON. Non mantiene sessioni né stato persistente tra richieste.

### Supabase come source of truth UI

Supabase (Postgres) salva:

- dati anagrafici team e atleti;
- attività e job di ingest;
- **TwinState** completo;
- workout assegnati e compliance;
- eventi di validazione e modelli di calibrazione team.

### Quando il frontend legge da Supabase

| Scenario | Azione |
|----------|--------|
| Aprire Digital Twin | Leggi `twin_states.twin_state` |
| Lista attività / dettaglio già analizzato | Leggi `activities.summary`, `activities.bundle` (se presente) |
| Dashboard coach mattutina | Leggi twin + load da DB; chiama backend solo per brief live |
| Storico validazioni | Leggi `validation_events` |
| Workout assegnati | Leggi `workout_assignments` |

### Quando il frontend chiama il backend live

| Scenario | Azione |
|----------|--------|
| Nuovo upload FIT | Ingest + summary + aggiornamento TwinState |
| Nuovo test / onboarding | propose → confirm → snapshot → twin/build |
| What-if / proiezione stagione | `projectionSeason`, `twinStateProject` |
| Decision support coach | `coachDailyBrief`, `coachSessionDecision`, … |
| Prescrizione workout | `validateWorkout` → `prescribeWorkout` |
| Validazione test lattato | `labLactateValidateModel` + calibrazione team |
| Aggiornamento TwinState post-ride/workout | `twinStateUpdateFromRide`, `twinStateUpdateFromWorkout` |

### Evitare duplicazione fisiologica

Il frontend **mostra** output dei motori backend. Non **ricalcola** curve metaboliche, zone, CTL/ATL/TSB, VO₂max, VLamax, MLSS, FatMax, parsing FIT o analisi HRV.

---

## 3. Stack consigliato

| Layer | Tecnologia | Ruolo |
|-------|------------|-------|
| UI | **React + TypeScript** | Pagine coach/atleta |
| Server state | **TanStack Query** | Cache, retry, stati loading/error per facade |
| Persistenza | **Supabase client** | Read/write su tabelle ufficiali |
| Grafici | **ECharts** / **Recharts** / **Nivo** | Render da `activity_charts` o `metaChartConfig` |
| Form | **React Hook Form** | Upload FIT, conferma test, editor workout |
| Tabelle | **TanStack Table** | Roster atleti, eventi validazione, assignments |
| HTTP backend | **`frontend/src/api/client.ts`** | Unico client OpenAPI — **solo dentro le facade** |

### Divieti

- ❌ `fetch('/ride/summary')` nei componenti
- ❌ `axios` parallelo non tipizzato
- ❌ Logica fisiologica nei `.tsx`
- ❌ Import diretto di `api` nei componenti leaf (eccezione temporanea: migrazione legacy documentata)

---

## 4. Flussi frontend ufficiali (7)

| # | Flusso | Facade target |
|---|--------|---------------|
| F1 | Onboarding atleta | `athleteFacade.onboardAthlete` |
| F2 | Upload nuova attività FIT | `activityFacade.uploadActivity` |
| F3 | Analisi attività | `activityFacade.analyzeActivity` |
| F4 | Digital Twin atleta | `twinFacade.loadTwin` / `twinFacade.refreshTwin` |
| F5 | Prescrizione workout | `workoutFacade.prescribeWorkout` |
| F6 | Confronto workout eseguito | `workoutFacade.compareCompletedWorkout` |
| F7 | Coach daily decision | `coachFacade.dailyDecision` |

---

## 5. Dettaglio per flusso

### F1 — Onboarding atleta

**Scopo:** creare profilo fisiologico iniziale da test FIT (sprint + CP) e costruire il primo TwinState.

**Pagine / componenti:**

- Testing Lab → upload test FIT
- Athlete setup wizard
- Team Command Center → nuovo atleta

**Endpoint backend:**

| Metodo | Path | Client `api.*` |
|--------|------|----------------|
| POST | `/test/propose` | `proposeTest` |
| POST | `/test/confirm` | `confirmTest` |
| POST | `/profile/snapshot` | `profileSnapshot` |
| POST | `/twin/state/build` | `twinStateBuild` |
| POST | `/twin/state/validate` | `twinStateValidate` |

**Supabase — leggere / salvare:**

| Tabella | Operazione | Contenuto |
|---------|------------|-----------|
| `athletes` | INSERT | anagrafica, `team_id`, peso, genere |
| `twin_states` | INSERT | blob `twin_state` completo |
| `measured_profile` | INSERT (opz.) | anchor da `confirmTest` |
| `validation_events` | INSERT (se test validato) | predicted/measured |

**Regole UI:**

- Mostrare proposta test (`ProfileProposal`) prima della conferma coach
- Badge `confidence_score`, `tier`, `cross_validation.severity`
- Distinguere **misurato FIT** vs **modello fisiologico**

**Warning da mostrare:**

- MMP insufficienti (< 3 durate diverse)
- Sprint non identificato o CP ambiguo
- `warnings[]` da `profileSnapshot` e `twinStateValidate`

**Cosa NON deve fare il frontend:**

- Non calcolare VO₂max / VLamax / MLSS localmente
- Non saltare `twinStateValidate` prima di persistere
- Non chiamare endpoint LABS senza approvazione prodotto

---

### F2 — Upload nuova attività FIT

**Scopo:** ingerire un file FIT di uscita, aggiornare load curve e TwinState.

**Pagine / componenti:**

- Activity Analysis → upload
- Athlete home → “Nuova uscita”
- Background worker (stesso flusso via facade server-side)

**Endpoint backend:**

| Metodo | Path | Client `api.*` |
|--------|------|----------------|
| POST | `/ride/parse` | `rideParse` |
| POST | `/ride/data-quality` | `rideDataQuality` |
| POST | `/ride/summary` | `rideSummary` |
| POST | `/ride/ingest` | `ingestRide` |
| POST | `/twin/state/update-from-ride` | `twinStateUpdateFromRide` |
| POST | `/ride/full-bundle` | `rideFullBundle` — **candidato futuro**, non obbligatorio MVP |

**Supabase — leggere / salvare:**

| Tabella | Operazione | Contenuto |
|---------|------------|-----------|
| `activities` | INSERT/UPDATE | `fit_file_url`, `ride_date`, `summary` JSON |
| `activity_jobs` | INSERT/UPDATE | `pending` → `processing` → `done` \| `failed` |
| `twin_states` | UPDATE | twin aggiornato post-ride |
| `power_curve` | UPDATE (in twin) | rolling MMP da ingest |

**Regole UI:**

- Mostrare report qualità sensori prima di confermare ingest
- Progress job su `activity_jobs.status`
- Se `profile_should_refresh`: prompt coach per refresh profilo

**Warning da mostrare:**

- `data-quality`: gap HR/potenza, campionamento basso
- `ingest`: dedup / file già processato
- `missing_inputs`, `quality_flags` da summary

**Cosa NON deve fare il frontend:**

- Non fare parsing FIT in JavaScript
- Non chiamare 15 endpoint analytics in parallelo al posto di summary orchestrato
- Non persistere TwinState senza `twinStateUpdateFromRide`

**Nota MVP vs futuro:** in MVP usare la sequenza `parse` → `data-quality` → `ingest` → `summary` → `twinStateUpdateFromRide`. `POST /ride/full-bundle` (`rideFullBundle`) è il candidato per consolidare orchestrazione in una sola chiamata — adottarlo quando il team frontend è pronto, non è gate MVP.

---

### F3 — Analisi attività

**Scopo:** presentare analisi coach-facing di un'uscita già ingerita (metriche, zone, cardiaca, HRV, durability).

**Pagine / componenti:**

- Activity Analysis (timeline, KPI, zone chart)
- Sezioni embed in Athlete Digital Twin (ultima uscita)

**Endpoint backend (MVP — chiamare solo se dati non già in `activities.summary`):**

| Metodo | Path | Client `api.*` |
|--------|------|----------------|
| POST | `/ride/summary` | `rideSummary` |
| POST | `/ride/intelligence` | `rideIntelligence` |
| POST | `/ride/durability` | `rideDurability` |
| POST | `/ride/analytics/zones` | `rideAnalyticsZones` |
| POST | `/ride/analytics/w-prime/balance` | `rideAnalyticsWPrimeBalance` |
| POST | `/ride/analytics/hrv` | `rideAnalyticsHrv` |
| POST | `/ride/analytics/cardiac` | `rideAnalyticsCardiac` |

**Supabase — leggere / salvare:**

| Tabella | Operazione | Contenuto |
|---------|------------|-----------|
| `activities` | READ (primario) | `summary`, `durability`, stream metadata |
| `activities` | UPDATE | salva output summary/durability dopo prima analisi |

**Regole UI:**

- **Prima** leggere da Supabase; chiamare backend solo su cache miss o refresh esplicito
- Mostrare `data_provenance` per ogni metrica (misurato / modello / euristico)
- HRV: visibile solo se protocollo compatibile (es. ramp test) — rispettare `status: skipped`
- Zone: preferire `metabolic_power` + `coggan_power` da summary, non ricalcolare

**Warning da mostrare:**

- `limitations[]`, `model_metadata`, tier basso
- Sezione skipped → “dati insufficienti”, non valore inventato

**Cosa NON deve fare il frontend:**

- Non trasformare `null` in `0`
- Non mostrare analytics come misure dirette senza badge modello
- Non duplicare motori zones/HRV/cardiac in TS

---

### F4 — Digital Twin atleta

**Scopo:** vista centrale dello stato fisiologico dell'atleta — curve, snapshot, anchor, proiezioni.

**Pagine / componenti:**

- Athlete Digital Twin (6 KPI + curve metaboliche + power duration)
- Team Command Center → drill-down atleta

**Endpoint backend:**

| Metodo | Path | Client `api.*` |
|--------|------|----------------|
| POST | `/twin/state/build` | `twinStateBuild` (solo rebuild) |
| POST | `/twin/state/update-from-ride` | `twinStateUpdateFromRide` |
| POST | `/twin/state/update-from-workout-result` | `twinStateUpdateFromWorkout` |
| POST | `/twin/state/validate` | `twinStateValidate` |
| POST | `/profile/snapshot` | `profileSnapshot` (refresh) |
| POST | `/profile/metabolic/curves` | `profileMetabolicCurves` |

**Supabase — leggere / salvare:**

| Tabella | Operazione | Contenuto |
|---------|------------|-----------|
| `twin_states` | READ (primario) | intero blob `twin_state.v1` |
| `athletes` | READ | peso, genere, phenotype |
| `teams` | READ | `calibration_model` per apply |
| `twin_states` | UPDATE | dopo ogni update backend |

**Regole UI:**

- Caricamento pagina: **solo Supabase**; zero chiamate backend se twin fresco
- Curve: `metabolic_curves.curves.vo2_demand`, `substrate_oxidation`, `lactate_state`
- Traffic light da `cross_validation` e `expressiveness`
- Season what-if: `projectionSeason` su azione esplicita coach

**Warning da mostrare:**

- Anchor stale, sensor quality bassa
- `confidence_score` per ogni KPI model-based
- Disaccordo tra `estimated_vlamax` e `power_derived_vlamax` (non conflarli)

**Cosa NON deve fare il frontend:**

- Non interpolare curve metaboliche localmente
- Non mostrare VO₂max/MLSS come “verità lab” senza test lattato
- Non nascondere `cross_validation.severity` critico

---

### F5 — Prescrizione workout

**Scopo:** validare, rendere fattibile e prescrivere un workout per un atleta.

**Pagine / componenti:**

- Coach Planner → editor workout
- Libreria template
- Assegnazione calendario

**Endpoint backend:**

| Metodo | Path | Client `api.*` |
|--------|------|----------------|
| POST | `/workouts/validate` | `validateWorkout` |
| POST | `/workouts/prescribe` | `prescribeWorkout` |
| POST | `/workouts/feasibility` | `workoutFeasibility` |
| POST | `/twin/state/update-from-workout-result` | `twinStateUpdateFromWorkout` (post-esecuzione) |

**Supabase — leggere / salvare:**

| Tabella | Operazione | Contenuto |
|---------|------------|-----------|
| `workout_assignments` | INSERT | workout, prescription, `scheduled_date`, status |
| `twin_states` | READ | snapshot per feasibility |
| `twin_states` | UPDATE | dopo confronto eseguito (con F6) |

**Regole UI:**

- Sequenza: validate → feasibility → prescribe → salva assignment
- Mostrare watt target con tier e limitazioni fattibilità
- Export opzionale: `exportWorkout` (erg/mrc/zwo)

**Warning da mostrare:**

- Feasibility `blocked` o `caution`
- Zone mismatch con snapshot atleta
- `missing_inputs` per prescribe

**Cosa NON deve fare il frontend:**

- Non calcolare watt da formule locali
- Non saltare `validateWorkout` prima di prescribe
- Non assegnare workout senza persistenza su `workout_assignments`

---

### F6 — Confronto workout eseguito

**Scopo:** confrontare workout prescritto vs attività FIT completata; aggiornare compliance e TwinState.

**Pagine / componenti:**

- Coach Planner → compliance badge
- Activity Analysis → link assignment
- Notifica coach post-uscita

**Endpoint backend:**

| Metodo | Path | Client `api.*` |
|--------|------|----------------|
| POST | `/workouts/compare` | `compareWorkout` |
| POST | `/twin/state/update-from-workout-result` | `twinStateUpdateFromWorkout` |
| POST | `/workouts/calendar/transition` | `calendarTransition` (opz.) |

**Supabase — leggere / salvare:**

| Tabella | Operazione | Contenuto |
|---------|------------|-----------|
| `workout_assignments` | READ/UPDATE | `compliance`, `status` |
| `activities` | READ | file/power per confronto |
| `twin_states` | UPDATE | post-workout twin delta |

**Regole UI:**

- Compliance visuale: verde/giallo/rosso con spiegazione narrativa backend
- Collegare assignment_id ↔ activity_id in DB

**Warning da mostrare:**

- Power trace incompleto per confronto interval
- Deviazione elevata senza nascondere il warning

**Cosa NON deve fare il frontend:**

- Non calcolare compliance localmente
- Non aggiornare twin senza passare da `twinStateUpdateFromWorkout`

---

### F7 — Coach daily decision

**Scopo:** brief mattutino, decisione sessione, sicurezza allenamento, piano test.

**Pagine / componenti:**

- Team Command Center → home coach
- Coach Planner → pre-sessione
- Notifiche push / email (futuro)

**Endpoint backend:**

| Metodo | Path | Client `api.*` |
|--------|------|----------------|
| POST | `/coach/daily-brief` | `coachDailyBrief` |
| POST | `/coach/session-decision` | `coachSessionDecision` |
| POST | `/coach/training-safety` | `coachTrainingSafety` |
| POST | `/coach/testing-plan` | `coachTestingPlan` |
| POST | `/readiness/today` | `readinessToday` (supporto) |

**Supabase — leggere / salvare:**

| Tabella | Operazione | Contenuto |
|---------|------------|-----------|
| `twin_states` | READ | roster twin per contesto |
| `activities` | READ | load recente |
| `workout_assignments` | READ | sessioni pianificate |
| — | Non persistere tutto | brief è effimero; salvare solo decisioni coach esplicite |

**Regole UI:**

- Mostrare narrative + tier; non colonne rigide per ogni campo modello
- Gate sicurezza (`coachTrainingSafety`) prima di sessioni ad alta intensità
- Lista atleti attention: derivare da twin + brief, non inventare priorità

**Warning da mostrare:**

- `coachDecisionSafety` blockers
- Readiness bassa, ACWR elevato (da twin/load in DB)

**Cosa NON deve fare il frontend:**

- Non inventare spiegazioni fisiologiche oltre narrative backend
- Non nascondere safety blockers per “semplificare” la UI
- Non chiamare 10 endpoint coach secondari non documentati in parallelo

---

## 6. Endpoint principali (riferimento rapido)

### Onboarding

```text
POST /test/propose          → api.proposeTest
POST /test/confirm          → api.confirmTest
POST /profile/snapshot      → api.profileSnapshot
POST /twin/state/build      → api.twinStateBuild
POST /twin/state/validate   → api.twinStateValidate
```

### Upload FIT / activity ingest

```text
POST /ride/parse                    → api.rideParse
POST /ride/data-quality             → api.rideDataQuality
POST /ride/summary                  → api.rideSummary
POST /ride/ingest                   → api.ingestRide
POST /twin/state/update-from-ride   → api.twinStateUpdateFromRide
POST /ride/full-bundle              → api.rideFullBundle  (futuro, non MVP)
```

### Activity analysis

```text
POST /ride/summary                      → api.rideSummary
POST /ride/intelligence                 → api.rideIntelligence
POST /ride/durability                   → api.rideDurability
POST /ride/analytics/zones              → api.rideAnalyticsZones
POST /ride/analytics/w-prime/balance    → api.rideAnalyticsWPrimeBalance
POST /ride/analytics/hrv                → api.rideAnalyticsHrv
POST /ride/analytics/cardiac            → api.rideAnalyticsCardiac
```

### Digital Twin

```text
POST /twin/state/build                      → api.twinStateBuild
POST /twin/state/update-from-ride             → api.twinStateUpdateFromRide
POST /twin/state/update-from-workout-result   → api.twinStateUpdateFromWorkout
POST /twin/state/validate                     → api.twinStateValidate
POST /profile/snapshot                        → api.profileSnapshot
POST /profile/metabolic/curves                → api.profileMetabolicCurves
```

### Workout

```text
POST /workouts/validate                         → api.validateWorkout
POST /workouts/prescribe                        → api.prescribeWorkout
POST /workouts/feasibility                      → api.workoutFeasibility
POST /workouts/compare                          → api.compareWorkout
POST /twin/state/update-from-workout-result     → api.twinStateUpdateFromWorkout
```

### Coach

```text
POST /coach/daily-brief       → api.coachDailyBrief
POST /coach/session-decision    → api.coachSessionDecision
POST /coach/training-safety     → api.coachTrainingSafety
POST /coach/testing-plan        → api.coachTestingPlan
```

---

## 7. Pagine frontend ufficiali

| Pagina | Flussi facade | Lettura primaria Supabase | Backend live |
|--------|---------------|---------------------------|--------------|
| **Team Command Center** | F7, drill-down F4 | `teams`, `athletes`, `twin_states`, `validation_events` | `coachDailyBrief`, `coachTestingPlan` |
| **Athlete Digital Twin** | F4 | `twin_states`, `athletes` | refresh: `profileSnapshot`, `profileMetabolicCurves` |
| **Activity Analysis** | F2, F3, F6 | `activities`, `activity_jobs` | upload/analisi se non in cache |
| **Testing Lab** | F1 | `athletes`, `test_sessions` | `proposeTest`, `confirmTest`, calibrazione |
| **Coach Planner** | F5, F6, F7 | `workout_assignments`, `twin_states` | validate/prescribe/compare |
| **Model Accuracy** | — (aggregazione DB) | `validation_events`, `teams.calibration_model` | `updateTeamCalibration`, `applyTeamCalibration` |

### Team Command Center

- KPI roster green/yellow/red da `twin_state` + readiness
- Header calibrazione team da `teams.calibration_model`
- Entry point brief giornaliero (F7)

### Athlete Digital Twin

- 6 KPI fisiologici + curve metaboliche + power duration
- Expressiveness checklist e cross-validation matrix
- Nessuna chiamata backend all'apertura se twin in DB è aggiornato

### Activity Analysis

- Upload FIT (F2) o visualizzazione uscita salvata (F3)
- Timeline multi-serie, zone, cardiaca, HRV (se disponibile)
- Link a workout assignment (F6)

### Testing Lab

- Wizard propose → confirm → snapshot → twin/build
- Tablet lattato (flusso esteso: `labLactateValidateModel` — fuori MVP minimo)

### Coach Planner

- Editor workout, feasibility, calendario
- Compliance post-uscita

### Model Accuracy

- MAE/bias per parametro da aggregazione `validation_events`
- Scatter predicted vs measured
- Storico apprendimento team

---

## 8. Regole UI obbligatorie

### Campi da mostrare quando disponibili

Ogni card metrica o sezione analisi deve esporre, se presenti nel payload backend:

| Campo | Uso UI |
|-------|--------|
| `status` | Gate visibilità (`success` / `partial` / `skipped` / `error`) |
| `confidence_score` | Barra o badge numerico |
| `warnings` | Lista espandibile, mai nascosta se `severity: critical` |
| `missing_inputs` | Spiegazione “perché non disponibile” |
| `quality_flags` | Badge qualità sensore / protocollo |
| `tier` | `measured` \| `model` \| `heuristic` \| `unavailable` |
| `limitations` | Testo limite modello |
| `model_metadata` | Versione motore, parametri rilevanti per coach avanzato |
| `data_provenance` | `Misurato FIT` \| `Calcolo standard` \| `Modello fisiologico` \| `Euristico` |

### Il frontend NON deve

| Vietato | Motivo |
|---------|--------|
| Trasformare `null` in `0` | Inganna il coach su dati mancanti |
| Nascondere warning critici | Rischio decisionale |
| Mostrare modelli come misure dirette | Violazione contratto tier |
| Inventare spiegazioni fisiologiche | Solo narrative backend (`explainability*`) |
| Calcolare VO₂max, VLamax, MLSS, FatMax, CTL/ATL/TSB | Duplicazione motori Python |
| Fare parsing FIT | `rideParse` / worker backend |
| Duplicare motori Python lato frontend | Manutenzione impossibile, incoerenza |

---

## 9. Wrapper frontend consigliato

Struttura target sotto `frontend/src/services/`:

```text
frontend/src/services/
  athleteFacade.ts      # F1 onboarding
  activityFacade.ts     # F2 upload, F3 analisi
  twinFacade.ts         # F4 digital twin
  workoutFacade.ts      # F5 prescribe, F6 compare
  coachFacade.ts        # F7 daily decision
  testingFacade.ts      # Testing Lab, lactate validate (estensione F1)
```

### Responsabilità di ogni facade

1. **Chiamare Supabase** per read/write sulle tabelle del contratto (§11).
2. **Chiamare `api.*`** solo quando serve calcolo live o ingest.
3. **Normalizzare errori** in un tipo `FacadeResult<T>` con `data | error | warnings`.
4. **Evitare logica fisiologica** — mapping campi JSON → props UI, non formule.

### Esempio superficie (indicativa)

```typescript
// activityFacade.ts
export async function uploadActivity(input: UploadActivityInput): Promise<FacadeResult<ActivityRecord>>;
export async function analyzeActivity(activityId: string): Promise<FacadeResult<ActivityAnalysisView>>;
```

### Hooks TanStack Query

```text
useTwin(athleteId)           → twinFacade.loadTwin
useActivityAnalysis(id)      → activityFacade.analyzeActivity
useCoachDailyBrief(teamId)   → coachFacade.dailyDecision
```

I componenti consumano **hooks**, non `api` direttamente.

---

## 10. Error handling

### Codici HTTP da gestire

| Codice | Significato | Azione UI |
|--------|-------------|-----------|
| **400** | Input invalido | Form validation, messaggio campo-specifico |
| **413** | Upload troppo grande | “File troppo grande”, suggerire compressione / supporto |
| **422** | FIT non leggibile o attività senza potenza | Spiegare requisito potenza; non retry cieco |
| **429** | Rate limit | Backoff + messaggio “riprova tra N secondi” |
| **500** | Errore backend | Stato errore generico + `activity_jobs.failed` se job |

### Tre tipi di “errore” da distinguere in UI

| Tipo | Esempio | Presentazione |
|------|---------|---------------|
| **Errore tecnico** | 500, timeout, rete | Banner rosso, retry, log supporto |
| **Dato fisiologico mancante** | HRV skipped, lactate assente | Stato empty informativo, non errore rosso |
| **Dato low confidence** | `tier: heuristic`, score < soglia | Badge giallo, valore visibile con caveat |

### Normalizzazione in facade

```typescript
type FacadeError =
  | { kind: 'technical'; status: number; message: string }
  | { kind: 'missing_data'; field: string; reason: string }
  | { kind: 'low_confidence'; tier: string; score?: number };
```

Non mappare `422` fisiologico (es. “no power data”) come crash generico.

---

## 11. Contratto con Supabase

### Tabelle — lettura principale UI

| Tabella | Contenuto | Flussi |
|---------|-----------|--------|
| `teams` | team, `calibration_model` | Command Center, Model Accuracy |
| `athletes` | anagrafica, link team | Tutte le pagine |
| `activities` | FIT URL, `summary`, durability | Activity Analysis |
| `activity_jobs` | stato pipeline ingest | Upload FIT |
| `twin_states` | `twin_state` JSON completo | Digital Twin, Coach |
| `validation_events` | predicted/measured, protocol | Testing Lab, Model Accuracy |
| `workout_assignments` | workout, prescription, compliance | Coach Planner |
| `team_calibration_models` | storico calibrazione (se normalizzato) | Model Accuracy |

### Backend live — solo per

- nuovi calcoli (upload, test, prescribe);
- what-if (`projectionSeason`);
- decision support (`coachDailyBrief`, `coachSessionDecision`);
- validazione test (`labLactateValidateModel`);
- aggiornamento TwinState (`twinStateUpdateFromRide`, `twinStateUpdateFromWorkout`).

### Pattern transazione consigliato

```text
1. Facade chiama backend → riceve JSON
2. Facade scrive Supabase in transazione (activity + twin + job)
3. TanStack Query invalida cache
4. UI rilegge da Supabase
```

---

## 12. MVP frontend minimo

Il MVP prodotto include **solo** queste schermate:

| # | Schermata | Flusso | Priorità |
|---|-----------|--------|----------|
| 1 | Login / team selector | — | P0 |
| 2 | Athlete list | read `athletes` | P0 |
| 3 | Athlete Digital Twin | F4 | P0 |
| 4 | Upload FIT | F2 | P0 |
| 5 | Activity Analysis | F3 | P0 |
| 6 | Coach Daily Brief | F7 (solo `coachDailyBrief` + readiness) | P1 |
| 7 | Workout Prescription basic | F5 (validate + prescribe, no export avanzato) | P1 |

### Fuori MVP (fase 2)

- Model Accuracy completa
- Testing Lab lactate tablet
- `rideFullBundle` come flusso unificato
- Season projection / what-if
- Endpoint LABS e coach secondari

---

## 13. Definition of Done frontend

Una pagina frontend è **pronta per merge** quando:

- [ ] Usa il client API ufficiale (`frontend/src/api/client.ts`) **solo** tramite facade/hooks
- [ ] Non chiama endpoint LABS/INTERNAL senza approvazione prodotto esplicita
- [ ] Gestisce `null` e `status: skipped` senza convertirli in zero
- [ ] Mostra `warnings` e `missing_inputs` quando presenti
- [ ] Mostra `confidence_score` e `tier` per metriche model-based
- [ ] Distingue visivamente **model** vs **measured** (`data_provenance`)
- [ ] Salva o legge da Supabase correttamente (tabelle §11)
- [ ] Non contiene logica fisiologica duplicata (no CTL/VO₂max locali)
- [ ] Ha stati **loading**, **error**, **empty** distinti
- [ ] È comprensibile da un coach **senza leggere il codice**

---

## Appendice — Relazione con altri documenti

| Documento | Ruolo |
|-----------|--------|
| `docs/STABLE_BACKEND_SURFACE.md` | Tier STABLE / ADVANCED / LABS per ogni path |
| `docs/FRONTEND_DEVELOPER_GUIDE.md` | TwinState, zone, navigazione pagine |
| `docs/INGEST_PIPELINE_ARCHITECTURE.md` | S3 → worker → Supabase |
| `docs/OPENAPI_FRONTEND.md` | Codegen, env, inventario `api.*` |
| `docs/API_ENDPOINT_INDEX.md` | Elenco 135 path |
| `frontend/src/api/client.ts` | Trasporto HTTP — **non** è la facade |

---

## Changelog

| Date | Version | Change |
|------|---------|--------|
| 2026-07-05 | 1.0.0 | Initial frontend API facade for V5.2.6 |

---

*Documento di governance frontend — nessuna modifica a runtime backend, OpenAPI, workflow, frontend, test, Makefile o README in questa revisione.*
