# Metabolic curves & lactate state — TwinState contract (frontend + DB)

This document defines how **profile-stable metabolic curves** and **measured lactate curves** are stored on `twin_state.v1`, so the coach frontend can render charts from Postgres without calling `POST /profile/metabolic/curves` on every page load.

Session-scoped curves (fuel demand, W′ balance, durability decay) remain on **activity** payloads — not on TwinState.

---

## TwinState fields

| Field | Schema | When populated | Frontend use |
|-------|--------|----------------|--------------|
| `metabolic_snapshot` | profiler output | Profile build / refresh | KPI cards (MLSS, VO₂, VLamax) |
| `metabolic_curves` | `metabolic_curves.v1` | Twin build, profile refresh, ride update with snapshot | Line/area charts (VO₂ demand, substrate) |
| `lactate_state` | `lactate_state.v1` | Mader / lab test with ≥3 steps | Lactate curve + D-max thresholds |

---

## `metabolic_curves.v1`

Top-level object persisted at `twin_states.twin_state.metabolic_curves`:

```json
{
  "status": "success",
  "schema_version": "metabolic_curves.v1",
  "measurement_tier": "MIXED",
  "confidence_score": 0.62,
  "available_curves": ["vo2_demand", "substrate_oxidation", "energy_contribution_by_duration"],
  "missing_curves": [],
  "curves": {
    "vo2_demand": { "...": "see curve object below" },
    "substrate_oxidation": { "...": "..." },
    "energy_contribution_by_duration": { "...": "..." },
    "lactate": { "...": "only after lab test" }
  },
  "db_contract": {
    "store_points": true,
    "store_model_parameters": true,
    "store_measurement_tier": true,
    "store_confidence_and_limitations": true
  }
}
```

### Profile curves (always synced when snapshot is ready)

| `curve_id` | Tier | X axis | Y series | Notes |
|------------|------|--------|----------|-------|
| `vo2_demand` | MODEL_ESTIMATE | `power_w` (W) | `pct_vo2max`, `vo2_ml_kg_min` | Anchors at FATmax, MLSS, MAP |
| `substrate_oxidation` | MODEL_ESTIMATE | `power_w` (W) | `fat_oxidation_g_min_est`, `carbohydrate_oxidation_g_min_est` | From `combustion_curve` in snapshot |
| `energy_contribution_by_duration` | MODEL_ESTIMATE | `duration_s` (s) | energy split by duration | Optional on Digital Twin |

### Single curve object (render contract)

```json
{
  "curve_id": "vo2_demand",
  "title": "VO2 demand (%VO2max vs watt)",
  "x_axis": { "key": "power_w", "unit": "W" },
  "y_axis": [
    { "key": "pct_vo2max", "unit": "%", "label": "% VO2max" },
    { "key": "vo2_ml_kg_min", "unit": "ml/kg/min", "label": "VO2 demand" }
  ],
  "measurement_tier": "MODEL_ESTIMATE",
  "points": [
    { "power_w": 120.0, "pct_vo2max": 42.1, "vo2_ml_kg_min": 24.4, "domain": "recovery" }
  ],
  "anchors": [
    { "label": "FATmax", "power_w": 185.0, "pct_vo2max": 58.2 }
  ],
  "confidence_score": 0.58,
  "limitations": ["Gross efficiency strongly affects VO2 demand estimates."],
  "frontend_hint": { "chart_type": "line", "show_anchors": true },
  "model_parameters": {
    "estimated_vo2max": 58.0,
    "weight_kg": 72.0,
    "eta_used": 0.23
  }
}
```

### Frontend rendering rules

1. Read `twin.metabolic_curves.curves[curve_id].points` — **do not recompute** physiology.
2. Show `measurement_tier` badge: `MODEL_ESTIMATE` → blue “Model”; `LAB_MEASURED` → green “Lab”.
3. If `curve_id` not in `available_curves`, show `missing_curves[].reason` in Data Quality panel.
4. Tooltip: join `limitations` strings from the curve object.

### Example: VO₂ demand chart (React + Recharts)

```typescript
const vo2 = twin.metabolic_curves?.curves?.vo2_demand;
if (!vo2?.points?.length) return <MissingCurve reason="vo2_demand" />;

<LineChart data={vo2.points}>
  <XAxis dataKey="power_w" unit="W" />
  <YAxis dataKey="pct_vo2max" unit="%" />
  <Line dataKey="pct_vo2max" />
  {vo2.anchors?.map(a => (
    <ReferenceDot key={a.label} x={a.power_w} y={a.pct_vo2max} label={a.label} />
  ))}
</LineChart>
```

---

## `lactate_state.v1`

Persisted at `twin_states.twin_state.lactate_state` after a Mader / incremental lactate test:

```json
{
  "schema_version": "lactate_state.v1",
  "measurement_tier": "LAB_MEASURED",
  "latest_curve": {
    "curve_id": "lactate",
    "measurement_tier": "LAB_MEASURED",
    "x_axis": { "key": "power_w", "unit": "W" },
    "y_axis": [{ "key": "lactate_mmol", "unit": "mmol/L", "label": "Lactate" }],
    "points": [
      { "power_w": 160, "lactate_mmol": 1.5, "hr_mean": 128 }
    ],
    "thresholds": {
      "mlss_dmax_watts": 268.0,
      "obla_4mmol_watts": 285.0,
      "aerobic_2mmol_watts": 195.0
    },
    "frontend_hint": { "chart_type": "line", "show_anchors": true }
  },
  "thresholds": {
    "mlss_dmax_watts": 268.0,
    "obla_4mmol_watts": 285.0,
    "aerobic_2mmol_watts": 195.0
  },
  "last_test_summary": {
    "points_count": 5,
    "mlss_dmax_watts": 268.0,
    "obla_4mmol_watts": 285.0,
    "aerobic_2mmol_watts": 195.0
  },
  "updated_at": "2026-06-17T12:00:00Z"
}
```

### Frontend rendering

- Chart: `lactate_state.latest_curve.points` (X=`power_w`, Y=`lactate_mmol`).
- Vertical reference lines: `thresholds.mlss_dmax_watts`, `obla_4mmol_watts`.
- Badge: **Lab measured** — not model estimate.

### API source for persistence bundle

`POST /test/in-person` (Mader with `test_data.steps`) returns:

```json
{
  "lactate_persistence": {
    "schema_version": "lactate_state.v1",
    "lactate_curve": { "...": "..." },
    "lactate_state": { "...": "..." },
    "db_contract": {
      "store_on": "twin_states.twin_state.lactate_state",
      "mirror_curve_on": "twin_states.twin_state.metabolic_curves.curves.lactate"
    }
  }
}
```

Merge into TwinState via `sync_lactate_state_from_steps()` or `POST /twin/state/update-from-ride` with `lactate_steps`.

---

## What stays on activities (not TwinState)

| Curve | Storage | Endpoint |
|-------|---------|----------|
| `session_fuel_demand` | `activities.summary` or analytics JSON | `/profile/metabolic/curves` with `power_series` |
| `w_prime_balance` | activity analytics | same |
| `durability_decay` | `activities.durability` or summary | `/ride/durability` |

---

## Backend sync hooks (VPS ingest worker)

| Event | Python helper | HTTP equivalent |
|-------|---------------|-----------------|
| Initial twin build | `build_twin_state()` → auto `sync_profile_metabolic_curves` | `POST /twin/state/build` |
| Profile refresh | `sync_twin_after_profile_refresh(twin, snapshot)` | `POST /ride/update-profile` (returns `metabolic_curves`) |
| After ingest + new snapshot | `update_twin_state_from_ride(..., metabolic_snapshot=...)` | `POST /twin/state/update-from-ride` |
| Lactate test | `sync_lactate_state_from_steps(twin, steps)` | `POST /test/in-person` → `lactate_persistence` |

Hook registry: `engines.twin_state.ingest_worker_hook_points()`.

### Recommended worker sequence (new FIT)

```text
1. Load twin_state from DB
2. Parse FIT → POST /ride/ingest (or RideService.ingest)
3. POST /ride/summary
4. If ingest.profile_should_refresh:
     snapshot ← POST /ride/update-profile OR profiler refresh
5. POST /twin/state/update-from-ride
     { twin_state, ingest_result, ride_summary, metabolic_snapshot }
6. Save twin_state + activity row (transaction)
```

`skip_metabolic_curves_sync: true` on build only when importing legacy twins without weight.

---

## Related docs

- `docs/FRONTEND_DEVELOPER_GUIDE.md` — Digital Twin page, tier badges
- `docs/STRENGTH_AND_FUELING_CONTRACT.md` — session fuel from `session_fuel_demand`
- `docs/CONTRACT_FIRST_TESTING.md` — `pytest_metabolic_curves_twin_sync.py`
