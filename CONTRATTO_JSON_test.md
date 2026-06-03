# Contratto JSON — App tablet ↔ Backend test

Questo documento definisce **esattamente** cosa l'app manda al backend per ogni
tipo di test, e cosa il backend restituisce. È il riferimento per costruire
l'app: se l'app rispetta questo contratto, `test_protocols.py` la capisce.

Tutti i test condividono una **busta comune** (envelope) e differiscono solo
nel blocco `test_data`.

---

## Busta comune (uguale per tutti i test)

```json
{
  "test_type": "mader | incrementale | curva_pc | critical_power | wingate",
  "timestamp": "2026-06-03T10:30:00",
  "athlete": {
    "id": "uuid-da-supabase | null",
    "type": "registered | guest",
    "name": "Lorenzo",
    "surname": "Rossi",
    "dob": "1995-04-12",
    "weight_kg": 72.0,
    "height_cm": 178.0,
    "sex": "M | F",
    "hr_max": 192
  },
  "device": {
    "trainer": "Wahoo Kickr | Tacx Neo | ...",
    "power_source": "trainer | power_meter",
    "control_mode": "erg | manual"
  },
  "test_data": { ... }      // dipende da test_type, vedi sotto
}
```

**Note sull'atleta:**
- `type: registered` → `id` è l'uuid Supabase; gli altri campi arrivano dal db.
- `type: guest` → `id` è `null`; i campi sono inseriti a mano dal coach.

---

## 1. Mader (test del lattato) — il più importante

L'app raccoglie gli step con lattato misurato a fine di ognuno. Serve anche la
**MMP dell'atleta** (presa dallo storico o da uno sforzo), perché il backend
confronta il lattato reale con la predizione del modello non invasivo.

### L'app manda:

```json
"test_data": {
  "steps": [
    {"step": 1, "power_w": 150, "lactate_mmol": 1.2, "hr_mean": 120, "cadence_mean": 88, "duration_s": 300},
    {"step": 2, "power_w": 200, "lactate_mmol": 1.8, "hr_mean": 138, "cadence_mean": 90, "duration_s": 300},
    {"step": 3, "power_w": 230, "lactate_mmol": 2.6, "hr_mean": 150, "cadence_mean": 89, "duration_s": 300},
    {"step": 4, "power_w": 260, "lactate_mmol": 4.1, "hr_mean": 162, "cadence_mean": 91, "duration_s": 300},
    {"step": 5, "power_w": 290, "lactate_mmol": 6.8, "hr_mean": 171, "cadence_mean": 90, "duration_s": 300},
    {"step": 6, "power_w": 320, "lactate_mmol": 10.2, "hr_mean": 178, "cadence_mean": 92, "duration_s": 300}
  ],
  "mmp": {"15": 980, "60": 540, "300": 340, "720": 300, "1200": 285, "3600": 255}
}
```

**Requisito:** almeno **5 step** (vincolo del D-max). Con meno, il backend
rifiuta e spiega perché.

### Il backend restituisce:

```json
{
  "status": "success",
  "validated": true,
  "verdict": "Modello VALIDATO per questo atleta...",
  "mlss_true_watts": 260.0,
  "mlss_model_watts": 258.0,
  "error_watts": -2.0,
  "error_pct": -0.8,
  "lactate_thresholds": {
    "mlss_dmax_watts": 260.0,
    "obla_4mmol_watts": 258.0,
    "aerobic_2mmol_watts": 207.5
  },
  "model_snapshot": { ... }      // profilo completo dal MetabolicProfiler
}
```

---

## 2. Incrementale

Step a potenza crescente. Niente lattato. Serve a stimare la soglia dalla
risposta FC/potenza e a costruire la MMP per gli altri calcoli.

### L'app manda:

```json
"test_data": {
  "config": {"w_start": 200, "w_increment": 10, "step1_duration_s": 180, "step_duration_s": 60},
  "steps": [
    {"step": 1, "power_w": 200, "hr_mean": 130, "cadence_mean": 90, "duration_s": 180},
    {"step": 2, "power_w": 210, "hr_mean": 138, "cadence_mean": 91, "duration_s": 60}
    // ... fino all'esaurimento
  ]
}
```

### Il backend restituisce:

```json
{
  "status": "success",
  "max_power_w": 380,
  "hr_max_observed": 189,
  "steps_completed": 19,
  "vo2max_estimate": null,        // valorizzato se la MMP lo consente
  "notes": "..."
}
```

---

## 3. Curva Potenza/Cadenza

4-5 sprint massimali a RPM diverse. Misura la potenza di picco per cadenza.

### L'app manda:

```json
"test_data": {
  "points": [
    {"point": 1, "rpm_target": 80,  "rpm_peak": 82,  "w_peak": 820, "duration_s": 40},
    {"point": 2, "rpm_target": 100, "rpm_peak": 101, "w_peak": 910, "duration_s": 40},
    {"point": 3, "rpm_target": 120, "rpm_peak": 119, "w_peak": 870, "duration_s": 40},
    {"point": 4, "rpm_target": 140, "rpm_peak": 138, "w_peak": 760, "duration_s": 40}
  ]
}
```

### Il backend restituisce:

```json
{
  "status": "success",
  "optimal_cadence_rpm": 105,
  "peak_power_w": 910,
  "curve": [{"rpm": 82, "watts": 820}, ...]
}
```

---

## 4. Critical Power

Una o più prove massimali nella finestra **2-15 minuti**. Stima CP e W'.
Usa il fit già esistente nel backend (`power_engine.fit_critical_power`).

### L'app manda:

```json
"test_data": {
  "efforts": [
    {"duration_s": 180, "power_w": 360},
    {"duration_s": 300, "power_w": 330},
    {"duration_s": 720, "power_w": 295}
  ]
}
```

**Requisito:** almeno **3 prove** nella finestra 120-900s.

### Il backend restituisce:

```json
{
  "status": "success",
  "cp_w": 285.0,
  "wprime_kj": 18.5,
  "r_squared": 0.998,
  "n_points": 3
}
```

---

## 5. Wingate

Sprint massimale cronometrato (classico 30s). Misura picco, media, minimo e
indice di affaticamento.

### L'app manda:

```json
"test_data": {
  "duration_s": 30,
  "power_stream": [980, 960, 940, ...],   // un valore al secondo
  "body_weight_kg": 72.0
}
```

### Il backend restituisce:

```json
{
  "status": "success",
  "peak_power_w": 980,
  "peak_power_wkg": 13.6,
  "mean_power_w": 720,
  "min_power_w": 480,
  "fatigue_index_pct": 51.0
}
```

---

## Output: campi comuni a tutte le risposte

Ogni risposta porta anche, in coda, i campi del contratto del backend
(aggiunti automaticamente da `annotate_payload`):

```json
{
  "api_contract": { "tier": "...", "confidence": {...} },
  "tier": "REFERENCE | MODEL | ...",
  "uncertainty": { ... }
}
```
