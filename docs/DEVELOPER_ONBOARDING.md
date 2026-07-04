# Guida onboarding sviluppatori — Backend Digital Twin V5.2.6

Documento in italiano per sviluppatori che entrano nel progetto **Backend-definitivo-V5**. Non serve conoscere il ciclismo: serve capire come il backend espone dati fisiologici onesti, testabili e pronti per un frontend coach-facing.

## Benvenuto

Questo repository è il backend di una piattaforma di **digital twin fisiologico** per ciclismo d'élite. Il backend è:

- **stateless** — non salva DB; il frontend/DB persiste `TwinState`, curve, calibrazione
- **contract-first** — OpenAPI committato + test di prodotto
- **modulare** — router → service → engines

Superficie attuale: **135 path OpenAPI**, **43 tipi di grafico** via `/meta/chart-config`.

## Prerequisiti

| Tool | Versione |
|------|----------|
| Python | 3.10+ (CI usa 3.11) |
| pip / venv | consigliato `.venv` |
| make | per i comandi di sviluppo |
| Docker | opzionale, per smoke production-style |

## Setup rapido (prima ora)

```bash
git clone <repo>
cd Backend-definitivo-V5
python3 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env   # opzionale
make run               # http://127.0.0.1:8000
```

Verifica:

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/openapi.json | python3 -c "import sys,json; print(len(json.load(sys.stdin)['paths']), 'paths')"
```

Swagger UI: `http://localhost:8000/docs`

## Architettura in 30 secondi

```text
api/routers/     → HTTP sottile (multipart, status code)
api/services/    → orchestrazione use-case (no FastAPI)
engines/         → algoritmi fisiologici, FIT, modelli
openapi/         → contratto HTTP committato
tests/           → pytest smoke + contract + hardening
```

Flusso tipico: **router → service → engines**. Dettaglio in `docs/ARCHITECTURE.md`.

### Pipeline attività ufficiale

Per ogni uscita in bici, il percorso canonico è:

```text
FIT / stream → parse → data quality → workout summary → activity intelligence
            → activity charts → full activity bundle → JSON frontend
```

Endpoint preferito: **`POST /ride/full-bundle`** (`rideFullBundle`).  
Compatibilità stretta: `POST /ride/summary`.

## Cosa leggere (ordine consigliato)

| # | Documento | Perché |
|---|-----------|--------|
| 1 | `README.md` | panoramica repo, comandi, CI |
| 2 | `docs/API_ENDPOINT_INDEX.md` | inventario completo 135 endpoint |
| 3 | `docs/FRONTEND_DEVELOPER_GUIDE.md` | TwinState, pagine prodotto, zone doppie |
| 4 | `docs/CONTRACT_FIRST_TESTING.md` | come scriviamo i test di prodotto |
| 5 | `docs/CHART_CONFIG_CONTRACT.md` | 43 chart types + payload |
| 6 | `DEVELOPMENT_TEAM_HANDOFF.md` | handoff team frontend |
| 7 | `docs/ENGINE_ORCHESTRATION_AUDIT.md` | audit orchestrazione motori |
| 8 | `docs/PRODUCTION_READINESS_ASSESSMENT.md` | stato hardening / release |

## Comandi di sviluppo

```bash
make test              # smoke veloce
make test-all          # suite completa (~2275 test)
make hardening-test    # robustezza parser/API
make check             # lint + mypy + test-all + hardening (release gate)
make openapi-frontend  # rigenera openapi.json + TS client
```

Dopo modifiche a router o schemi:

```bash
make openapi-frontend
git add openapi/openapi.json frontend/src/api/generated/schema.ts
```

## Superficie API (tag principali)

| Tag | Path | Esempi |
|-----|-----:|--------|
| ride | 33 | `/ride/full-bundle`, `/ride/summary`, `/ride/analytics/*` |
| coach | 20 | `/coach/daily-brief`, `/coach/session-decision` |
| profile | 19 | `/profile/snapshot`, `/profile/metabolic/curves` |
| workouts | 9 | `/workouts/validate`, `/workouts/export` |
| meta | 3 | `/meta/chart-types`, `/meta/chart-config` |

Lista completa: `docs/API_ENDPOINT_INDEX.md`.

## Principi non negoziabili (UI e API)

Ogni numero mostrato al coach deve indicare se è:

1. misurato direttamente (potenza/HR da FIT)
2. calcolato con formula standard (NP, TSS)
3. stimato da modello fisiologico (VO₂max da MMP)
4. corretto da test validati (Mader, lactato)
5. non affidabile o assente (`status: skipped`, `null`, `warnings`)

Non mostrare mai un valore `null` o `skipped` come se fosse certo.

## TwinState — modello di persistenza

Il frontend/DB deve salvare e reinviare:

- `twin_state` (`twin_state.v1`)
- `metabolic_snapshot` / curve metaboliche
- `anchor` atleta
- `calibration_model` squadra
- `ValidationEvent` per ogni test confermato
- `model_version` associata alle predizioni

Vedi `docs/METABOLIC_CURVES_TWIN_CONTRACT.md` e `docs/FRONTEND_DEVELOPER_GUIDE.md`.

## Test: contract-first

I test di contratto dichiarano cosa **deve** vedere il prodotto. Un fallimento è un bug reale.

```bash
pytest tests/pytest_engines_contract_all.py tests/pytest_contract_full_codebase.py -q
pytest tests/pytest_chart_output_quality.py -q      # 43 chart types
pytest tests/pytest_product_output_quality.py -q  # 135 API paths
```

Metodologia completa: `docs/CONTRACT_FIRST_TESTING.md`.

## Prima PR — checklist

1. Modifica mirata (router/service/engine) con test.
2. `make test` verde in locale.
3. Se tocchi API: `make openapi-frontend` e committa il contratto.
4. Aggiorna `docs/API_ENDPOINT_INDEX.md` se aggiungi path.
5. `make check` prima del merge su `main`.

## Policy release

- Bug fix e nuove API → test + `make check`
- Non committare artefatti locali (`.venv`, `htmlcov/`, `data/`)
- Branch `main` = backend corrente **5.2.6**

## Contatti e risorse

- Contratto HTTP: `openapi/openapi.json`
- Client TypeScript: `frontend/src/api/client.ts`
- Troubleshooting: `docs/TROUBLESHOOTING.md`
- Deploy: `docs/DEPLOY_BACKEND.md`

---

*Onboarding V5.2.6 — 135 OpenAPI paths, 43 chart types. Per domande architetturali partire da `docs/ARCHITECTURE.md`.*
