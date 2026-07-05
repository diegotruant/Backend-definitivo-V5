# CI Cost Control Plan — Digital Twin Backend V5.2.6

**Repository:** `diegotruant/Backend-definitivo-V5`  
**Versione backend:** 5.2.6  
**Audience:** maintainers, agenti Cloud, contributor  
**Stato:** policy documentale — **nessun workflow modificato in questa revisione**

---

## 1. Scopo

Questo documento definisce una **strategia di governance CI** per il backend Digital Twin, da applicare **prima** di modificare i workflow GitHub Actions.

### Obiettivi

| Obiettivo | Dettaglio |
|-----------|-----------|
| Ridurre costi GitHub Actions | Meno minuti macchina su push draft e iterazioni frequenti |
| Ridurre rumore su PR draft | Feedback rapido senza log da 2000+ test a ogni commit |
| Evitare full-check inutili | `make check` solo quando serve una release gate |
| Proteggere `main` | Gate completo obbligatorio prima del merge |
| Mantenere qualità | Nessun abbassamento coverage, hardening o test suite |
| Favorire micro PR | Un obiettivo, pochi file, ciclo review prevedibile |

**Questa PR documenta solo la strategia.** L'implementazione avviene in PR dedicate (§15).

---

## 2. Problema attuale

Il backend ha una suite ampia (~2200+ test) e workflow GitHub Actions pesanti. Situazione osservata:

| Problema | Effetto |
|----------|---------|
| Ogni push su PR fa partire workflow pesanti | `ci.yml` esegue `make lint` + **`make test-all`** su ogni branch/PR |
| PR grandi con commit frequenti | Molte run Actions per lo stesso obiettivo |
| Full backend check costoso | `full-check.yml` esegue `make check` (lint, typecheck, test-all, hardening, lockdown, integrity, api-matrix, perfection, golden, coverage) |
| Coverage / hardening / golden importanti | Ma **non sempre necessari** su ogni commit draft di documentazione o micro-fix |
| Mancanza di livelli distinti | Controlli leggeri e release gate non separati chiaramente in policy |

### Workflow attuali (riferimento, non da modificare qui)

| File | Trigger attuale | Contenuto tipico |
|------|-----------------|------------------|
| `.github/workflows/ci.yml` | `push` su tutti i branch, ogni `pull_request` | `make lint` + `make test-all` |
| `.github/workflows/full-check.yml` | PR/push su `main`, schedule settimanale, `workflow_dispatch` | `make check` |
| `.github/workflows/hardening.yml` | (hardening dedicato) | Suite hardening |
| `.github/workflows/multitenant-stress.yml` | (stress) | Stress multi-tenant |

**Sintomo:** PR documentali o draft con 5 push possono consumare 5× `test-all` + eventuali full-check senza valore proporzionale.

**Soluzione proposta:** separare esplicitamente controlli **leggeri** (draft / fast) da controlli **release** (ready / main / manual).

---

## 3. Principio guida

Usare questo principio operativo:

```text
Draft PR     = controlli leggeri
Ready PR     = controlli completi
main         = controlli completi
manual       = controlli pesanti opzionali
```

| Stato | Cosa ci si aspetta |
|-------|-------------------|
| **Draft PR** | Lint + smoke / test mirati — feedback in pochi minuti |
| **Ready for review** | Release gate (`make check` o equivalente) |
| **Push su `main`** | Release gate completo — `main` sempre protetto |
| **Manual / schedule** | Stress, golden completa, matrix pesante, diagnostica |

Nessun merge su `main` senza **almeno una** release gate verde (§14).

---

## 4. Livelli CI proposti

Quattro livelli distinti. Solo LEVEL 1 è obbligatorio prima di ogni push; LEVEL 2–4 sono responsabilità CI/remota secondo policy §5–6.

### LEVEL 1 — Local developer check

Eseguito **localmente** dal developer/agent prima del push.

**Comandi consigliati (default):**

```bash
python3 -m ruff check engines api api_app.py tests scripts
python3 -m pytest -q tests/pytest_*.py pytest_script_suite.py --tb=short
```

**Se il cambio riguarda OpenAPI:**

```bash
python3 scripts/export_openapi.py
```

**Se il cambio riguarda typing:**

```bash
python3 -m mypy --explicit-package-bases api api_app.py
```

**Se il cambio è docs-only:**

```bash
git diff --check
```

---

### LEVEL 2 — PR fast check

Da eseguire su **ogni** PR/push, ma deve restare **leggero** (target futuro: `ci-fast.yml`).

| Controllo | Incluso |
|-----------|---------|
| Lint | ✅ `make lint` |
| Test mirati / smoke | ✅ `make test` (smoke) o subset per path |
| Formato | ✅ se configurato |
| Coverage pesante | ❌ |
| Hardening pesante | ❌ |
| Full matrix | ❌ |

**Possibile comando CI:**

```bash
make lint
make test
```

**Durata target:** pochi minuti, non decine.

---

### LEVEL 3 — Release candidate check

Da eseguire solo quando:

- la PR passa da **draft → ready for review**, oppure
- `workflow_dispatch` esplicito, oppure
- push su **`main`**

| Controllo | Comando Makefile |
|-----------|------------------|
| Lint + typecheck + full test | `make check` (include tutto sotto) |
| Test completi | `make test-all` |
| Hardening | `make hardening-test` |
| Lockdown + integrity | `make lockdown-test`, `make integrity-test` |
| API matrix | `make api-matrix-test` |
| Perfection + golden | `make perfection-test`, `make golden-test` |
| Coverage baseline | `make coverage-test` |
| OpenAPI consistency | `make openapi` (parte di `test-all`) |

**Comando unico:**

```bash
make check
```

Allineato a `.github/workflows/full-check.yml` attuale.

---

### LEVEL 4 — Scheduled / manual deep check

Da eseguire **manualmente** o su **schedule** (settimanale / pre-release).

| Controllo | Esempio |
|-----------|---------|
| Stress test | `make stress-test`, `make multitenant-stress` |
| Full hardening | marker `hardening and stress` |
| Golden FIT regression completa | `make golden-test` + suite estesa |
| Matrix pesante | `make api-matrix-test` in configurazione ampia |
| Coverage completa + artifact | report HTML, log diagnostici |
| Engine lockdown diagnostic | log come in `full-check.yml` oggi |

Non bloccare ogni PR draft; usare per audit, release major, o debug sistemico.

---

## 5. Policy per PR draft

Le PR **draft** devono:

| Regola | Dettaglio |
|--------|-----------|
| Essere piccole | Un obiettivo chiaro; spezzare se cresce |
| Titolo chiaro | Es. `docs: define CI cost control plan` |
| Non pretendere full check ogni push | Solo LEVEL 2 (fast) in CI futuro |
| Dichiarare scope in descrizione | `runtime` \| `docs` \| `tests` \| `OpenAPI` \| `workflow` |
| Passare LEVEL 1 locale | Prima di ogni push |

**Etichetta suggerita in descrizione PR:**

```text
Scope: docs-only | CI: fast check only
```

---

## 6. Policy per PR ready

Una PR può passare da **draft → ready for review** solo quando:

- [ ] È piccola e leggibile (review in < 30 min idealmente)
- [ ] Ha passato i controlli **locali** LEVEL 1 (o `make check` se runtime)
- [ ] Ha descrizione chiara: scopo, file toccati, rischio
- [ ] Non contiene file temporanei, log, artifact, `.pyc`, dump
- [ ] Se modifica API/router → OpenAPI aggiornato (`make openapi` / `scripts/export_openapi.py`)
- [ ] Se modifica backend stable → test di contratto aggiunti o aggiornati
- [ ] Release gate LEVEL 3 pianificato o in corso (ready trigger)

**Ready = richiesta di review seria**, non solo cambio stato GitHub.

---

## 7. Policy per micro PR

Ogni micro PR deve idealmente avere:

| Criterio | Dettaglio |
|----------|-----------|
| 1 obiettivo | Una frase nel titolo |
| Pochi file | Preferire < 10 file non-docs |
| Nessun refactor laterale | Refactor = PR separata |
| Nessun cambio workflow | Salvo PR dedicata `ci: …` |
| Nessun motore nuovo | Se l'obiettivo è stabilizzazione/docs |

### Esempi titolo validi

```text
docs: define stable backend surface
docs: define frontend API facade
docs: define Supabase handoff
docs: define CI cost control plan
test: lock ability profile W/kg contract
fix: handle missing HR stream in ride summary
```

### Esempi da evitare

```text
fix: various things + docs + workflow tweak
refactor: engines while fixing tests
feat: new engine + OpenAPI + frontend + CI
```

---

## 8. Policy per docs-only PR

Le PR **solo documentali** (`docs/**`, nessun `.py`, nessun workflow):

| Regola | Dettaglio |
|--------|-----------|
| No full backend check pesante | Non serve `make check` in CI |
| Lint opzionale | Markdown link check / `git diff --check` se presente |
| No coverage | — |
| No OpenAPI export | — |
| No risorse CI inutili | Path filter futuro: skip `test-all` se solo `docs/` |

**LEVEL 1 locale minimo:**

```bash
git diff --check
```

**Merge su `main`:** almeno fast check verde; release gate completo può essere soddisfatto dal gate su `main` post-merge se policy team lo consente — preferibile comunque fast + review umana per docs critiche (contratti API, handoff).

---

## 9. Policy per workflow changes

Ogni modifica a `.github/workflows/**` deve essere:

| Regola | Dettaglio |
|--------|-----------|
| PR dedicata | Titolo `ci: …` — mai mescolata con motori |
| Piccola | Un workflow o un comportamento per PR |
| Spiegata | Descrizione: trigger, cosa si risparmia, cosa si protegge |
| Verificata con prudenza | Test su branch fork o `workflow_dispatch` prima del merge |
| Mai con codice fisiologico | Split obbligatorio |

**Ordine consigliato:** prima questo documento (PR A), poi split fast/release (PR B).

---

## 10. Strategia proposta per GitHub Actions futura

Descrizione **solo documentale** — **non implementata** in questa PR.

### Workflow 1 — `ci-fast.yml`

| Campo | Valore |
|-------|--------|
| **Trigger** | `pull_request`, `push` su branch (escluso `main` opzionale) |
| **Controlli** | `make lint`, `make test` (smoke) |
| **Ottimizzazione** | Path filter: se solo `docs/**` → skip test, solo `git diff --check` o markdown lint |
| **Durata** | Target < 5 min |

### Workflow 2 — `release-check.yml`

| Campo | Valore |
|-------|--------|
| **Trigger** | `pull_request` → `ready_for_review`, `workflow_dispatch`, `push` su `main` |
| **Controlli** | `make check` |
| **Artifact** | Log release gate (come `full-check.yml` oggi) |
| **Durata** | Accettabile (20–45 min) — ma **non** su ogni push draft |

### Workflow 3 — `deep-check.yml`

| Campo | Valore |
|-------|--------|
| **Trigger** | `workflow_dispatch`, `schedule` settimanale (es. domenica 03:00 UTC) |
| **Controlli** | `make stress-test`, `make multitenant-stress`, golden estesa, diagnostica lockdown |
| **Artifact** | Log, coverage HTML, report stress |
| **Blocco merge** | No — informativo / pre-release |

### Migrazione dal presente

| Oggi | Futuro proposto |
|------|-----------------|
| `ci.yml` = lint + test-all su ogni push | `ci-fast.yml` = lint + smoke |
| `full-check.yml` su ogni PR main | `release-check.yml` su ready + main |
| hardening/multitenant separati | consolidati in `deep-check.yml` dove possibile |

---

## 11. Regole anti-costo

Regole operative per maintainer e agenti:

| # | Regola |
|---|--------|
| 1 | **Non** fare push correttivi uno alla volta senza test locale LEVEL 1 |
| 2 | **Non** rilanciare workflow senza aver letto il fallimento |
| 3 | **Non** usare `re-run all jobs` come strategia di debug |
| 4 | Leggere sempre log / artifact prima di correggere |
| 5 | Se una PR diventa troppo grande → chiuderla e spezzarla |
| 6 | Se una PR è docs-only → non deve consumare full release gate a ogni push |
| 7 | Usare **micro PR da `main`** — branch corti, pochi commit |
| 8 | Evitare branch lunghi con decine di commit e rebase continui |
| 9 | Accumulare fix locali → **un push** dopo LEVEL 1 verde |
| 10 | Preferire `workflow_dispatch` per deep check esplorativo |

---

## 12. Comandi locali consigliati prima del push

### Docs-only

```bash
git diff --check
# opzionale: verifica link markdown
```

### Test-only

```bash
python3 -m pytest -q path/del/test.py --tb=short
python3 -m ruff check tests
```

### Runtime backend (engines, api, services)

```bash
python3 -m ruff check engines api api_app.py tests scripts
python3 -m pytest -q tests/pytest_*.py pytest_script_suite.py --tb=short
```

### API / router / schema

```bash
python3 scripts/export_openapi.py
python3 -m pytest -q tests/pytest_openapi*.py tests/pytest_engine_api_coverage.py --tb=short
```

### Release candidate (prima di ready / merge)

```bash
make check
```

### Smoke rapido (equivalente LEVEL 2)

```bash
make lint
make test
```

---

## 13. Definition of Done CI policy

La policy CI è **pronta per implementazione** quando:

- [ ] Distingue **draft** e **ready** con controlli diversi
- [ ] Distingue **docs-only** e **runtime**
- [ ] Mantiene **`main` protetto** con release gate completo
- [ ] Riduce run pesanti inutili su iterazioni draft
- [ ] **Non** abbassa qualità (stessi test in release gate)
- [ ] **Non** abbassa coverage baseline
- [ ] **Non** elimina test dalla suite — solo li **schedula** meglio
- [ ] **Non** nasconde failure (artifact e log obbligatori su gate fallito)
- [ ] Permette **una release gate completa** prima del merge su `main`

Questo documento soddisfa la definizione policy; l'implementazione workflow è DoD separato (§15).

---

## 14. Cosa NON fare

| Vietato | Motivo |
|---------|--------|
| Disabilitare completamente CI su `main` | Rischio regressioni silenti |
| Abbassare coverage baseline per comodità | Perdita qualità misurabile |
| Rimuovere hardening dalla release gate | Sicurezza e robustezza |
| Eliminare test lenti senza alternativa in deep check | Copertura falsata |
| Modificare workflow insieme a codice fisiologico | Review impossibile, rollback difficile |
| Usare `[skip ci]` sui commit finali da mergiare | Bypass gate |
| Mergiare PR senza almeno una **release gate completa** verde | `main` non protetto |
| Sostituire `make check` con solo smoke su `main` | Gate insufficiente |

---

## 15. Roadmap di implementazione futura

**Non implementare in questa PR.** Sequenza consigliata:

| PR | Titolo | Contenuto |
|----|--------|-----------|
| **A** | `docs: define CI cost control plan` | Questo documento — policy only |
| **B** | `ci: split fast PR check from release gate` | `ci-fast.yml` + trigger `ready_for_review` su release |
| **C** | `ci: add docs-only lightweight path` | Path filter `docs/**` → skip test-all |
| **D** | `ci: make deep backend check manual/scheduled` | `deep-check.yml`; alleggerire `ci.yml` legacy |
| **E** | `test: mark slow/golden/stress suites explicitly` | Marker pytest per subset LEVEL 2 vs 4 |

### Criteri di successo post-implementazione

- Push su draft docs-only: < 3 min CI
- Ready PR runtime: `make check` verde obbligatorio
- `main`: sempre `make check` su push
- Costo Actions mensile misurabile in calo senza regressioni su `main`

---

## Documenti correlati

| Documento | Contenuto |
|-----------|-----------|
| `Makefile` | Target `lint`, `test`, `test-all`, `check` |
| `.github/workflows/ci.yml` | CI attuale (lint + test-all) |
| `.github/workflows/full-check.yml` | Release gate attuale (`make check`) |
| `docs/DEVELOPER_ONBOARDING.md` | Onboarding e comandi make |

---

## Changelog

| Date | Version | Change |
|------|---------|--------|
| 2026-07-05 | 1.0.0 | Initial CI cost control plan for V5.2.6 |

---

*Documento di governance CI — nessuna modifica a runtime backend, workflow, OpenAPI, frontend, test, Makefile o README in questa revisione.*
