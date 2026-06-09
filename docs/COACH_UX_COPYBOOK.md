# Coach UX Copybook — Come spiegare i numeri senza conoscere il ciclismo

Questo file contiene testi pronti da usare in UI, tooltip, badge, empty states e warning.

## 1. Regola linguistica

Non usare mai “misurato” se il backend ha prodotto una stima modellata.

Usare:

- “stimato dal modello”;
- “calibrato su test del team”;
- “validato da test”;
- “dato insufficiente”;
- “richiede test mirato”.

## 2. Badge

### Measured

Testo badge: `Misurato`

Tooltip:

> Valore ottenuto direttamente da test o sensore, non stimato dal modello.

### Model estimate

Testo badge: `Stima modello`

Tooltip:

> Valore stimato dal modello fisiologico usando potenza, profilo atleta e curva MMP. Interpretare insieme alla confidenza.

### Team calibrated

Testo badge: `Calibrato team`

Tooltip:

> La stima è stata corretta usando errori storici osservati nei test validati del team.

### Low confidence

Testo badge: `Bassa confidenza`

Tooltip:

> Il dato disponibile non copre tutte le finestre fisiologiche necessarie. Programmare un test mirato.

### Insufficient data

Testo badge: `Dato insufficiente`

Tooltip:

> Il backend non ha dati sufficienti per mostrare questo valore in modo responsabile.

## 3. Tooltip metriche

### MLSS

> Potenza stimata alla massima stabilità metabolica sostenibile. Utile per lavori soglia, pacing cronometro e valutazione endurance avanzata.

### VO2max

> Capacità aerobica massima stimata. Indica il potenziale del sistema aerobico. Se non proviene da spirometria, va considerata una stima.

### VLamax

> Indicatore della capacità glicolitica. Valori alti favoriscono sprint e cambi ritmo, ma aumentano il consumo di carboidrati. Richiede dati brevi/sprint affidabili.

### FatMax

> Potenza stimata alla quale l'atleta massimizza l'uso dei grassi. Utile per endurance e gestione nutrizionale, ma meno certa senza dati metabolici diretti.

### Durability

> Capacità di mantenere prestazione dopo fatica accumulata. Molto importante per gare lunghe e tappe World Tour.

### Cardiac drift

> Aumento della frequenza cardiaca a parità di potenza. Può indicare fatica, caldo, disidratazione o base aerobica insufficiente.

### MMP

> Miglior potenza media dell'atleta per diverse durate. È la curva base usata dal modello fisiologico.

## 4. Semafori

### Profilo verde

> Profilo coerente. I dati coprono le finestre principali e la confidenza è sufficiente per usare i target in allenamento.

### Profilo giallo

> Profilo utilizzabile con cautela. Alcune finestre dati mancano o la confidenza è moderata. Programmare un test mirato.

### Profilo rosso

> Profilo non affidabile per decisioni importanti. Servono nuovi dati o validazione con test.

## 5. Messaggi per Model Accuracy

### Nessun test validato

> Il team non ha ancora test validati. Il modello usa solo la fisiologia generale e non può ancora correggere gli errori specifici del team.

### Apprendimento iniziale

> Il sistema sta iniziando a calibrare le stime. Servono più test validati per ridurre l'incertezza.

### Calibrazione attiva

> Il modello usa gli errori storici del team per correggere le nuove stime. Ogni correzione è limitata da soglie conservative.

### Correzione applicata

> La stima finale include una correzione appresa da test validati. Apri l'audit per vedere valore base, correzioni e margine atteso.

## 6. Empty states

### Mancano dati sprint

> Manca un effort breve massimale. VLamax e capacità glicolitica sono meno affidabili. Programmare sprint 10–30 secondi in condizioni controllate.

### Mancano dati soglia

> Manca un effort lungo 20–60 minuti. MLSS e FatMax potrebbero essere mascherati o avere bassa confidenza.

### Nessun HR

> Frequenza cardiaca non disponibile. Cardiac drift e aerobic decoupling non possono essere calcolati.

### Nessun RR

> RR intervals non disponibili. HRV e DFA-alpha1 non possono essere calcolati.

## 7. Frasi commerciali sicure

Usare:

> Il sistema riduce progressivamente l'errore delle stime grazie ai test validati del team.

> Ogni stima mostra confidenza, origine del dato e audit della correzione.

> La piattaforma combina modello fisiologico, dati reali e validazione longitudinale.

Non usare:

> Il sistema non sbaglia più.

> L'AI misura VO2max senza test.

> Sostituisce il laboratorio.
