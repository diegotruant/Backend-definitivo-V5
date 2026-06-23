# Demo coach World Tour — 5 minuti

Script presentazione + comando live per mostrare il **wow factor** del backend:
validazione Mader al lattato + Team Learning con audit.

## Comando

```bash
make install   # solo la prima volta
python3 tools/demo/wt_coach_demo.py
```

Opzioni:

| Flag | Uso |
|------|-----|
| `--no-pause` | Nessuna pausa tra gli atti (replay veloce, CI) |
| `--json` | Output JSON machine-readable |

## Cast

| Personaggio | Ruolo |
|-------------|-------|
| **Marco Rossi** | Nuovo ingaggio, grimpeur 62 kg — protagonista Atti 1-2 |
| **Luca B., Tom H., Jonas V.** | Tre colleghi già testati in settimana — Atto 3 |
| **Paolo C.** | Neo-pro 58 kg senza lattato — Atto 4 |

## Timeline (5 minuti)

### Atto 1 — Profilo da MMP (~1 min)

**Cosa mostra:** `MetabolicProfiler` → stima MLSS/VO2max/VLamax da curva MMP espressiva.

**Cosa dire:**

> «Marco è appena arrivato. Dal suo storico potenze abbiamo una curva MMP completa — sprint, glicolitico, VO2max, soglia. Il modello Mader stima la MLSS a ~265 W. Ma prima di fidarmi del monitoraggio solo da potenza, voglio validare con il lattato.»

**Badge UI da menzionare:** `Model estimate`, `fully_expressive: true`

---

### Atto 2 — Test Mader (~1.5 min)

**Cosa mostra:** `POST /test/in-person` → D-max (ground truth) vs MLSS predetta → verdetto.

**Cosa dire:**

> «Sei step al lattato in sala. Il backend calcola la MLSS vera con D-max — indipendente dal modello — e la confronta con la predizione da MMP. Tolleranza ±8%.»

**Momento WOW:** banner verde `MODEL VALIDATED` + verdetto testuale.

> «Per Marco posso passare al monitoraggio non invasivo. Il sistema non dice "fidati ciecamente" — dice "validato entro 8%, procedi".»

**Se validated = false:** usare come teachable moment su MMP/calibrazione — nel demo preconfigurato è `true`.

---

### Atto 3 — Memoria di squadra (~1 min)

**Cosa mostra:** 3 `ValidationEvent` — predizione **prima** del test vs valore misurato.

**Cosa dire:**

> «Nella stessa settimana di test, tre grimpeurs hanno già fatto Mader. Il modello sovrastima sistematicamente di ~15 W. Non è un bug di un atleta — è un bias di cohort. Lo registriamo con audit.»

**Numeri attesi:** bias team ≈ -15 W, MAE ≈ 15 W.

---

### Atto 4 — Neo-pro calibrato (~1 min)

**Cosa mostra:** `POST /team/calibration/apply` su Paolo (senza lattato).

**Cosa dire:**

> «Arriva Paolo, nessun test al lattato ancora. Il modello direbbe 300 W. Ma la squadra ha già imparato: correggiamo di ~14 W con cap e audit. La stima è più conservativa — e tracciata. Dopo il test di Paolo, il ciclo ricomincia.»

**Momento WOW:** confronto `MLSS grezza` vs `MLSS calibrata` + breakdown `[team] bias -15 W`.

---

### Chiusura (~30 sec)

**Frase chiave:**

> «Non è un'AI che stima l'FTP. È un motore Mader che si valida col lattato, ammette quando non è affidabile, e impara gli errori del TUO team — con audit.»

**Endpoint da ricordare:**

- `POST /profile/snapshot`
- `POST /test/in-person`
- `POST /team/calibration/update`
- `POST /team/calibration/apply`

---

## Demo HTTP live (opzionale)

Se hai il server avviato (`make run`), puoi replicare l'Atto 2 con curl:

```bash
curl -s -X POST http://127.0.0.1:8000/test/in-person \
  -H 'Content-Type: application/json' \
  -d '{
    "test_type": "mader",
    "athlete": {"weight_kg": 62, "sex": "M", "discipline": "CLIMB"},
    "test_data": {
      "steps": [
        {"step": 1, "power_w": 180, "lactate_mmol": 1.1},
        {"step": 2, "power_w": 210, "lactate_mmol": 1.5},
        {"step": 3, "power_w": 240, "lactate_mmol": 2.2},
        {"step": 4, "power_w": 265, "lactate_mmol": 3.8},
        {"step": 5, "power_w": 285, "lactate_mmol": 5.9},
        {"step": 6, "power_w": 305, "lactate_mmol": 9.1}
      ],
      "mmp": {"5": 850, "60": 400, "300": 285, "720": 275, "1200": 278, "3600": 262}
    }
  }' | python3 -m json.tool
```

---

## Note tecniche per il presentatore

- Il demo usa `CorrectionConfig(min_team_events=3)` per attivare la calibrazione team con 3 colleghi. In produzione il default è **5 eventi**.
- I numeri sono deterministici: stesso input → stesso output.
- `--json` utile per integrare la demo in slide o recording automatico.

## Troubleshooting

| Problema | Soluzione |
|----------|-----------|
| `ModuleNotFoundError: scipy` | `make install` |
| Output senza colori | Normale se non è un TTY; usare terminale interattivo |
| `validated: false` | MMP/lattato non allineati — usa i payload del demo script |
