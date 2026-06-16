# JSON Contract — Tablet App ↔ Test Backend

This document defines **exactly** what the app sends to the backend for each
test type, and what the backend returns. It is the reference for building
the app: if the app follows this contract, `test_protocols.py` will understand it.

All tests share a **common envelope** and differ only
in the `test_data` block.

---

## Common envelope (same for all tests)

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
    "trainer": "smart trainer | indoor trainer | ...",
    "power_source": "trainer | power_meter",
    "control_mode": "erg | manual"
  },
  "test_data": { ... }      // depends on test_type, see below
}
```

**Athlete notes:**
- `type: registered` → `id` is the Supabase UUID; the other fields come from the database.
- `type: guest` → `id` is `null`; the fields are entered manually by the coach.

---

## 1. Mader (lactate test) — the most important

The app collects the steps with measured lactate at the end of each one. It also needs the
**athlete's MMP** (from history or from an effort), because the backend
compares the actual lactate with the prediction from the non-invasive model.

### The app sends:

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

**Requirement:** at least **5 steps** (D-max constraint). With fewer, the backend
rejects the payload and explains why.

### The backend returns:

```json
{
  "status": "success",
  "validated": true,
  "verdict": "Model VALIDATED for this athlete...",
  "mlss_true_watts": 260.0,
  "mlss_model_watts": 258.0,
  "error_watts": -2.0,
  "error_pct": -0.8,
  "lactate_thresholds": {
    "mlss_dmax_watts": 260.0,
    "obla_4mmol_watts": 258.0,
    "aerobic_2mmol_watts": 207.5
  },
  "model_snapshot": { ... }      // complete profile from MetabolicProfiler
}
```

---

## 2. Incremental

Steps with increasing power. No lactate. Used to estimate the threshold from
HR/power response and to build the MMP for the other calculations.

### The app sends:

```json
"test_data": {
  "config": {"w_start": 200, "w_increment": 10, "step1_duration_s": 180, "step_duration_s": 60},
  "steps": [
    {"step": 1, "power_w": 200, "hr_mean": 130, "cadence_mean": 90, "duration_s": 180},
    {"step": 2, "power_w": 210, "hr_mean": 138, "cadence_mean": 91, "duration_s": 60}
    // ... until exhaustion
  ]
}
```

### The backend returns:

```json
{
  "status": "success",
  "max_power_w": 380,
  "hr_max_observed": 189,
  "steps_completed": 19,
  "vo2max_estimate": null,        // populated if the MMP allows it
  "notes": "..."
}
```

---

## 3. Power/Cadence Curve

4-5 maximal sprints at different RPMs. Measures peak power for each cadence.

### The app sends:

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

### The backend returns:

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

One or more maximal efforts within the **2–15 minute** window. Estimates CP and W'.
Uses the fit already implemented in the backend (`power_engine.fit_critical_power`).

### The app sends:

```json
"test_data": {
  "efforts": [
    {"duration_s": 180, "power_w": 360},
    {"duration_s": 300, "power_w": 330},
    {"duration_s": 720, "power_w": 295}
  ]
}
```

**Requirement:** at least **3 efforts** within the 120–900s window.

### The backend returns:

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

Timed maximal sprint (classic 30s). Measures peak, mean, minimum, and
fatigue index.

### The app sends:

```json
"test_data": {
  "duration_s": 30,
  "power_stream": [980, 960, 940, ...],   // one value per second
  "body_weight_kg": 72.0
}
```

### The backend returns:

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

## Output: fields common to all responses

Each response also includes, at the end, the backend contract fields
(automatically added by `annotate_payload`):

```json
{
  "api_contract": { "tier": "...", "confidence": {...} },
  "tier": "REFERENCE | MODEL | ...",
  "uncertainty": { ... }
}
```
