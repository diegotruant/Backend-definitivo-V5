# Backend-definitivo-V5

Backend Python per analisi fisiologica e performance cycling (Digital Twin).
Il repository mantiene la logica applicativa esistente e aggiunge una struttura di lavoro più professionale per sviluppo, qualità e CI.

## Panoramica

- Core analytics in moduli Python + facade `engines/`
- API HTTP con FastAPI in `api_app.py`
- Suite storica di test script-based (`test_*.py`)
- Nuovi smoke test in `tests/`

## Setup locale

Prerequisiti:

- Python 3.10+
- `pip`

Installazione:

```bash
make install
```

oppure:

```bash
python -m pip install -r requirements-dev.txt
```

## Variabili ambiente

Copiare il template:

```bash
cp .env.example .env
```

Variabili principali:

- `DIGITAL_TWIN_API_TITLE`
- `DIGITAL_TWIN_API_VERSION`
- `UVICORN_HOST`
- `UVICORN_PORT`
- `UVICORN_RELOAD`

## Comandi sviluppo

```bash
make run        # avvia API FastAPI (uvicorn)
make test       # smoke test pytest
make lint       # ruff
make format     # black
make typecheck  # mypy
make precommit  # esegue hooks su tutti i file
```

## Test legacy (compatibilità)

La suite storica resta disponibile:

```bash
python -m pytest -q pytest_script_suite.py
```

## Struttura cartelle

```text
.
├── .github/workflows/        # CI
├── docs/                     # documentazione tecnica/scientifica
├── engines/                  # package facade pubblico
├── frontend/                 # client TypeScript (non ristrutturato)
├── reports/                  # report generati
├── scripts/                  # script di supporto (scaffold per crescita)
├── tests/                    # test pytest moderni (smoke)
├── api_app.py                # entrypoint API FastAPI
├── pyproject.toml            # package metadata + tool config
├── requirements-dev.txt      # dipendenze sviluppo
├── .pre-commit-config.yaml   # hooks qualità automatica
└── Makefile                  # task comuni sviluppo
```

## CI

La GitHub Action (`.github/workflows/ci.yml`) esegue su push/PR:

1. install dipendenze con cache pip
2. `make lint`
3. `make test`

## Note

- Nessun cambiamento funzionale intenzionale agli engine.
- La configurazione è pensata per evolvere gradualmente verso una struttura ancora più modulare senza rompere compatibilità esistente.
