# Handoff per team di sviluppo — Digital Twin Fisiologico Cycling Backend V5

## Obiettivo di questa consegna

Questo repository contiene il backend per una piattaforma di performance intelligence per ciclismo elite. Il team frontend non deve conoscere il ciclismo: deve costruire un'interfaccia che visualizza correttamente i dati, rispetta la confidenza dei modelli e guida coach e performance scientist nelle decisioni.

Il prodotto non deve apparire come un clone di Strava, Garmin o TrainingPeaks. Deve apparire come un **digital twin fisiologico**: un sistema che combina dati reali, modelli metabolici, test validati e apprendimento atleta/team.

## Cosa è già pronto nel backend

- API FastAPI stateless in `api_app.py`.
- Parsing FIT e ingestione attività.
- Power curve / MMP.
- Profilo metabolico da MMP.
- Stima VO2max, VLamax, MLSS, FatMax, MAP.
- Expressiveness gate: il sistema sa quando i dati non bastano.
- Workout summary.
- Durability meccanicistica.
- HRV / cardiac response quando i dati sono presenti.
- Test in presenza via envelope JSON.
- Validazione lattato / Mader.
- Anchor fisiologico confermato dal coach.
- Team Learning Engine: apprendimento residuo da test validati.

## File fondamentali per il frontend

| File | Scopo |
|---|---|
| `api_app.py` | Contratti API disponibili oggi |
| `docs/FRONTEND_IMPLEMENTATION_BLUEPRINT.md` | Specifica frontend principale |
| `docs/API_PAYLOAD_EXAMPLES.md` | Esempi payload/response per ogni endpoint |
| `docs/COACH_UX_COPYBOOK.md` | Testi, badge e semafori da mostrare ai coach |
| `docs/TEAM_LEARNING_ENGINE.md` | Spiegazione del motore di auto-apprendimento |
| `docs/FRONTEND_DEVELOPER_GUIDE.md` | Guida tecnica esistente estesa |
| `frontend/src/contracts.ts` | TypeScript interfaces base per iniziare |
| `frontend/src/metricDictionary.ts` | Dizionario metriche per UI |
| `frontend/src/api.ts` | Client API minimale |
| `frontend/src/mockData.ts` | Mock data per prototipare pagine senza backend live |

## Principio UI non negoziabile

Ogni numero deve dire all'utente se è:

1. misurato direttamente;
2. calcolato con formula standard;
3. stimato da modello fisiologico;
4. appreso/corretto da test validati;
5. non affidabile o non disponibile.

Non mostrare mai un valore `null`, `skipped` o mascherato come fosse un valore certo.

## Le 7 pagine da costruire

1. **Team Command Center** — vista team, accuratezza modello, stato atleti.
2. **Athlete Digital Twin** — profilo metabolico completo del singolo atleta.
3. **Activity Analysis** — analisi singola uscita/allenamento.
4. **Testing Lab** — caricamento test FIT/tablet/lattato e conferma coach.
5. **Model Accuracy & Learning** — dashboard di auto-apprendimento team.
6. **Coach Planner** — target operativi, zone, raccomandazioni.
7. **Data Quality Center** — completezza dati, warning, sensori mancanti.

## Cosa deve essere memorabile per un team WT

La piattaforma deve comunicare tre messaggi:

1. **Non guarda solo quanto forte va l'atleta fresco, ma quanto resta forte dopo ore di fatica.**
2. **Non dà numeri magici: misura il proprio errore rispetto a test Mader/lattato/lab.**
3. **Più il team la usa e valida, più il modello si calibra sulla coorte del team.**

## Regola di implementazione

Il backend è stateless. Il frontend/database deve salvare e rimandare:

- `curve` per atleta;
- `anchor` per atleta;
- `metabolic_snapshot` più recente;
- `calibration_model` per team;
- `ValidationEvent` per ogni test validato;
- `model_version` associato a ogni previsione.

## Comando rapido backend

```bash
pip install -r requirements-dev.txt
uvicorn api_app:app --reload
```

Health check:

```bash
curl http://localhost:8000/health
```

## Test rapidi

```bash
PYTHONPATH=. pytest -q tests/pytest_smoke.py tests/test_team_learning_engine.py
```
