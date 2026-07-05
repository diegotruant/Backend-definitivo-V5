# Frontend API Facade — Digital Twin Backend V5.2.6

**Repository:** `diegotruant/Backend-definitivo-V5`  
**Companion:** `docs/STABLE_BACKEND_SURFACE.md` (tier map per endpoint)  
**Typed client:** `frontend/src/api/client.ts` (135 metodi — trasporto HTTP)  
**Versione:** 5.2.6  

---

## 1. Scopo del documento

Questo documento definisce la **facciata frontend ufficiale** del backend.

Il backend espone molti endpoint, ma il frontend **non** deve chiamarli tutti direttamente.  
Il frontend deve usare pochi flussi chiari, stabili e orientati al prodotto.

Obiettivo:

```text
135 endpoint backend  →  pochi flussi frontend comprensibili
```

| Layer | Ruolo | Chi lo usa |
|-------|--------|------------|
| **UI / pagine** | Schermate coach e atleta | React / Next / mobile |
| **Facade** (questo doc) | Orchestrazione prodotto, nomi di dominio | `hooks/`, `services/` |
| **`api` client** | Trasporto HTTP tipizzato 1:1 con OpenAPI | Solo dentro la facade |
| **Backend** | Motori fisiologici stateless | Mai importato in UI |

**Regola:** i componenti React chiamano la **facade**, non `api.rideAnalytics*` sparsi nei file `.tsx`.

---

## 2. Tre livelli di accesso API

```text
┌─────────────────────────────────────────────────────────┐
│  Pages: AthleteHome, RideDetail, CoachBrief, …          │
└──────────────────────────┬──────────────────────────────┘
                           │ facade.* (contratto prodotto)
┌──────────────────────────▼──────────────────────────────┐
│  frontend/src/services/digitalTwinFacade.ts  (target)   │
│  oppure hooks che incapsulano le sequenze sotto         │
└──────────────────────────┬──────────────────────────────┘
                           │ api.* (solo qui)
┌──────────────────────────▼──────────────────────────────┐
│  frontend/src/api/client.ts — 135 jsonFetch             │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP
┌──────────────────────────▼──────────────────────────────┐
│  Backend FastAPI V5.2.6                                   │
└─────────────────────────────────────────────────────────┘
```

### Cosa è consentito dove

| Da | A | Consentito |
|----|---|------------|
| Pagina `.tsx` | `facade.onboardAthlete()` | ✅ |
| Pagina `.tsx` | `api.rideFullBundle()` | ⚠️ solo in migrazione legacy |
| Pagina `.tsx` | `api.rideAnalyticsHrv()` | ❌ |
| Facade | `api.*` STABLE / STABLE-CANDIDATE | ✅ |
| Facade | `api.*` ADVANCED | ⚠️ solo schermate secondarie documentate |
| Facade | `api.*` LABS / INTERNAL | ❌ |

Tier completi: `docs/STABLE_BACKEND_SURFACE.md`.

---

## 3. I sette flussi facade (MVP + estensioni)

Il frontend MVP si organizza in **7 flussi facade**. Ogni flusso è una sequenza ordinata di chiamate `api.*` + persistenza Supabase.

### F1 — `onboardAthlete`

**Schermata:** setup atleta / primo test  
**Tier:** STABLE  

```text
api.profileSnapshot(...)
api.proposeTest(files)          // opzionale
api.confirmTest(...)
api.twinStateBuild(...)
api.twinStateValidate(...)
→ salva metabolic_snapshot + twin_state in Supabase
```

### F2 — `uploadAndAnalyzeRide` (canonico)

**Schermata:** dettaglio attività, report post-uscita  
**Tier:** STABLE — **flusso preferito**

```text
api.ingestRide({ file, ride_date, weight_kg, stored_curve_json })
api.rideFullBundle({ file, weight_kg, ftp, metabolic_snapshot, ... })
api.twinStateUpdateFromRide({ twin_state, bundle, ... })
api.updateProfile(...)          // solo se bundle.profile_should_refresh
→ salva activities.bundle + twin_state + power_curve
```

**Non usare** in parallelo: `rideSummary` + `rideAnalyticsDurabilityIndex` + `rideAnalyticsHrv` + …  
Quel campo è già nel bundle (`engine_manifest`, `durability_index`, `workout_summary.sections.hrv`, …).

### F3 — `prescribeWorkout`

**Schermata:** libreria workout, assegnazione  
**Tier:** STABLE  

```text
api.validateWorkout(workout)
api.workoutFeasibility({ workout, athlete_profile })
api.prescribeWorkout({ workout, athlete_profile })
api.exportWorkout({ workout, format })   // opzionale: erg | mrc | zwo
→ salva workout_assignments in Supabase
```

### F4 — `compareCompletedWorkout`

**Schermata:** compliance post-uscita  
**Tier:** STABLE  

```text
api.compareWorkout({ workout, activity_file | power_json })
api.calendarTransition({ assignment_id, new_status })
→ aggiorna compliance su workout_assignments
```

### F5 — `validateLactateAndCalibrate`

**Schermata:** tablet test lattato / lab  
**Tier:** STABLE  

```text
api.labLactateValidateModel({ steps, snapshot, ... })
→ estrai response.validation_event
→ aggiungi athlete_id, team_id
api.updateTeamCalibration({ events: [validation_event] })
api.applyTeamCalibration({ snapshot, calibration_model })
→ salva validation_events + teams.calibration_model
```

### F6 — `coachMorningBrief` (STABLE-CANDIDATE)

**Schermata:** home coach  
**Tier:** STABLE-CANDIDATE  

```text
api.readinessToday({ twin_state, recent_load, ... })
api.coachDailyBrief({ twin_state, roster_context, ... })
api.coachSessionDecision({ planned_session, readiness, ... })   // pre-sessione
api.coachDecisionSafety({ ... })                                 // gate sicurezza
api.coachNutritionPerformanceTargets({ ... })                    // fueling
→ UI mostra tier + narrative; non persistere tutto in colonne rigide
```

### F7 — `renderActivityCharts` (STABLE)

**Schermata:** grafici attività / twin  
**Tier:** STABLE  

```text
api.metaChartTypes()
api.metaChartConfig({ chart_type, stream_payload | twin_state, ... })
```

Per attività già analizzate: preferire `bundle.activity_charts` da F2 invece di richiamare `metaChartConfig` per ogni chart se i dati sono già nel bundle.

---

## 4. Mappa pagina → facade → `api.*`

| Pagina prodotto | Facade | Metodi `api.*` ammessi |
|-----------------|--------|-------------------------|
| Athlete onboarding | `onboardAthlete` | `profileSnapshot`, `proposeTest`, `confirmTest`, `twinStateBuild`, `twinStateValidate` |
| Upload FIT | `uploadAndAnalyzeRide` | `ingestRide`, `rideFullBundle`, `twinStateUpdateFromRide`, `updateProfile` |
| Ride detail | `uploadAndAnalyzeRide` (già fatto) + `renderActivityCharts` | Leggi da Supabase; `metaChartConfig` solo se manca chart nel bundle |
| Workout editor | `prescribeWorkout` | `validateWorkout`, `workoutFeasibility`, `prescribeWorkout`, `exportWorkout` |
| Workout compliance | `compareCompletedWorkout` | `compareWorkout`, `calendarTransition` |
| Lactate tablet | `validateLactateAndCalibrate` | `labLactateValidateModel`, `updateTeamCalibration`, `applyTeamCalibration` |
| Coach home | `coachMorningBrief` | `readinessToday`, `coachDailyBrief`, `coachSessionDecision`, … |
| Digital Twin | — | Leggi `twin_state` da Supabase; `profileMetabolicCurves` solo se serve refresh curve |
| Dashboard | — | `dashboardAthleteSnapshot` (STABLE-CANDIDATE) dietro feature flag |

---

## 5. Metodi `api.*` — allowlist MVP

### ✅ Allowlist (42 metodi — STABLE + STABLE-CANDIDATE)

Usabili dalla facade nelle schermate MVP:

```text
health
profileSnapshot
proposeTest, confirmTest
ingestRide, rideFullBundle, rideSummary, updateProfile
rideParse, rideDataQuality, rideIntelligence          // debug / fallback only
validateWorkout, prescribeWorkout, workoutFeasibility,
  compareWorkout, exportWorkout, calendarTransition
twinStateBuild, twinStateUpdateFromRide, twinStateValidate
twinStateProject, projectionSeason
labLactateValidateModel
updateTeamCalibration, applyTeamCalibration
metaChartTypes, metaChartConfig, metaEngineTiers
readinessToday
manualLoad, loadAcwr
coachDailyBrief, coachSessionDecision, coachDecisionSafety,
  coachNutritionPerformanceTargets
profileMetabolicCurves, profileTrainingLoadCtlAtlTsb
workoutProgressionLevels, recommendWorkout
dashboardAthleteSnapshot
explainabilityWorkoutSummaryNarrative, explainabilityMetricNarrative
```

### ⛔ Blocklist per componenti UI (chiamare solo da schermate ADVANCED dedicate)

```text
rideAnalytics*          (25 metodi) — usare bundle
rideDurability          — legacy; bundle include durability_*
coachAdherence, coachAttention, …  (coach secondari)
profileSnapshotBayesian, profileSnapshotPhenotype, …  (LABS)
labCreateResult, labParseText, …    (LABS tranne validate-model)
integrations*, powerSourceNormalize, rideAnalyticsSessionRoute*
inPersonTest                        (LABS)
```

---

## 6. Contratto dati in uscita (cosa la UI deve leggere)

### Ride bundle (`api.rideFullBundle`)

| Campo | Uso UI |
|-------|--------|
| `status` | Gate pagina (`success` / `partial` / `error`) |
| `engine_manifest[]` | Quali widget mostrare / nascondere |
| `manifest_summary.release_blockers` | Badge coach se > 0 |
| `workout_summary.sections.*` | Metriche principali |
| `activity_charts` | Grafici precomputati |
| `physiology_outputs.exposed_keys` | Sezioni fisiologia disponibili |
| `durability_index`, `np_drift`, … | Side outputs (rispettare `status`) |

**Manifest rule:** se `engine_manifest[].status === "skipped"`, mostrare “dati insufficienti” — non chiamare l’endpoint analytics corrispondente.

### TwinState

Persistere il blob intero. Per query veloci, denormalizzare in Supabase solo:

- `metabolic_snapshot` (headline metrics)
- `power_curve`
- `anchor` atleta

Vedi `docs/METABOLIC_CURVES_TWIN_CONTRACT.md`.

### Tier UX

Ogni numero model-based deve mostrare `tier` / `confidence_tier`.  
Non renderizzare `null` o `status: skipped` come valore certo.

---

## 7. Implementazione consigliata (target file)

Questo documento **non** aggiunge ancora codice. Il target è:

```text
frontend/src/services/digitalTwinFacade.ts
```

Esempio di superficie (nomi stabili per il team):

```typescript
export const facade = {
  onboardAthlete,
  uploadAndAnalyzeRide,
  prescribeWorkout,
  compareCompletedWorkout,
  validateLactateAndCalibrate,
  coachMorningBrief,
  getChartConfig,
};
```

Ogni funzione:

1. accetta DTO di dominio (atleta, file, twin da Supabase);
2. chiama solo metodi `api.*` della allowlist;
3. restituisce un oggetto UI-ready + `warnings` + `tiers`;
4. non espone `EnginePayload` grezzo ai componenti se evitabile.

---

## 8. Anti-pattern (vietati)

| Anti-pattern | Perché è un problema | Alternativa |
|--------------|---------------------|-------------|
| `api.rideAnalyticsHrv()` nella pagina Ride | Duplica orchestrazione già nel bundle | Leggi `bundle.workout_summary.sections.hrv` |
| 15 chiamate analytics al upload | Latenza, incoerenza manifest | `api.rideFullBundle()` |
| Salvare output LABS in colonna NOT NULL | Schema fragile | JSON opzionale + flag feature |
| `api.rideAnalyticsSessionRouteRun()` in UI | Endpoint INTERNAL | Solo debug / script |
| Componente che importa `api` direttamente | Nessun confine prodotto | Passare da facade/hook |
| Ignorare `engine_manifest` | Widget vuoti o dati inventati | Manifest-driven UI |

---

## 9. Relazione con altri documenti

| Documento | Ruolo |
|-----------|--------|
| `docs/STABLE_BACKEND_SURFACE.md` | Classificazione tier di ogni path HTTP |
| `docs/DEVELOPER_ONBOARDING.md` | Onboarding giorno 1, comandi make |
| `docs/FRONTEND_DEVELOPER_GUIDE.md` | TwinState, pagine, zone doppie |
| `docs/OPENAPI_FRONTEND.md` | Codegen, env, `api.*` completo |
| `docs/API_ENDPOINT_INDEX.md` | Inventario 135 path |
| `frontend/src/api/client.ts` | Client generato/manutenuto — **non** è la facade |

---

## 10. Checklist PR frontend

Prima di mergiare una PR UI che tocca il backend:

- [ ] Nessun nuovo `import { api }` nei componenti leaf (solo in facade/hooks)
- [ ] Flusso ride usa `rideFullBundle`, non catena analytics
- [ ] `engine_manifest` rispettato per visibilità widget
- [ ] Tier mostrato per metriche model-based
- [ ] Nessuna colonna Supabase obbligatoria da endpoint LABS/INTERNAL
- [ ] Se si aggiunge un metodo facade, aggiornare questa tabella §4

---

## 11. Changelog

| Date | Version | Change |
|------|---------|--------|
| 2026-07-05 | 1.0.0 | Initial frontend facade map for V5.2.6 |

---

*Documento di governance frontend — nessuna modifica a runtime backend, OpenAPI o `client.ts` in questa revisione.*
