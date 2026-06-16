# Product Analytics Backend V1

Questo incremento aggiunge moduli backend neutrali e non proprietari per trasformare il motore fisiologico in una piattaforma prodotto più completa.

## Regola di naming

Nessun endpoint, documento, payload o commento introdotto in questo incremento usa nomi di piattaforme esterne o nomi commerciali del progetto. Tutti i nomi sono descrittivi e generici.

## Nuovi blocchi backend

| Area | Moduli | Endpoint principali |
|------|--------|---------------------|
| Activity intelligence | `engines/io/activity_intelligence.py`, `engines/io/data_quality_report.py` | `/ride/intelligence`, `/ride/data-quality` |
| Storico atleta | `engines/history/` | `/history/summary`, `/history/power-curve`, `/history/records`, `/history/load` |
| Readiness e load risk | `engines/readiness/` | `/readiness/today`, `/load/state/update`, `/load/risk` |
| Ability e breakthrough | `engines/performance/ability_profile.py`, `breakthrough_detector.py` | `/performance/ability-profile`, `/performance/breakthroughs` |
| Workout intelligence | `engines/workouts/recommendation_engine.py`, `progression_levels.py`, `adaptive_planner.py` | `/workouts/recommend`, `/workouts/progression-levels`, `/workouts/adapt-plan` |
| Workout export | `engines/workouts/exporters/` | `/workouts/export` |
| Planning | `engines/planning/` | `/planning/create-season-plan`, `/planning/adapt-week`, `/planning/check-load-risk` |
| Route/segment utilities | `engines/routes/` | motore disponibile per future API |
| Generic imports | `engines/integrations/` | normalizzazione e deduplica disponibili per future API |

## Principio architetturale

Il backend resta stateless:

1. Il frontend o il database persistono attività, TwinState, curve, calendario e storico.
2. Il backend riceve payload JSON o FIT.
3. Il backend restituisce envelope canonici calcolati.
4. Il frontend renderizza senza ricreare i calcoli.

## Nuovi output ad alto valore

- best efforts per durate comuni
- zone distribution potenza e frequenza cardiaca
- auto interval detection
- chart series downsampled
- data-quality score e signal coverage
- storico power curve multi-periodo
- personal records
- load trends acute/chronic/balance
- readiness score non medico
- ability profile per aree di performance
- breakthrough detection su curva potenza
- workout recommendation
- progression levels
- adaptive plan adjustment
- structured workout text export
- season plan rule-based
- planned load risk check

## Validazione eseguita

- `python -m compileall -q api engines`
- `python scripts/export_openapi.py` → 42 paths
- `python -m pytest -q tests/pytest_product_engines_v1.py` → 5 passed
- `python -m pytest -q tests/pytest_frontend_client_contract.py tests/pytest_openapi_contract.py tests/pytest_product_engines_v1.py` → 20 passed
- `python -m pytest -q tests/pytest_*.py` → 105 passed, 12 skipped

`ruff` non è stato eseguito nel sandbox perché il pacchetto non era installato nell'ambiente corrente.
