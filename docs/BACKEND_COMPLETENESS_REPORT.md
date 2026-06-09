# Backend Completeness Report — V5 Team Learning

## Stato generale

Il backend è pronto come base di sviluppo per un prodotto frontend avanzato. È stateless, modulare e costruito attorno a motori fisiologici separati dall'API.

Questa consegna non include database, autenticazione o job queue: sono intenzionalmente lasciati allo strato applicativo/production. Il backend restituisce JSON serializzabili che il frontend/DB deve salvare e rimandare.

## Moduli principali

| Area | Stato | Note |
|---|---|---|
| API FastAPI | Pronta | `api_app.py` |
| FIT ingest | Pronto | parsing e power curve |
| MMP / power curve | Pronto | aggiornamento curva persistibile |
| Metabolic snapshot | Pronto | VO2max, VLamax, MLSS, FatMax, MAP |
| Expressiveness gate | Pronto | evita valori non affidabili |
| Workout summary | Pronto | report attività modulare |
| Mader durability | Pronto | durability meccanicistica |
| Test in presenza | Pronto | envelope tablet |
| Lab/lactate validation | Presente | da usare nei test validati |
| Anchor profile flow | Pronto | proposta → conferma coach → anchor |
| Kalman / Bayesian / Neural | Presente | motori avanzati già nel repo |
| Team Learning Engine | Aggiunto | apprendimento residuo team/atleta/fenotipo |
| Frontend MVP | Presente ma non definitivo | serve ricostruzione secondo blueprint |

## Endpoint disponibili

| Endpoint | Stato | Uso frontend |
|---|---|---|
| `GET /health` | Pronto | monitoraggio servizio |
| `POST /test/propose` | Pronto | upload FIT test |
| `POST /test/confirm` | Pronto | conferma coach e anchor |
| `POST /ride/ingest` | Pronto | import attività e curva MMP |
| `POST /ride/update-profile` | Pronto | aggiornamento profilo da ride |
| `POST /profile/snapshot` | Pronto | dashboard profilo metabolico |
| `POST /ride/summary` | Pronto | report attività |
| `POST /ride/durability` | Pronto | durability da snapshot |
| `POST /test/in-person` | Pronto | test tablet/lattato/Mader |
| `POST /team/calibration/update` | Aggiunto | aggiorna modello apprendimento team |
| `POST /team/calibration/apply` | Aggiunto | applica calibrazione a valore/snapshot |

## Cosa manca per produzione

Questi punti non sono bug del backend, ma responsabilità dello strato prodotto:

1. Autenticazione e ruoli.
2. Database persistente.
3. Storage file FIT.
4. Job queue per parsing e calcoli pesanti.
5. Audit log degli accessi e dei modelli.
6. Gestione GDPR e consensi.
7. Versionamento modello in DB.
8. Monitoring errori.
9. Rate limiting.
10. Backup e disaster recovery.

## Cosa deve salvare il database

Minimo indispensabile:

- team;
- atleti;
- file attività;
- curve MMP;
- anchor fisiologici;
- snapshot metabolici;
- workout summary;
- validation events;
- calibration model team;
- model version.

## Test eseguiti consigliati

```bash
PYTHONPATH=. pytest -q tests/pytest_smoke.py tests/test_team_learning_engine.py
```

Risultato atteso:

```text
6 passed
```

## Posizionamento tecnico

Il backend non deve essere presentato come AI generica. Deve essere presentato come:

> Physics/physiology-informed performance engine with audited residual learning.

In italiano:

> Motore di performance basato su fisiologia, validazione da test e apprendimento residuo auditabile.
