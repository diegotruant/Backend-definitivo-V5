# Digital Twin — Demo paper per coach World Tour

**Validazione Mader al lattato e Team Learning con audit trail**

*Documento dimostrativo · v5.2.1 · Giugno 2026*

---

## Abstract

Questo paper illustra, attraverso un caso studio realistico, il differenziatore principale del backend fisiologico Digital Twin rispetto alle piattaforme di allenamento generiche: un **contratto di fiducia** a tre livelli tra motore Mader, test al lattato in presenza e calibrazione di squadra con audit completo.

Il caso segue la **Squadra Demo WT** durante una settimana di test in sala: un nuovo grimpeur (Marco Rossi) viene validato con protocollo Mader; tre colleghi hanno già contribuito alla memoria di cohort; un neo-pro successivo (Paolo C.) beneficia della correzione team prima ancora del proprio test al lattato.

**Risultato chiave:** il sistema non sostituisce il lattato con una stima opaca — lo usa per **validare** il modello, **registrare** l'errore pre-test e **correggere** le stime future con limiti conservativi e tracciabilità.

---

## 1. Il problema del coach World Tour

Uno staff d'élite gestisce 25–30 atleti con esigenze contrastanti: grimpeurs, rouleurs, sprinter, gregari. Ogni stagione si ripresentano le stesse domande:

| Domanda del coach | Risposta tipica delle piattaforme generiche | Limite |
|-------------------|---------------------------------------------|--------|
| Posso fidarmi della soglia stimata da potenza? | «FTP aggiornato automaticamente» | Nessuna validazione indipendente |
| Questo numero è misurato o modellato? | Spesso ambiguo | Il coach non distingue ground truth da stima |
| Perché il modello sbaglia sui miei grimpeurs? | Silenzio | Nessuna memoria di cohort |
| Cosa faccio dopo il test al lattato? | PDF o numero in tabella | Nessun verdetto operativo |
| Chi ha corretto questo valore e perché? | Nessun audit | Impossibile difendere la decisione davanti allo sport scientist |

Il Digital Twin affronta queste lacune con un'architettura **fisica-informata** (modello Mader), **auto-critica** (expressiveness gate, verdetto di validazione) e **apprendimento residuale auditato** (Team Learning Engine).

---

## 2. Architettura del contratto di fiducia

```
┌─────────────────────────────────────────────────────────────────────────┐
│  LIVELLO 1 — FISICA (Mader)                                             │
│  MMP → VO2max, VLamax, MLSS, FatMax                                     │
│  Tier: MODEL · Onestà: expressiveness gate maschera output inaffidabili │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LIVELLO 2 — VALIDAZIONE (Lattato in presenza)                          │
│  D-max (ground truth geometrica) vs MLSS predetta da MMP                │
│  Output: validated true/false · errore % · azione raccomandata          │
│  Tier: REFERENCE (lattato) + MODEL (verdetto)                           │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LIVELLO 3 — CALIBRAZIONE TEAM (Residual learning)                      │
│  Errore = misurato − predetto (PRIMA del test)                          │
│  Correzione bounded: team → fenotipo → atleta                           │
│  Tier: MODEL · Audit: ogni componente tracciata                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Principio guida:** il Team Learning **non sostituisce** il modello Mader. Impara solo la correzione residua, con cap assoluti e percentuali per parametro (es. MLSS ±25 W / 5%).

---

## 3. Caso studio — Settimana test Squadra Demo WT

### 3.1 Contesto

| Parametro | Valore |
|-----------|--------|
| Squadra | Demo WT (`wt_demo_squadra`) |
| Fenotipo principale | Grimpeur (`climber`) |
| Periodo | 8–10 giugno 2026 |
| Protocollo | Mader (6 step × 5 min, prelievo lattato a fine step) |
| Dispositivo | Rulli Wahoo KICKR, modalità ERG |

### 3.2 Cast

| Atleta | Ruolo nel caso | Peso | Test lattato |
|--------|----------------|------|--------------|
| **Marco Rossi** | Nuovo ingaggio, protagonista validazione | 62 kg | Sì (10 giu) |
| Luca B. | Collega grimpeur, evento team #1 | — | Sì (8 giu) |
| Tom H. | Collega grimpeur, evento team #2 | — | Sì (8 giu) |
| Jonas V. | Collega grimpeur, evento team #3 | — | Sì (9 giu) |
| **Paolo C.** | Neo-pro successivo, senza lattato | 58 kg | No (stima calibrata) |

---

## 4. Fase A — Profilo non invasivo (Marco Rossi)

Prima del test in sala, il sistema costruisce un profilo metabolico dalla curva MMP storica di Marco.

### 4.1 Curva MMP (estratto)

| Durata | Potenza (W) | Finestra fisiologica |
|--------|-------------|----------------------|
| 5 s | 850 | Neuromuscolare |
| 60 s | 400 | Glicolitico |
| 300 s | 285 | VO₂max |
| 720 s | 275 | VO₂max |
| 1200 s | 278 | Soglia |
| 3600 s | 262 | Soglia |

### 4.2 Output `POST /profile/snapshot`

| Parametro | Valore | Affidabilità |
|-----------|--------|--------------|
| MLSS stimata | **265 W** | `mlss_reliable: true` |
| VO₂max stimato | 55.0 ml/kg/min | Sì |
| VLamax stimato | 0.18 mmol/L/s | Sì |
| `confidence_score` | 0.79 | Moderata-alta |
| `fully_expressive` | **true** | Tutte e 4 le finestre coperte |

> **Nota coach:** la curva MMP è *espressiva* — copre sprint, glicolitico, VO₂max e soglia. Senza la finestra 20–60 min o 20–60 min di soglia, il sistema mascherebbe VLamax o MLSS invece di mostrare numeri fuorvianti.

**Domanda operativa:** *«Posso monitorare Marco solo con la potenza, senza ripetere il lattato?»*  
→ Serve la Fase B.

---

## 5. Fase B — Test Mader e verdetto di validazione

### 5.1 Protocollo eseguito

| Step | Potenza (W) | Lattato (mmol/L) | FC media |
|------|-------------|------------------|----------|
| 1 | 180 | 1.1 | 118 |
| 2 | 210 | 1.5 | 132 |
| 3 | 240 | 2.2 | 145 |
| 4 | 265 | 3.8 | 158 |
| 5 | 285 | 5.9 | 168 |
| 6 | 305 | 9.1 | 176 |

### 5.2 Confronto ground truth vs modello

| Metrica | Valore |
|---------|--------|
| MLSS da lattato (D-max) | **265 W** |
| MLSS predetta da MMP (pre-test) | **265 W** |
| Errore assoluto | 0 W |
| Errore percentuale | **0.0%** |
| Tolleranza validazione | ±8% |
| **`validated`** | **`true`** |
| Severità | `none` |

### 5.3 Verdetto (testuale dal backend)

> *Model VALIDATED for this athlete. MLSS predicted from MMP (265W) matches lactate-measured MLSS (265W) within 8% (error +0.0%). Monitoring can now continue non-invasively without repeating the lactate test.*

### 5.4 Azione raccomandata

> *Proceed with non-invasive monitoring. Re-evaluate with a new lactate test only after major physiological changes (long training block, extended break, injury).*

**Momento WOW per il coach:** non è un numero in una tabella — è un **permesso operativo** documentato. Il sistema ha confrontato due metodi indipendenti (D-max geometrico vs modello Mader su MMP) e ha emesso un verdetto con soglia, severità e follow-up.

---

## 6. Fase C — Memoria di squadra (Team Learning)

Nella stessa settimana, tre grimpeurs hanno già completato il protocollo Mader. Per ciascuno il sistema ha registrato la **predizione prodotta PRIMA del test** e il valore misurato al lattato.

### 6.1 Eventi di validazione

| Atleta | Predetto (W) | Misurato (W) | Errore (W) | Interpretazione |
|--------|--------------|--------------|------------|-----------------|
| Luca B. | 385 | 370 | **−15** | Modello sovrastima |
| Tom H. | 372 | 358 | **−14** | Modello sovrastima |
| Jonas V. | 398 | 382 | **−16** | Modello sovrastima |

### 6.2 Statistiche cohort (grimpeur)

| Statistica | Valore |
|------------|--------|
| Eventi team | 3 |
| Bias medio ponderato | **−15.0 W** |
| MAE | 15.0 W |
| Pattern | Sovrastima sistematica MLSS su grimpeurs |

> **Insight:** non è un difetto di Marco — è un **bias di cohort**. Il modello Mader con i prior di default tende a sovrastimare la soglia su questo sottoinsieme della rosa.

### 6.3 Meccanismo di correzione

La correzione residua è **bounded**:

| Parametro | Cap assoluto | Cap percentuale |
|-----------|--------------|-----------------|
| MLSS | ±25 W | 5% |
| VO₂max | ±4 ml/kg/min | 5% |
| VLamax | ±0.08 mmol/L/s | 15% |

In produzione servono ≥5 eventi team per attivare la correzione; in questo caso studio ne bastano 3 (config demo).

---

## 7. Fase D — Neo-pro calibrato (Paolo C.)

Arriva Paolo C. (58 kg). Ha una MMP espressiva ma **nessun test al lattato**. Il coach deve pianificare gli allenamenti in attesa del test.

### 7.1 Stima grezza vs calibrata

| Stadio | MLSS (W) | Fonte |
|--------|----------|-------|
| Modello grezzo (solo MMP) | **300** | `POST /profile/snapshot` |
| Correzione team | **−14.3** | Team Learning |
| **MLSS calibrata** | **285.8** | `POST /team/calibration/apply` |
| Cap applicato | ±15 W | Sicurezza conservativa |

### 7.2 Audit trail della correzione

| Scope | Bias (W) | n eventi | Peso nel blend |
|-------|----------|----------|----------------|
| team | −15.0 | 3 | 0.11 |
| phenotype (climber) | −15.0 | 3 | 0.17 |

Ogni campo è ispezionabile nel payload `team_calibration` — il coach o lo sport scientist può rispondere alla domanda: *«Chi ha spostato questo numero e su quale evidenza?»*

### 7.3 Ciclo chiuso

Dopo il test Mader di Paolo, un nuovo `ValidationEvent` si aggiunge al modello. La calibrazione diventa più precisa per il fenotipo grimpeur e, dopo 2 validazioni individuali, per Paolo stesso.

---

## 8. Confronto con piattaforme generiche

| Capacità | TrainingPeaks / WKO / Intervals | Digital Twin |
|----------|--------------------------------|--------------|
| Stima soglia da potenza | Sì (eFTP, MCP, FTP) | Sì (Mader su MMP) |
| Validazione vs lattato indipendente | No | **Sì — verdetto ±8%** |
| Mascheramento output inaffidabili | Raro | **Expressiveness gate** |
| Memoria errori di squadra | No | **Team Learning + audit** |
| Correzione bounded e conservativa | N/A | **Cap per parametro** |
| Durabilità meccanistica (CP residua) | Empirica o assente | Mader ODE (modulo separato) |
| Audit pre-test vs post-test | No | **ValidationEvent obbligatorio** |

---

## 9. Conclusioni

Il valore per un coach World Tour non è «un'altra stima di FTP». È un **sistema che si misura, ammette i limiti e migliora sulla rosa**:

1. **Prima del lattato** — profilo Mader con gate di espressività; niente numeri fabbricati.
2. **Con il lattato** — verdetto `validated` con soglia, severità e azione; permesso operativo documentato.
3. **Dopo il lattato** — errore pre-test archiviato; calibrazione team per i prossimi atleti.
4. **Sempre** — audit trail su ogni correzione; difendibile davanti allo staff scientifico.

### Frase di posizionamento

> *Un motore fisiologico Mader validato dal lattato, con apprendimento residuale auditato sul cohort della squadra.*

---

## Appendice A — Endpoint dimostrati

| Endpoint | Fase | Funzione |
|----------|------|----------|
| `POST /profile/snapshot` | A, D | Profilo metabolico da MMP |
| `POST /test/in-person` | B | Protocollo Mader + verdetto |
| `POST /team/calibration/update` | C | Aggiunge ValidationEvent |
| `POST /team/calibration/apply` | D | Applica correzione con audit |

## Appendice B — Rigenerazione dati live

I numeri di questo paper corrispondono all'output deterministico del motore:

```bash
python3 tools/demo/wt_coach_demo.py --no-pause --json
python3 tools/generate_demo_wt_paper_pdf.py
```

## Appendice C — Riferimenti nel codebase

| Modulo | Path |
|--------|------|
| Modello Mader | `engines/metabolic/metabolic_profiler.py` |
| Validazione lattato | `engines/metabolic/lactate_validation_engine.py` |
| Expressiveness | `engines/metabolic/mader_constants.py` |
| Team Learning | `engines/metabolic/team_learning_engine.py` |
| Test in presenza | `engines/performance/test_protocols.py` |
| Copybook coach | `docs/COACH_UX_COPYBOOK.md` |

---

*Fine documento*
