# Guida per lo sviluppatore frontend — Digital Twin Backend V5.1

Documento unificato per uno **sviluppatore software** che deve costruire il frontend collegato a questo backend, **senza background nel ciclismo endurance**. Spiega cosa produce il backend (v **5.1.0**), come interpretare le metriche, come disegnarle, come progettare le pagine principali e come usare **TwinState** come modello di persistenza centrale.

**Documenti correlati (leggere in questo ordine)**

| Priorità | Documento | Contenuto |
|----------|-----------|-----------|
| 1 | Questo file | Panoramica, API, TwinState, mappa pagine |
| 2 | `docs/FRONTEND_IMPLEMENTATION_BLUEPRINT.md` | Layout dettagliato per pagina, design system, DoD |
| 3 | `docs/API_PAYLOAD_EXAMPLES.md` | Esempi curl / TypeScript per ogni endpoint |
| 4 | `docs/WORKOUT_SYSTEM_BACKEND_V1.md` | Flusso prescrizione → compliance |
| 5 | `docs/BACKEND_IMPLEMENTATIONS_V2.md` | TwinState, projection, neuromuscular |
| 6 | `docs/COACH_UX_COPYBOOK.md` | Copy coach-facing |
| 7 | `docs/HARDENING_TESTS.md` | Suite robustezza / stress |
| 8 | `CONTRATTO_JSON_test.md` | Contratto tablet test in presenza |

**Riferimenti codice**

| Risorsa | Path |
|---------|------|
| API HTTP | `api_app.py` |
| Facade Python | `engines/__init__.py` |
| TwinState canonico | `engines/twin_state/` |
| Report per attività | `engines/io/workout_summary.py` |
| Config grafici | `engines/io/chart_builder.py`, `engines/io/activity_charts.py` |
| Tier / confidenza | `engines/core/tiers.py`, `engines/core/metric_contracts.py` |
| Sicurezza input | `engines/core/security.py` |
| Frontend MVP esistente | `frontend/` (oggi legge CSV; va migrato alle API) |

---

## 1. Idea di prodotto in una frase

Il backend trasforma **file FIT** (uscite dal ciclocomputer), **test in presenza** (sprint, CP 3/6/12 min, lattato), **allenamenti prescritti** e **dati fisici dell'atleta** in un **profilo fisiologico personalizzato**, in **analisi per ogni allenamento** e in un **gemello digitale** (`TwinState`) che il frontend persiste e aggiorna nel tempo.

Non è un "Garmin clone": molti numeri sono **stime modellate**, non misure dirette. Il backend è **onesto** quando mancano dati o la confidenza è bassa (`status: skipped`, campi `null`, `warnings`, `tier`).

---

## 2. Glossario minimo (per chi non fa ciclismo)

| Termine | Cosa significa | Unità tipica |
|---------|----------------|--------------|
| **Potenza (W)** | Quanto "forte" pedala il ciclista | Watt |
| **FTP** | Potenza sostenibile ~1 h (soglia funzionale) | W |
| **MLSS / CP** | Potenza alla soglia del lattato (max sostenibile a lungo) | W |
| **VO₂max** | Capacità aerobica massima | ml/kg/min |
| **VLamax** | Capacità anaerobica glicolitica | mmol/L/s |
| **MMP** | Miglior potenza media per ogni durata (curva potenza-durata) | `{secondi: W}` |
| **NP** | Normalized Power — intensità "equivalente" su terreno variabile | W |
| **IF** | Intensity Factor = NP / FTP | 0–1+ |
| **TSS** | Training Stress Score — carico dell'uscita | punti |
| **CTL / ATL / TSB** | Carico cronico / acuto / forma (detraining engine) | punti |
| **Durability** | Capacità di mantenere la performance nel tempo (affaticamento) | % o curva CP |
| **W′** | "Batteria" anaerobica sopra CP | Joule |
| **DFA-α₁** | Indice HRV legato a zona aerobica/anaerobica | 0–1 |
| **Fenotipo** | Profilo rider (diesel / all-rounder / sprinter) | etichetta |
| **TwinState** | Blob JSON unico (`twin_state.v1`) con profilo, carico, calendario, compliance | JSON |

**Regola d'oro per la UI:** distingui sempre **misura diretta** (potenza, FC dal FIT) da **modello** (VO₂max da MMP, MLSS da Mader).

---

## 3. Filosofia dati: tier e confidenza

Ogni output importante porta (o può portare):

```json
{
  "status": "success | error | skipped | insufficient_data | unavailable",
  "tier": "REFERENCE | MODEL | HEURISTIC | EXPERIMENTAL",
  "api_contract": { "module": "...", "method": "...", "confidence": 0.72 },
  "uncertainty": { "confidence_score": 0.72, "confidence_level": "moderate" },
  "limitations": ["testo libero..."]
}
```

| Tier | Significato UI | Come mostrarlo |
|------|----------------|----------------|
| **REFERENCE** | Formula standard su dati FIT (NP, TSS, zone) | Numero pieno, badge verde "Misurato / standard" |
| **MODEL** | Modello fisiologico (Mader, W′, mader_durability) | Numero + badge blu "Modello" + tooltip limitazioni |
| **HEURISTIC** | Soglie indicative (ACWR, durability empirica) | Numero + badge ambra "Indicativo" |
| **EXPERIMENTAL** | Esplorativo | Nascosto o sezione "Labs" |

**Se `status !== "success"` o un campo è `null`:** non inventare un valore. Mostra messaggio dal backend (`reason`, `message`, `warnings`).

---

## 4. Architettura frontend ↔ backend (V5.1)

Il backend è **stateless**: il frontend (o Supabase) persiste **TwinState**, anchor, curve, calibration model e li rimanda alle API.

```mermaid
flowchart TB
  subgraph persist [Persistenza client/DB]
    TWIN[(TwinState twin_state.v1)]
    TEAM[(Team calibration_model)]
    ACT[(activities, validation_events)]
  end

  subgraph onboarding [Flow A - Onboarding test]
    FIT_TEST[FIT test sprint+CP o tablet lattato]
    PROPOSE[POST /test/propose]
    REVIEW[UI revisione coach]
    CONFIRM[POST /test/confirm]
    FIT_TEST --> PROPOSE --> REVIEW --> CONFIRM
  end

  subgraph monitoring [Flow B - Monitoraggio]
    FIT_RIDE[FIT uscita]
    INGEST[POST /ride/ingest]
    SUMMARY[POST /ride/summary]
    FIT_RIDE --> INGEST --> SUMMARY
  end

  subgraph twin [Digital Twin centrale]
    BUILD[POST /twin/state/build]
    UPD_RIDE[POST /twin/state/update-from-ride]
    SNAP[POST /profile/snapshot]
    APPLY[POST /team/calibration/apply]
    CONFIRM --> BUILD
    INGEST --> UPD_RIDE
    SUMMARY --> UPD_RIDE
    BUILD --> TWIN
    UPD_RIDE --> TWIN
    TWIN --> SNAP
    TEAM --> APPLY
    SNAP --> APPLY
  end

  subgraph coach [Flow C - Prescrizione]
    VAL[POST /workouts/validate]
    PRE[POST /workouts/prescribe]
    FEAS[POST /workouts/feasibility]
    CMP[POST /workouts/compare]
    VAL --> PRE --> FEAS --> CMP
    CMP --> UPD_WO[POST /twin/state/update-from-workout-result]
    UPD_WO --> TWIN
  end
```

**Principio V5.1:** invece di ricomporre lo stato da molti JSON sparsi, usa `TwinState` come **read model canonico** per la pagina Digital Twin, il Command Center e le proiezioni stagionali.

---

## 5. TwinState v1 — modello di persistenza centrale

Schema: `twin_state.v1` (`engines/twin_state/models.py`).

### 5.1 Sezioni top-level

| Sezione | Contenuto | Aggiornata da |
|---------|-----------|---------------|
| `athlete_profile` | Peso, sesso, discipline, training_years | `/test/confirm`, edit manuale |
| `measured_anchor` | VO₂max, MLSS, VLamax misurati | `/test/confirm`, `/test/in-person` |
| `metabolic_snapshot` | Snapshot completo profiler | `/profile/snapshot`, `/ride/update-profile` |
| `rolling_power_curve` | Curva MMP aggregata | `/ride/ingest` |
| `load_state` | CTL/ATL/TSB, ACWR | ingest + `/load/manual` |
| `readiness_state` | Readiness adattivo | adaptive_load engines |
| `sensor_quality` | Completezza sensori FIT | `/ride/summary` |
| `workout_calendar_state` | Assegnazioni calendario | DB frontend + `/workouts/calendar/transition` |
| `last_compliance_results` | Ultimi confronti workout vs eseguito | `/workouts/compare` |
| `team_calibration_state` | Audit correzioni team | `/team/calibration/apply` |
| `state_confidence` | Score 0–1 globale | calcolato in build/update |
| `warnings` | Lista warning attivi | tutti i flussi |
| `event_log` | Cronologia eventi (append-only) | update endpoints |

### 5.2 Endpoint TwinState

| Metodo | Path | Quando chiamarlo |
|--------|------|------------------|
| POST | `/twin/state/build` | Dopo primo anchor + snapshot: crea blob iniziale |
| POST | `/twin/state/update-from-ride` | Dopo ogni ingest/summary: aggiorna curva, load, sensor quality |
| POST | `/twin/state/update-from-workout-result` | Dopo `/workouts/compare`: append compliance |
| POST | `/twin/state/project` | What-if stagionale da calendario pianificato |
| POST | `/projection/season` | Alias di `/twin/state/project` |

**Flusso consigliato React:**

1. Carica `twin_state` da DB.
2. Se assente: `build` con anchor + snapshot + curve.
3. Dopo ogni FIT: `ingest` → `ride/summary` → `update-from-ride` → salva TwinState.
4. Prima di mostrare KPI calibrati: `team/calibration/apply` sullo snapshot dentro TwinState.
5. Per Coach Planner stagionale: `projection/season` con piano calendario.

---

## 6. API HTTP completa (`api_app.py`)

Base URL esempio: `http://localhost:8000` (`make run` o `uvicorn api_app:app`).

### 6.1 Health e profilo

| Metodo | Path | Scopo |
|--------|------|--------|
| GET | `/health` | Health check |
| POST | `/test/propose` | N file FIT → proposta profilo (non committa) |
| POST | `/test/confirm` | Proposta confermata → anchor misurato |
| POST | `/test/in-person` | Envelope tablet → test_protocols / lattato |
| POST | `/profile/snapshot` | MMP → snapshot metabolico completo |
| POST | `/ride/update-profile` | MMP uscita + anchor → profilo aggiornato |

### 6.2 Attività e analisi

| Metodo | Path | Scopo |
|--------|------|--------|
| POST | `/ride/ingest` | 1 FIT → aggiorna curva potenza |
| POST | `/ride/summary` | FIT o `power_json` → `workout_summary` completo |
| POST | `/ride/durability` | FIT + snapshot → CP residua + potenze sostenibili |
| POST | `/performance/neuromuscular-profile` | Profilo sprint da FIT |
| POST | `/power-source/normalize` | Offset trainer vs power meter |
| POST | `/load/manual` | Carico non-ciclismo (RPE × durata) |

### 6.3 Workout system

| Metodo | Path | Scopo |
|--------|------|--------|
| POST | `/workouts/validate` | Valida template workout |
| POST | `/workouts/prescribe` | Materializza % target in watt |
| POST | `/workouts/feasibility` | Preview fattibilità W′ |
| POST | `/workouts/compare` | Confronto assegnato vs FIT eseguito |
| POST | `/workouts/calendar/transition` | FSM stato assegnazione calendario |

### 6.4 TwinState e proiezione

| Metodo | Path | Scopo |
|--------|------|--------|
| POST | `/twin/state/build` | Crea TwinState v1 |
| POST | `/twin/state/update-from-ride` | Aggiorna dopo uscita |
| POST | `/twin/state/update-from-workout-result` | Append compliance |
| POST | `/twin/state/project` | Proiezione stagionale what-if |
| POST | `/projection/season` | Alias projection |

### 6.5 Team learning

| Metodo | Path | Scopo |
|--------|------|--------|
| POST | `/team/calibration/update` | Aggiunge eventi validati al modello team |
| POST | `/team/calibration/apply` | Applica correzione a snapshot o singolo parametro |

Dettagli payload: `docs/API_PAYLOAD_EXAMPLES.md`.

---

## 7. Mappa endpoint → schermate frontend

Tabella operativa derivata da `FRONTEND_IMPLEMENTATION_BLUEPRINT.md`. Ogni riga indica **quale endpoint alimenta quale pagina/sezione**.

| Pagina | Sezione UI | Endpoint primari | Dati da persistere |
|--------|------------|------------------|-------------------|
| **Team Command Center** | Header team calibration | — (legge DB) | `teams.calibration_model` |
| | KPI atleti verde/giallo/rosso | — (deriva da TwinState) | `athletes.twin_state` |
| | Tabella atleti | `/team/calibration/apply` su snapshot | anchor, snapshot, confidence |
| | MAE MLSS team | `/team/calibration/update` (storico) | `validation_events` |
| | Grafico accuratezza | aggregazione `validation_events` | eventi pre/post test |
| **Athlete Digital Twin** | Header + confidence | TwinState | `twin_state` |
| | KPI fisiologici (6 card) | `/profile/snapshot` o snapshot in TwinState | `metabolic_snapshot` |
| | Metabolic map / combustion | snapshot.`combustion_curve` | snapshot |
| | Power duration curve | `rolling_power_curve` in TwinState | curve JSON |
| | Expressiveness checklist | snapshot.`expressiveness` | snapshot |
| | Cross-validation semaforo | snapshot.`cross_validation` | snapshot |
| | Learning audit | `/team/calibration/apply` | `team_calibration_state` |
| | Durability predittiva | `/ride/durability` (ultima uscita lunga) | `activities.durability` |
| | Proiezione stagione | `/projection/season` | piano calendario |
| **Activity Analysis** | Summary cards (NP, IF, TSS) | `/ride/summary` | `activities.summary` |
| | Timeline multi-serie | `activity_charts` configs da summary | stream metadata |
| | Zone distribution | summary.`sections.zones` | summary |
| | Cardiac response | summary.`sections.cardiac` | summary |
| | HRV timeline | summary.`sections.hrv` | summary (solo ramp test) |
| | Mader durability | `/ride/durability` o summary.`mader_durability` | durability JSON |
| | Neuromuscular (sprint) | `/performance/neuromuscular-profile` | opzionale |
| **Testing Lab** | Upload FIT → proposta | `/test/propose` | proposal temporanea |
| | Conferma coach | `/test/confirm` | `measured_anchor` |
| | Test tablet/lattato | `/test/in-person` | envelope + result |
| | Pre-test prediction (obbligatorio) | `/profile/snapshot` **prima** del test | `validation_events.predicted_value` |
| | Post-test learning | `/team/calibration/update` | `calibration_model` |
| **Model Accuracy** | KPI MAE/bias per parametro | aggregazione `validation_events` | events |
| | Scatter predicted vs measured | `validation_events` | events |
| | Tabella eventi | DB | events |
| | Aggiorna modello | `/team/calibration/update` | `calibration_model` |
| **Coach Planner** | Editor workout | `/workouts/validate` | template library |
| | Prescrizione watt | `/workouts/prescribe` | prescription |
| | Preview fattibilità | `/workouts/feasibility` | feasibility report |
| | Assegnazione calendario | `/workouts/calendar/transition` | assignment status |
| | Target zones | snapshot.`zones` | snapshot |
| | Training focus cards | regole frontend su VLamax/durability | snapshot + readiness |
| | Season what-if | `/projection/season` | calendar plan |
| **Data Quality Center** | Checklist sensori | TwinState.`sensor_quality` | twin_state |
| | MMP completeness | TwinState.`rolling_power_curve` | twin_state |
| | Anchor freshness | TwinState.`measured_anchor` | twin_state |
| | Power source warning | `/power-source/normalize` | offset report |
| | Carico non-ciclismo | `/load/manual` | manual sessions |

### 6.6 Regole di navigazione tra pagine

| Evento utente | Sequenza API |
|---------------|--------------|
| Nuovo atleta + test FIT | propose → confirm → snapshot → twin/build |
| Upload uscita | ingest → summary → twin/update-from-ride → (se refresh) update-profile |
| Test validato con learning | snapshot (pre-test) → in-person/confirm → validation_event → calibration/update |
| Assegna workout | validate → prescribe → feasibility → (salva DB) → compare → twin/update-from-workout |
| Apri Digital Twin | carica twin_state → calibration/apply → render |

---

## 8. Flow operativi

### 8.1 Flow A — Creazione profilo (test FIT)

1. Coach carica 1+ FIT (sprint + CP3/6/12 idealmente).
2. `POST /test/propose` (multipart `files[]`) → `ProfileProposal`.
3. UI di **revisione**: sprint scelto, blocchi CP, confidence, file sorgente.
4. Coach conferma → `POST /test/confirm`:

```json
{
  "proposal": { "...ProfileProposal.to_dict()..." },
  "athlete": { "weight_kg": 72, "gender": "MALE", "training_years": 10, "discipline": "ENDURANCE" },
  "measured_on": "2026-06-01"
}
```

5. `POST /profile/snapshot` con MMP derivata.
6. `POST /twin/state/build` → salva `twin_state` in DB.

### 8.2 Flow B — Monitoraggio uscite

1. `POST /ride/ingest` — form: `file`, `ride_date`, `weight_kg`, `stored_curve_json` (opzionale).
2. `POST /ride/summary` con stesso FIT + opz. `metabolic_snapshot_json`.
3. `POST /twin/state/update-from-ride` con `ingest_result` + `ride_summary`.
4. Se `profile_should_refresh`: `POST /ride/update-profile` → aggiorna snapshot in TwinState.

### 8.3 Flow C — Prescrizione workout

Vedi `docs/WORKOUT_SYSTEM_BACKEND_V1.md`:

```
validate → prescribe → feasibility → (assign in DB) → compare → twin/update-from-workout-result
```

### 8.4 Flow D — Team learning

1. **Prima** del test: salva `predicted_value` da snapshot corrente.
2. Dopo test validato: crea `ValidationEvent` con `measured_value`.
3. `POST /team/calibration/update` con evento.
4. Su Digital Twin: `POST /team/calibration/apply` prima di mostrare KPI.

---

## 9. Snapshot metabolico — cuore del Digital Twin

Campi principali da mostrare nella pagina profilo:

| Campo | Descrizione | UI |
|-------|-------------|-----|
| `estimated_vo2max` | VO₂max stimato | KPI grande + unità ml/kg/min |
| `estimated_vlamax_mmol_L_s` | VLamax | KPI + scala fenotipo |
| `mlss_power_watts` / `mlss_power_wkg` | Soglia lattato | KPI W e W/kg |
| `fatmax_power_watts` | Massima ossidazione grassi | KPI |
| `map_aerobic_watts` | MAP aerobica | KPI secondario |
| `metabolic_phenotype` | Diesel / sprinter / … | Badge + icona |
| `confidence_score` | Affidabilità globale | Gauge 0–100% |
| `combustion_curve` | Grassi vs carboidrati vs potenza | Area chart stacked |
| `zones` | Zone da profilo | Barre o tabella |
| `cross_validation` | Coerenza modello vs potenza osservata | Semaforo + testo |
| `unmasked_estimates` | Valori "debug" se campo mascherato | Solo modal tecnico |
| `expressiveness` | Quali durate MMP mancano | Checklist ancore |

**Mascheramento:** se MMP non copre durate soglia, `mlss_power_watts` può essere `null` ma `unmasked_estimates` ha il valore grezzo. La UI **non** deve mostrare il valore mascherato come certo.

**Cross-validation (`cross_validation`):**

| `severity` | UI |
|------------|-----|
| `none` | Verde — profilo coerente |
| `mild` / `moderate` | Giallo — warning + `recommended_action` |
| `severe` | Rosso — "Non affidabile, ripetere test" |

---

## 10. Report singola attività — `build_workout_summary`

Endpoint: `POST /ride/summary` (multipart: `file` **oppure** `power_json`, `weight_kg`, opz. `ftp`, `metabolic_snapshot_json`).

### 10.1 Struttura risposta

```json
{
  "status": "success",
  "schema_version": "1.0.0",
  "stream_metadata": { "duration_s", "has_power", "has_hr", "has_rr", ... },
  "sections": {
    "power": { ... },
    "zones": { ... },
    "classification": { ... },
    "hrv": { ... },
    "cardiac": { ... },
    "mader_durability": { ... }
  },
  "headline": { ... },
  "warnings": [ "..." ],
  "section_contracts": { ... }
}
```

### 10.2 Sezioni e grafici consigliati

| Sezione | Contenuto | Visualizzazione |
|---------|-----------|-----------------|
| **power** | NP, IF, TSS, VI, MMP, CP+W′ fit | KPI row + `chart_power_duration_curve` |
| **zones** | Coggan 7 zone, Friel HR, Seiler 3 zone | Donut / barre stacked |
| **classification** | Fenotipo Coggan da MMP | `chart_phenotype_spider` |
| **hrv** | Timeline DFA-α₁ (se RR) | `chart_hrv_timeline` |
| **cardiac** | Drift, decoupling, recovery, kinetics | `chart_cardiac_drift`, `chart_hr_recovery` |
| **mader_durability** | CP residua ODE + potenze sostenibili | Vedi §10.3 |

**Headline** (card in cima): `tss`, `normalized_power`, `intensity_factor`, `worst_cardiac_drift_pct`, `rider_phenotype`, `mader_durability_loss_pct`, `mader_sustainable_3h_w`.

### 10.3 Mader durability

Endpoint dedicato: `POST /ride/durability` (richiede `metabolic_snapshot_json` valido).

| Campo | Grafico |
|-------|---------|
| `cp_residual_curve` | Linea tempo: CP residua (W) vs secondi |
| `kj_above_cp_curve` | Asse X alternativo: kJ sopra soglia |
| `durability_loss_pct` | KPI % perdita CP (nadir sessione) |
| `sustainability.sustainable_steady_power_w` | Tabella potenza max costante 1h–5h |
| `sustainability.training_recommendations` | Testo coach |

---

## 11. Catalogo motori — cosa fa il backend

### 11.1 Per attività (dopo ogni FIT)

| Modulo | Output chiave | Grafico / UI |
|--------|---------------|--------------|
| `fit_parser` | Stream campionato | — (interno) |
| `power_engine` | NP, IF, TSS, MMP | KPI + curva P-D |
| `zones_engine` | Tempo in zona | Donut multipli |
| `coggan_classifier` | Fenotipo | Spider / badge |
| `hrv_engine` | α₁ per finestra | Linea + bande 0.75 / 0.50 |
| `cardiac_engine` | Drift, decoupling | Linee segmenti |
| `mader_durability` | CP residua meccanicistica | Curve §10.3 |
| `interval_detector` | Categoria sessione | Chip TEST/HIIT/FREE |
| `session_router` | Motori eseguiti | Timeline pipeline (debug) |
| `neuromuscular_profile` | Pmax, repeat sprint | KPI sprint |

### 11.2 Longitudinale / profilo / twin

| Modulo | Output chiave | Grafico / UI |
|--------|---------------|--------------|
| `metabolic_profiler` | Snapshot completo | Digital Twin |
| `cross_validation_engine` | Coerenza | Semaforo + matrix |
| `metabolic_kalman` | Traiettoria nel tempo | Linea con banda |
| `metabolic_current` | Stato attuale + detraining | KPI decay |
| `detraining_engine` | CTL/ATL/TSB | `chart_training_load` |
| `team_learning_engine` | Correzioni calibrate | Learning audit panel |
| `season_projection_engine` | What-if stagionale | Linee CP/CTL proiettate |
| `manual_load` | Carico gym/corsa | Modificatore readiness |

### 11.3 Workout system

| Modulo | Endpoint | UI |
|--------|----------|-----|
| `validate` | `/workouts/validate` | Editor errori |
| `prescribe` | `/workouts/prescribe` | Preview watt per step |
| `feasibility` | `/workouts/feasibility` | Semáforo W′ |
| `compliance` | `/workouts/compare` | Score + discrepanze |
| `calendar_fsm` | `/workouts/calendar/transition` | Stato assegnazione |

---

## 12. Pagina Digital Twin — specifica funzionale

### 12.1 Obiettivo

Una vista **per atleta** che risponde a:

1. Chi è fisiologicamente (VO₂max, VLamax, MLSS, fenotipo)?
2. Il profilo è **affidabile** (ancore + cross-validation)?
3. Come **evolve** nel tempo (load, readiness, projection)?
4. Cosa può **sostenere** (mader_durability, season projection)?
5. Cosa **manca** per migliorare la stima?

### 12.2 Layout consigliato (desktop)

```
┌─────────────────────────────────────────────────────────────────┐
│ HEADER: Nome | peso | ultimo test | state_confidence (TwinState)│
│ [Badge anchor: OK / parziale / mancante] [Team calibrated?]     │
├─────────────────────────────────────────────────────────────────┤
│ ROW KPI (6 card): VO2max | VLamax | MLSS W | FatMax | MAP | W/kg│
├──────────────────────────┬──────────────────────────────────────┤
│ Curva potenza-durata     │ Combustione (fat vs CHO)             │
├──────────────────────────┴──────────────────────────────────────┤
│ COERENZA PROFILO (cross_validation) + Learning audit se attivo    │
├──────────────────────────┬──────────────────────────────────────┤
│ Carico CTL/ATL/TSB       │ Readiness / adaptive load            │
├──────────────────────────┴──────────────────────────────────────┤
│ DURABILITY (ultima uscita lunga) | SEASON PROJECTION (opzionale)  │
├─────────────────────────────────────────────────────────────────┤
│ ANCORE MANCANTI (expressiveness) + sensor_quality checklist     │
└─────────────────────────────────────────────────────────────────┘
```

### 12.3 Stati della pagina

| Stato | Condizione | Cosa mostrare |
|-------|------------|---------------|
| **Empty** | Nessun FIT / nessun test | CTA "Carica test sprint+CP" |
| **Partial** | Anchor parziale o MMP povera | Campi `null` grigiati + checklist ancore |
| **Ready** | TwinState + cross_validation ok | Tutti i pannelli predittivi |
| **Stale** | Anchor vecchio (>90 gg) | Banner "Ricalibrare con test" |
| **Calibrated** | Team learning attivo | Learning audit + badge "Team calibrated" |

### 12.4 Cosa **non** fare

- Non mostrare VO₂max/MLSS come "verità di laboratorio" senza test lattato.
- Non nascondere `warnings` e `cross_validation.severity`.
- Non usare DFA-α₁ da uscita libera per estrarre soglie.
- Non chiamare snapshot senza MMP con almeno 3 durate diverse.
- Non applicare calibrazione team senza `validation_events` pre-test.

---

## 13. `chart_builder` — integrazione pratica

Il backend non renderizza grafici: restituisce **config JSON** compatibili con Recharts / Chart.js / Plotly.

```python
from engines.io.chart_builder import (
    chart_power_duration_curve,
    chart_metabolic_combustion,
    chart_training_load,
    chart_cross_validation_matrix,
)
```

**Palette ufficiale:** vedi `COLORS` in `chart_builder.py`.

**Frontend:** componente `<EngineChart config={payload} />` che fa switch su `config.type`.

---

## 14. Modello dati da persistere (Supabase / DB)

| Entità | Campi minimi | Note |
|--------|--------------|------|
| `teams` | id, name, `calibration_model` JSON | Da `/team/calibration/update` |
| `athletes` | id, team_id, weight_kg, gender, phenotype | |
| `twin_states` | athlete_id, `twin_state` JSON, updated_at | **Entità centrale V5.1** |
| `measured_profile` | vo2max, mlss_watts, vlamax, measured_on | Da `/test/confirm` (anche in TwinState) |
| `power_curve` | athlete_id, curve JSON | Da `/ride/ingest` (anche in TwinState) |
| `activities` | fit_url, date, summary, durability JSON | `/ride/summary`, `/ride/durability` |
| `validation_events` | predicted, measured, parameter, protocol | **Obbligatorio per learning** |
| `workout_assignments` | workout, prescription, status, compliance | Coach Planner |
| `test_sessions` | envelope JSON, result JSON | Tablet |

Schema SQL di riferimento: `docs/workout_db_schema_v1.sql`.

---

## 15. Roadmap UI consigliata

### Fase 1 — MVP (sostituire CSV in `frontend/`)

- [ ] Client API verso `api_app.py` (tutti gli endpoint §6)
- [ ] TwinState build/update come persistenza centrale
- [ ] Lista atleti + Activity Analysis
- [ ] Digital Twin (snapshot + KPI + cross_validation)
- [ ] Upload FIT test → propose → confirm
- [ ] Upload FIT uscita → ingest → summary

### Fase 2 — Coach pro

- [ ] Testing Lab + validation_events + team calibration
- [ ] Model Accuracy page
- [ ] Coach Planner (workouts/*)
- [ ] mader_durability su uscite lunghe
- [ ] Season projection

### Fase 3 — Avanzato

- [ ] Kalman trend API (`/profile/kalman` — da aggiungere)
- [ ] Race simulation GPX (`/race/simulate` — da aggiungere)
- [ ] Data Quality Center completo
- [ ] Neuromuscular profile su attività sprint

---

## 16. Hardening e stress test — stato verificato

Eseguito su **Backend V5.1.0** (2026-06-01).

### 16.1 Comandi

```bash
# Hardening (malformed input, JSON safety, timeout)
python3 -m pytest -q -m "hardening" tests/pytest_hardening_*.py tests/pytest_security_hardening.py

# Stress subset (payload grandi, deadline strette)
python3 -m pytest -q -m "hardening and stress" tests/pytest_hardening_*.py

# Suite completa
python3 -m pytest -q tests/pytest_*.py
python3 -m pytest -q pytest_script_suite.py
```

### 16.2 Risultati ultima esecuzione

| Suite | Risultato |
|-------|-----------|
| Hardening (`-m hardening`) | **13 passed** |
| Stress (`-m "hardening and stress"`) | **5 passed** |
| Security hardening | incluso sopra |
| Multitenant contract (`pytest_multitenant_stress.py`) | **2 passed** |
| Full pytest (`tests/pytest_*.py`) | **55 passed**, 6 skipped |
| Script suite (`pytest_script_suite.py`) | **25 passed** |
| **Totale** | **~95 test verdi** |

I 6 skip sono test FIT/environment-dependent quando mancano file o dipendenze opzionali.

### 16.3 Cosa copre la suite

- Parser FIT su dati sparsi, gap, sensori enhanced
- FIT corrotti → `FitFileError` tipizzato
- Workout feasibility >1000 step sotto deadline
- Compliance con stream grandi, NaN, sensori mancanti
- API 4xx strutturati (no 500 non gestiti)
- Payload JSON ricorsivamente sicuri (no NaN/Inf)
- Limiti upload size e profondità JSON (`engines/core/security.py`)

### 16.4 Stress HTTP live (opzionale pre-release)

Richiede server uvicorn in esecuzione:

```bash
uvicorn api_app:app --host 0.0.0.0 --port 8000 &
python tools/stress/multitenant_stress.py \
  --base-url http://localhost:8000 \
  --athletes 20 --requests-per-athlete 15 \
  --output-dir stress_outputs/balanced
```

Output: `stress_summary.json`, `stress_requests.csv`, `stress_report.md`.

Vedi `docs/MULTI_TENANT_STRESS_TESTING.md` e `docs/HARDENING_TESTS.md`.

### 16.5 Gate CI consigliato

| Quando | Cosa eseguire |
|--------|---------------|
| Ogni PR su API/parser/workouts | `pytest -m hardening` |
| Pre-release | hardening + stress + `pytest_script_suite.py` |
| Pre-deploy infra | `multitenant_stress.py` contro staging |

---

## 17. Esempio flusso completo (sequenza V5.1)

```
1. Coach carica FIT test                    → POST /test/propose
2. UI revisione, coach conferma             → POST /test/confirm
3. Snapshot iniziale                        → POST /profile/snapshot
4. Crea gemello digitale                    → POST /twin/state/build → salva DB
5. Atleta pedala, FIT uscita                → POST /ride/ingest
6. Analisi attività                         → POST /ride/summary
7. Aggiorna TwinState                       → POST /twin/state/update-from-ride
8. Se profile_should_refresh                → POST /ride/update-profile
9. Pagina Activity Analysis                 → summary + durability da DB
10. Pagina Digital Twin                     → twin_state + calibration/apply
11. Test validato in lab                    → validation_event → /team/calibration/update
12. Coach assegna workout                   → validate → prescribe → feasibility
13. Atleta esegue, upload FIT               → /workouts/compare → twin/update-from-workout
14. Pianificazione stagione                 → /projection/season
```

---

## 18. Import Python utili

```python
from engines import (
    build_workout_summary,
    MetabolicProfiler,
    compute_session_durability,
    get_current_metabolic_status,
    tier_for,
    build_twin_state,
    update_twin_state_from_ride,
    project_season_from_plan,
)
from engines.io.session_router import route_and_run
from engines.io.chart_builder import chart_power_duration_curve, chart_metabolic_combustion
from engines.twin_state.models import TWIN_STATE_SCHEMA_VERSION
```

---

## 19. Endpoint ancora da aggiungere (fase futura)

| Endpoint proposto | Motore | Pagina target |
|-------------------|--------|---------------|
| `POST /profile/kalman` | `process_workout_history` | Digital Twin trend |
| `POST /race/simulate` | `simulate_gpx_race` | Coach Planner / pre-gara |

---

*Documento unificato per Backend-definitivo-V5 **5.1.0**. Aggiornare quando si aggiungono endpoint in `api_app.py` o nuovi motori in `engines/`.*
