# FIT parser policy

## Decisione

Il backend usa **fitdecode** come parser FIT canonico e ufficiale.

Il flusso supportato è:

```text
FIT payload
→ fitdecode
→ normalizzazione interna
→ ActivityStreamEnhanced
→ quality report / effort extraction / MMP / profilo metabolico
```

## Ruolo di fitparse

`fitparse` rimane temporaneamente installato esclusivamente come fallback legacy per file che `fitdecode` non riesce ancora a leggere o recuperare.

Non è un secondo parser equivalente e non deve essere usato come backend principale. Nuove funzionalità, nuovi campi FIT e nuovi test devono essere implementati e validati prima su `fitdecode`.

## Flag interni di disponibilità

I flag hanno significati distinti e non intercambiabili:

- `FITDECODE_AVAILABLE`: il parser canonico `fitdecode` è installato;
- `FITPARSE_FALLBACK_AVAILABLE`: il fallback legacy `fitparse` è realmente installato;
- `FIT_PARSER_AVAILABLE`: almeno un decoder FIT è disponibile;
- `FIT_BACKEND_AVAILABLE`: alias retrocompatibile di `FIT_PARSER_AVAILABLE`;
- `FITPARSE_AVAILABLE`: disponibilità reale della sola libreria `fitparse`.

Il core deve usare `FITPARSE_FALLBACK_AVAILABLE` per decidere se tentare il fallback e `FIT_PARSER_AVAILABLE` per verificare la disponibilità generale del parsing.

## Contratto esterno

La scelta del decoder è un dettaglio interno. Non deve modificare:

- endpoint HTTP;
- codici di stato;
- schema JSON;
- OpenAPI;
- client TypeScript;
- struttura Supabase.

Gli errori delle librerie FIT devono essere convertiti nei codici dominio stabili già previsti da `FitFileError`:

- `EMPTY_FILE`;
- `INVALID_HEADER`;
- `TRUNCATED`;
- `CRC_MISMATCH`;
- `MALFORMED_RECORDS`;
- `NO_RECORDS`;
- `UNKNOWN`.

## Criteri per rimuovere fitparse

Il fallback potrà essere eliminato soltanto dopo che `fitdecode` avrà superato tutti i seguenti controlli:

1. corpus versionato di FIT reali provenienti da più dispositivi e piattaforme;
2. parità sui record principali, sessioni, lap, device info, HRV e developer fields;
3. test su file vuoti, header non validi, CRC errati e file troncati;
4. assenza di regressioni nella suite completa, hardening, matrice API e golden tests;
5. benchmark documentato su tempo di parsing e memoria;
6. periodo di osservazione in produzione senza fallback necessario.

## Go

Non è previsto un parser FIT Go nel percorso ufficiale. Un eventuale componente Go potrà essere valutato solo come implementazione sostituibile dietro lo stesso contratto canonico e soltanto se benchmark reali dimostreranno un limite non risolvibile con worker Python e coda di elaborazione.

## Regola anti-drift

`tests/pytest_fit_parser_policy.py` verifica che:

- `fitdecode` resti una dipendenza runtime;
- `fitdecode` venga chiamato prima del fallback `fitparse`;
- disponibilità generale e disponibilità del fallback restino separate;
- il fallback assente venga rifiutato prima di accedere alla libreria;
- `fitparse` sia descritto come fallback temporaneo;
- questa policy continui a indicare `fitdecode` come parser canonico.
