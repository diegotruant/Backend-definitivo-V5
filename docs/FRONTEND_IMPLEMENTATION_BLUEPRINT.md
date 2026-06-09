# Frontend Implementation Blueprint — Digital Twin Fisiologico WT

## 1. Missione del frontend

Il frontend deve rendere comprensibile un backend fisiologico molto profondo a tre utenti diversi:

1. **Coach** — vuole sapere cosa fare domani in allenamento.
2. **Performance scientist** — vuole sapere quanto il modello è accurato e perché.
3. **Direttore sportivo / management** — vuole capire stato squadra, disponibilità, ruolo gara.

Gli sviluppatori non devono inventare interpretazioni ciclistiche: devono usare i contratti, i dizionari metriche e le regole UX qui sotto.

---

## 2. Architettura applicativa consigliata

### Stack suggerito

- React + TypeScript.
- Chart library: Recharts, ECharts o Nivo.
- Stato: TanStack Query per API + Zustand/Redux solo se serve.
- Form: React Hook Form.
- Tabelle: TanStack Table.
- Backend base URL configurabile via `.env`.

### Cartelle consigliate

```text
frontend/src/
  api/
    client.ts
    endpoints.ts
  contracts/
    athlete.ts
    profile.ts
    activity.ts
    testing.ts
    teamLearning.ts
  dictionary/
    metricDictionary.ts
    coachCopy.ts
  components/
    kpi/
    charts/
    quality/
    layout/
  pages/
    TeamCommandCenter.tsx
    AthleteDigitalTwin.tsx
    ActivityAnalysis.tsx
    TestingLab.tsx
    ModelAccuracy.tsx
    CoachPlanner.tsx
    DataQualityCenter.tsx
  mocks/
    mockData.ts
```

---

## 3. Data model lato frontend/database

Il backend è stateless. Serve un DB esterno. Tabelle minime:

### `teams`

| Campo | Tipo | Note |
|---|---|---|
| `id` | string | team id |
| `name` | string | nome team |
| `calibration_model` | jsonb | output `/team/calibration/update` |
| `created_at` | timestamp | |

### `athletes`

| Campo | Tipo | Note |
|---|---|---|
| `id` | string | athlete id |
| `team_id` | string | FK |
| `name` | string | |
| `weight_kg` | number | aggiornabile |
| `gender` | string | valore per modello fisiologico |
| `training_years` | number | |
| `discipline` | string | ENDURANCE, ROAD, TT, ecc. |
| `phenotype` | string | da snapshot o coach |
| `latest_anchor` | jsonb | output `/test/confirm` |
| `latest_curve` | jsonb | output `/ride/ingest` |
| `latest_snapshot` | jsonb | output `/profile/snapshot` o calibrato |

### `activities`

| Campo | Tipo | Note |
|---|---|---|
| `id` | string | |
| `athlete_id` | string | |
| `date` | date | |
| `fit_file_url` | string | storage |
| `summary` | jsonb | output `/ride/summary` |
| `durability` | jsonb | output `/ride/durability` |
| `mmp_for_profiler` | jsonb | dalla ingest |
| `profile_should_refresh` | boolean | |

### `validation_events`

Ogni test validato deve salvare la previsione precedente.

| Campo | Tipo | Note |
|---|---|---|
| `id` | string | |
| `team_id` | string | |
| `athlete_id` | string | |
| `parameter` | string | mlss, vo2max, vlamax, fatmax, map |
| `predicted_value` | number | stima prima del test |
| `measured_value` | number | valore test validato |
| `error_abs` | number | measured - predicted |
| `error_pct` | number | |
| `protocol` | string | mader_lactate, lab_vo2, wingate |
| `phenotype` | string | climber, sprinter, ecc. |
| `data_depth_score` | number | 0-1 |
| `measurement_confidence` | number | 0-1 |
| `model_version` | string | versione backend/modello |
| `test_date` | date | |

---

## 4. Le pagine principali

# 4.1 Team Command Center

## Scopo

Vista iniziale per staff WT. Deve rispondere in 10 secondi a:

- Chi è pronto?
- Chi ha warning fisiologici o qualità dati scarsa?
- Il modello sta migliorando?
- Quali atleti vanno testati?

## Layout

### Header

- Nome team.
- Data ultimo sync.
- Numero atleti.
- Badge: `Team calibration: None / Learning / Calibrated / High confidence`.

### KPI cards

1. Atleti con profilo verde.
2. Atleti con warning giallo.
3. Atleti con warning rosso.
4. MAE MLSS team.
5. Numero test validati ultimi 90 giorni.
6. Atleti da ritestare.

### Tabella atleti

Colonne:

- Nome atleta.
- Fenotipo.
- MLSS W/kg.
- VO2max.
- VLamax.
- Durability score.
- Data depth.
- Ultimo test.
- Stato modello.
- Azione consigliata.

### Grafici

- Bar chart: stato atleti per colore.
- Line chart: accuratezza MLSS nel tempo.
- Scatter: MLSS W/kg vs durability score.
- Bar chart: test mancanti per atleta.

---

# 4.2 Athlete Digital Twin

## Scopo

La pagina più importante. Deve mostrare il gemello fisiologico dell'atleta.

## Sezioni

### A. Athlete header

- Nome.
- Ruolo/fenotipo.
- Peso.
- Ultimo aggiornamento.
- Confidenza profilo.
- Ultimo anchor: tipo test e data.

### B. KPI fisiologici

Mostrare 6 card:

1. MLSS W.
2. MLSS W/kg.
3. VO2max.
4. VLamax.
5. FatMax W.
6. MAP W.

Ogni card deve avere:

- valore;
- unità;
- badge: measured/model/calibrated/low confidence;
- trend rispetto ultimo snapshot;
- tooltip “cosa significa per il coach”.

### C. Metabolic map

Grafico consigliato:

- asse X: potenza W;
- linee/aree: contributo grassi, carboidrati, lattato o combustion curve;
- marker verticali: FatMax, MLSS, MAP.

Se il backend non fornisce una curva completa, mostrare una visualizzazione semplificata con zone.

### D. Power duration curve

- asse X logaritmico: durata 5s, 15s, 1m, 5m, 20m, 60m;
- asse Y: watt o W/kg;
- curva attuale;
- best precedenti;
- punti mancanti evidenziati.

### E. Expressiveness checklist

Mostrare se il profilo è costruito su dati completi:

- 5-15 s sprint: presente/mancante;
- 20-60 s glicolitico: presente/mancante;
- 3-12 min VO2max: presente/mancante;
- 20-60 min soglia: presente/mancante.

Se manca una finestra, non colpevolizzare l'utente: mostrare “Serve un test mirato”.

### F. Learning audit

Se è stata applicata calibrazione team:

- valore base modello;
- correzione atleta;
- correzione fenotipo;
- correzione team;
- valore finale;
- cap applicato;
- confidenza.

Esempio UI:

```text
MLSS finale: 372 W
Base model: 380 W
Athlete correction: -5 W
Phenotype correction: -2 W
Team correction: -1 W
Expected error: ±8 W
```

---

# 4.3 Activity Analysis

## Scopo

Analizzare una singola uscita o gara.

## Input

- FIT file oppure attività già caricata.
- Peso atleta.
- FTP/MLSS opzionali.
- Snapshot metabolico opzionale.

## Sezioni

### A. Summary cards

- Durata.
- Distanza.
- Dislivello.
- NP.
- IF.
- TSS.
- Work kJ.
- VI.

### B. Timeline

Grafico multi-serie:

- power;
- heart rate;
- cadence;
- altitude;
- core temperature se presente.

### C. Zone distribution

- tempo in zone potenza;
- tempo in zone metaboliche;
- confronto obiettivo seduta vs reale.

### D. Cardiac response

Se HR presente:

- cardiac drift;
- aerobic decoupling;
- HR recovery;
- cardiac efficiency.

Semaforo:

- verde: stabile;
- giallo: deriva moderata;
- rosso: deriva alta / possibile fatica o caldo.

### E. Durability

Mostrare:

- CP residua stimata;
- sustainable power dopo fatica;
- curva decadimento;
- interpretazione coach.

Frase tipo:

> L'atleta mantiene una buona capacità sostenibile dopo il carico accumulato: indicazione positiva per gare lunghe.

---

# 4.4 Testing Lab

## Scopo

Permettere allo staff di caricare test, validarli e creare anchor.

## Flow FIT test

1. Upload 1+ FIT.
2. Chiamare `/test/propose`.
3. Mostrare proposta:
   - file usati;
   - migliori segmenti trovati;
   - sprint;
   - CP/MMP;
   - warning.
4. Coach conferma o rifiuta.
5. Se conferma: `/test/confirm`.
6. Salvare anchor in DB.

## Flow in-person/lattato

1. Form tablet/test:
   - protocollo;
   - atleta;
   - step potenza/lattato;
   - device;
   - note.
2. Chiamare `/test/in-person`.
3. Mostrare risultato.
4. Se validato, creare `ValidationEvent` per Team Learning.

## Regola essenziale

Prima di caricare il valore misurato, salvare la previsione del modello. Senza previsione pre-test non esiste apprendimento scientificamente valido.

---

# 4.5 Model Accuracy & Learning

## Scopo

Questa è la pagina che rende il prodotto unico.

Deve mostrare che il sistema non è una black box: conosce il proprio errore.

## KPI

Per ogni parametro:

- N test validati;
- bias medio;
- MAE;
- RMSE se disponibile;
- errore %;
- confidenza;
- stato: insufficient / learning / calibrated.

## Grafici

1. Line chart: errore MLSS nel tempo.
2. Bar chart: MAE per parametro.
3. Scatter: predicted vs measured.
4. Bar chart: correzione per fenotipo.
5. Tabella: eventi validati.

## Tabella eventi

Colonne:

- Data.
- Atleta.
- Parametro.
- Previsto.
- Misurato.
- Errore.
- Protocollo.
- Fenotipo.
- Qualità dato.
- Versione modello.

## Copy importante

Usare questa frase nella pagina:

> Il modello viene calibrato solo con test validati. Ogni correzione è limitata da soglie fisiologiche conservative e tracciata nell'audit.

---

# 4.6 Coach Planner

## Scopo

Tradurre il profilo in target pratici.

## Sezioni

### A. Target zones

- endurance;
- FatMax;
- tempo;
- MLSS;
- VO2max;
- anaerobic/sprint.

### B. Training focus

Generare cards da regole semplici:

- VLamax alta + obiettivo GC: focus endurance/threshold, limitare glicolitico.
- VLamax bassa + bisogno sprint: inserire lavori neuromuscolari.
- MLSS stabile + durability bassa: lavori lunghi con blocchi finali.
- Cardiac drift alto: endurance base/recupero/calore/idratation check.

### C. Race role suggestion

Non deve decidere automaticamente, ma suggerire:

- GC/climber;
- domestique endurance;
- lead-out;
- sprinter;
- breakaway rider;
- TT specialist.

---

# 4.7 Data Quality Center

## Scopo

Evitare decisioni basate su dati poveri.

## Checklist

- Power presente?
- HR presente?
- RR presente?
- Cadence presente?
- Temperatura/core temp presente?
- Power meter stabile?
- MMP completa?
- Ultimo test recente?
- Ultimo anchor affidabile?
- Snapshot calibrato?

## Output

Semaforo globale:

- Verde: dati sufficienti.
- Giallo: usare cautela.
- Rosso: test richiesto.

---

## 5. Design system fisiologico

### Colori semaforo

- Verde: affidabile / OK.
- Giallo: cautela / dati incompleti.
- Rosso: non affidabile / test richiesto.
- Blu: modello fisiologico.
- Viola: calibrazione appresa.
- Grigio: non disponibile.

### Badge obbligatori

- `Measured`
- `Standard formula`
- `Model estimate`
- `Team calibrated`
- `Low confidence`
- `Insufficient data`
- `Experimental`

### Tooltips obbligatori

Ogni metrica avanzata deve avere tooltip:

1. cosa significa;
2. come usarla;
3. da quali dati viene;
4. quanto è affidabile.

---

## 6. Grafici da implementare

| Grafico | Pagina | Tipo |
|---|---|---|
| Power duration curve | Athlete Digital Twin | line, x log |
| Combustion curve | Athlete Digital Twin | stacked area / line |
| Zone distribution | Activity Analysis | stacked bar / donut |
| Activity timeline | Activity Analysis | multi-line |
| Durability decay | Activity Analysis | line |
| Predicted vs measured | Model Accuracy | scatter |
| Error over time | Model Accuracy | line |
| MAE by parameter | Model Accuracy | bar |
| Team athlete status | Command Center | bar |
| Data completeness | Data Quality | checklist/radar |

---

## 7. Endpoint usage recipes

### Creare profilo da test FIT

```ts
const proposal = await api.proposeTest(files)
// coach review screen
const anchor = await api.confirmTest({ proposal, athlete, measured_on })
storeAthleteAnchor(anchor)
```

### Importare attività

```ts
const ingest = await api.ingestRide({ file, ride_date, weight_kg, stored_curve_json })
storeCurve(ingest.curve)
if (ingest.profile_should_refresh) {
  const snapshot = await api.profileSnapshot({ mmp: ingest.mmp_for_profiler, athlete })
  storeSnapshot(snapshot)
}
```

### Applicare team calibration

```ts
const calibrated = await api.applyTeamCalibration({
  calibration_model: team.calibration_model,
  snapshot,
  athlete_id: athlete.id,
  phenotype: athlete.phenotype,
  data_depth_score: snapshot.confidence_score ?? 1
})
```

### Aggiornare calibrazione team dopo test validato

```ts
const updatedModel = await api.updateTeamCalibration({
  team_id: team.id,
  calibration_model: team.calibration_model,
  events: [validationEvent]
})
storeTeamCalibration(updatedModel)
```

---

## 8. Regole anti-errori per sviluppatori

1. Non calcolare fisiologia nel frontend.
2. Non inventare valori mancanti.
3. Non nascondere warning severi.
4. Non confondere FTP con MLSS.
5. Non mostrare VO2max/VLamax come misurati se sono stimati.
6. Non applicare calibrazione team se `calibration_model` è vuoto.
7. Non usare test validati senza salvare la previsione pre-test.
8. Non mostrare grafici senza unità.
9. Non aggregare atleti con unità diverse senza normalizzare W/kg.
10. Non fare claim “il modello non sbaglia”. Usare “errore atteso ridotto e tracciato”.

---

## 9. Definition of Done per il primo frontend serio

Il primo rilascio è accettabile se contiene:

- Login/team selector anche mock.
- Lista atleti.
- Upload FIT per test.
- Upload FIT per ride.
- Athlete Digital Twin con KPI e warning.
- Activity Analysis con summary e zone.
- Testing Lab con conferma coach.
- Model Accuracy con almeno tabella eventi e MAE per parametro.
- Persistenza JSON per anchor, curve, snapshot, calibration model.
- Tooltips metrica.
- Stati loading/error/empty.

Non è necessario avere subito tutti i grafici avanzati. È necessario non comunicare male la fisiologia.
