# Chart config contract — `/meta/chart-config`

The backend is the **only** chart computation layer. The frontend requests a `chart_type` + `payload` and renders the returned `config` (Recharts/ECharts/Plotly agnostic).

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/meta/chart-types` | Full catalog with `required_keys` per chart |
| POST | `/meta/chart-config` | Build one chart config |

## Request

```json
{
  "chart_type": "vo2_demand",
  "payload": {
    "metabolic_snapshot": { "status": "success", "estimated_vo2max": 58.0, "...": "..." },
    "weight_kg": 72.0
  }
}
```

## Response

```json
{
  "status": "success",
  "chart_type": "vo2_demand",
  "category": "metabolic",
  "config": {
    "schema_version": "chart_config.v1",
    "type": "line",
    "title": "VO2 demand (%VO2max vs watt)",
    "series": [ { "name": "% VO2max", "x": [120, 185], "y": [42.1, 58.2] } ],
    "measurement_tier": "MODEL_ESTIMATE"
  }
}
```

## Catalog (33 chart types)

### Profile / load (`chart_builder.py`)

| `chart_type` | Required payload keys |
|--------------|----------------------|
| `mmp`, `power_duration` | `mmp` |
| `zones` | `zones_data` (+ optional `system`) |
| `training_load` | `dates`, `ctl_values`, `atl_values`, `tsb_values` |
| `detraining` | `parameters`, `baseline_values`, `current_values`, `units` |
| `metabolic_combustion` | `power_points`, `fat_contribution`, `carb_contribution`, `anaerobic_contribution` |
| `efforts_radar` | `durations`, `pct_ftp`, `pct_cp`, `pct_mlss`, `pct_map` |
| `phenotype_spider` | `percentiles` |

### Session analytics (`chart_builder.py`)

| `chart_type` | Required payload keys |
|--------------|----------------------|
| `hrv` | `time_seconds`, `dfa_alpha1` |
| `cardiac_drift` | `segments` |
| `cross_validation_matrix` | `methods`, `vt1_powers`, `vt2_powers` |
| `hr_kinetics` | `time_seconds`, `hr_values` |
| `power_hr_scatter` | `power_values`, `hr_values` |
| `hr_recovery` | `recovery_segments` |

### Metabolic curves (TwinState / profiler)

| `chart_type` | Required payload keys | Notes |
|--------------|----------------------|-------|
| `vo2_demand` | `metabolic_snapshot`, `weight_kg` | Or pass prebuilt `curve` |
| `lactate` | `lactate_steps` | Or pass prebuilt `curve` |
| `substrate_oxidation` | `metabolic_snapshot`, `weight_kg` | Or `curve` |
| `session_fuel_demand` | `metabolic_snapshot`, `power`, `weight_kg` | Cumulative CHO + fat |
| `session_fuel_partitioning` | `metabolic_snapshot`, `power` | **CHO vs fat rate (g/min) + cumulative** |
| `w_prime_balance` | `power`, `cp_w`, `w_prime_j` | W′ % over time |

Prefer reading precomputed curves from `twin_state.metabolic_curves` and passing `payload.curve` to avoid recomputation.

### Activity stream (`activity_charts.py`)

Prefix `activity_*` — require `power[]` (1 Hz). Optional arrays in `stream_payload`: `elapsed_s`, `heart_rate`, `altitude_m`, `speed_mps`, `temperature_c`, …

| `chart_type` | Extra |
|--------------|-------|
| `activity_time_in_power_zone` | `zones` |
| `activity_time_in_intensity` | `hrv_durability` |
| Others | `power` only |

## TwinState shortcut

```typescript
const curve = twin.metabolic_curves?.curves?.vo2_demand;
await api.metaChartConfig({
  chart_type: "vo2_demand",
  payload: { curve },
});
```

## Registry

Implementation: `engines/io/chart_registry.py`  
Stream coercion: `engines/io/chart_stream.py`  
Tests: `tests/pytest_chart_config_registry.py`

## Related

- `docs/METABOLIC_CURVES_TWIN_CONTRACT.md` — persisted curves on twin
- `docs/FRONTEND_DEVELOPER_GUIDE.md` — Digital Twin charts
