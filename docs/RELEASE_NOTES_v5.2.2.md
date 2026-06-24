# Release notes — V5.2.2

**Tag:** `v5.2.2`  
**Date:** 2026-06-17  
**Base:** `v5.2.1` (dual zone systems) + power-series VLamax proxy

## Summary

V5.2.2 adds a **power-derived VLamax proxy** (`cLaMax_P`) from maximal sprint power traces (8–30 s), exposed over HTTP and integrated into the glycolytic profile. The API surface grows to **106 OpenAPI paths** (+1 profile endpoint).

The proxy now uses a fixed **T_PCr = 3.5 s** for the alactic / PCr-dominant phase. The observed mechanical peak time (`t_Ppeak`) is retained only as protocol-quality metadata, not as the glycolytic-window boundary. This avoids bias when amateur athletes, indoor-trainer inertia or pacing cause peak power to occur after the first 3–4 seconds.

## Highlights

### Power-series VLamax proxy

- `engines/metabolic/power_vlamax_estimator.py` — sprint power trace → VLamax **proxy** (fixed T_PCr 3.5 s, protocol-quality `t_Ppeak`, oxidative fraction, FFM-normalized work, sustain-ratio gate).
- `POST /profile/vlamax-from-power-series` — standalone estimator from a power array.
- `POST /profile/glycolytic-profile` — optional `sprint_power`, `sprint_dt_s`, `cp_w`, `vo2max_power_w`, lactate fields → `power_derived_vlamax` and `vlamax_derivation.agreement`.
- Tests: `tests/pytest_power_vlamax_estimator.py`.
- Protocol reference: `docs/VLAMAX_POWER_PROXY_PROTOCOL.md`.

### Late mechanical peak handling

- `features.t_pcr_s` is fixed at `3.5`.
- `features.t_p_peak_s` reports the observed mechanical peak time.
- `late_power_peak_protocol_note` is emitted when the peak occurs after 3.5 s.
- `very_late_power_peak_protocol_note` is emitted when the peak occurs after 6.0 s.
- Late-peak flags are protocol notes for coach interpretation, not physiological error flags.
- Confidence is not penalized for normal late peak timing; very late peak timing receives only a mild penalty.

### Semantics (three levels)

| Field | Meaning |
|-------|---------|
| `estimated_vlamax_mmol_L_s` | Primary Mader/MMP model parameter |
| `power_derived_vlamax` | Explicit power proxy — **not** a blood measurement |
| `observed_vlapeak_mmol_l_s` | Blood-derived vLaPeak when lactate pre/post supplied |

UI must label each source separately; never show a proxy as a lab value.

### Inherited from V5.2.1

- Dual zone systems: `metabolic_power` + `coggan_power` on ride summaries and `/ride/analytics/zones`.
- `zones_engine` v1.1.0 with `systems_available` and `coach_note`.

## OpenAPI inventory (106 paths)

| Tag | Count |
|-----|------:|
| ride | 32 |
| profile | **15** |
| workouts | 9 |
| lab | 7 |
| explainability | 6 |
| twin | 6 |
| load | 5 |
| history | 4 |
| performance | 4 |
| planning | 3 |
| readiness | 3 |
| test | 3 |
| integrations | 2 |
| meta | 2 |
| race | 2 |
| team | 2 |
| health | 1 |

Full list: `docs/API_ENDPOINT_INDEX.md`

## Upgrade notes

1. Run `make openapi-frontend` after pulling — commit `openapi/openapi.json` + `schema.ts` if changed.
2. Digital Twin / glycolytic UI: show `power_derived_vlamax` with a **power proxy** badge when present; compare against Mader estimate via `vlamax_derivation.agreement`.
3. Sprint activities: pass `sprint_power` (≥8 Hz samples) on `/profile/glycolytic-profile` or call `/profile/vlamax-from-power-series` directly.
4. Coach UI: render late mechanical peak as a protocol note, not as failed physiology. Use `features.t_pcr_s` as the fixed glycolytic-window anchor and `features.t_p_peak_s` only for protocol interpretation.

## Release gate

```bash
make check
```

## Prior releases

- `docs/RELEASE_NOTES_v5.2.1.md` — dual metabolic + Coggan zones
- `docs/RELEASE_NOTES_v5.1.1.md` — frontend stabilization (tests + docs)
- `docs/RELEASE_NOTES_v5.1.0.md` — architectural baseline (router/service/engines)
